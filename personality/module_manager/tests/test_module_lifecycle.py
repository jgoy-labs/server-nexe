"""
────────────────────────────────────
Server Nexe
Version: 0.8
Author: Jordi Goy 
Location: personality/module_manager/tests/test_module_lifecycle.py
Description: Tests per ModuleLifecycleManager. Valida load, start, stop de mòduls,

www.jgoy.net
────────────────────────────────────
"""

import pytest
import asyncio
import threading
from datetime import datetime, timezone
from unittest.mock import MagicMock, AsyncMock, patch

from personality.module_manager.module_lifecycle import ModuleLifecycleManager
from personality.data.models import ModuleInfo, ModuleState

@pytest.fixture
def mock_dependencies():
  """Create mock dependencies for lifecycle manager."""
  modules = {}
  loader = MagicMock()
  loader.load_module = AsyncMock(return_value=MagicMock())
  loader.unload_module = AsyncMock()

  registry = MagicMock()
  events = MagicMock()
  events.emit_event = AsyncMock()

  metrics = MagicMock()

  return {
    "modules": modules,
    "loader": loader,
    "registry": registry,
    "events": events,
    "metrics": metrics
  }

@pytest.fixture
def lifecycle_manager(mock_dependencies):
  """Create ModuleLifecycleManager instance."""
  return ModuleLifecycleManager(
    modules=mock_dependencies["modules"],
    loader=mock_dependencies["loader"],
    registry=mock_dependencies["registry"],
    events=mock_dependencies["events"],
    metrics=mock_dependencies["metrics"]
  )

@pytest.fixture
def mock_lock():
  """Create mock lock."""
  return threading.RLock()

@pytest.fixture
def mock_module_info():
  """Create mock ModuleInfo."""
  module = MagicMock(spec=ModuleInfo)
  module.name = "test_module"
  module.state = ModuleState.DISCOVERED
  module.enabled = True
  module.dependencies = []
  module.dependents = set()
  module.manifest = {}
  module.instance = None
  module.error_count = 0
  module.last_error = None
  return module

class TestModuleLifecycleManagerInit:
  """Tests for initialization."""

  def test_init(self, mock_dependencies):
    """Should initialize with all dependencies."""
    manager = ModuleLifecycleManager(
      modules=mock_dependencies["modules"],
      loader=mock_dependencies["loader"],
      registry=mock_dependencies["registry"],
      events=mock_dependencies["events"],
      metrics=mock_dependencies["metrics"],
      i18n=MagicMock()
    )

    assert manager.modules == mock_dependencies["modules"]
    assert manager.loader == mock_dependencies["loader"]
    assert manager.api_integrator is None

  def test_set_api_integrator(self, lifecycle_manager):
    """Should set API integrator."""
    mock_integrator = MagicMock()

    lifecycle_manager.set_api_integrator(mock_integrator)

    assert lifecycle_manager.api_integrator == mock_integrator

class TestModuleLifecycleManagerLoad:
  """Tests for load_module."""

  @pytest.mark.asyncio
  async def test_load_nonexistent_module(self, lifecycle_manager, mock_lock):
    """Should return False for non-existent module."""
    result = await lifecycle_manager.load_module("nonexistent", mock_lock)

    assert result is False

  @pytest.mark.asyncio
  async def test_load_already_loaded(self, lifecycle_manager, mock_lock, mock_module_info):
    """Should return True if already loaded."""
    mock_module_info.state = ModuleState.LOADED
    lifecycle_manager.modules["test"] = mock_module_info

    result = await lifecycle_manager.load_module("test", mock_lock)

    assert result is True

  @pytest.mark.asyncio
  async def test_load_already_running(self, lifecycle_manager, mock_lock, mock_module_info):
    """Should return True if already running."""
    mock_module_info.state = ModuleState.RUNNING
    lifecycle_manager.modules["test"] = mock_module_info

    result = await lifecycle_manager.load_module("test", mock_lock)

    assert result is True

  @pytest.mark.asyncio
  async def test_load_disabled_module(self, lifecycle_manager, mock_lock, mock_module_info):
    """Should return False for disabled module."""
    mock_module_info.enabled = False
    lifecycle_manager.modules["test"] = mock_module_info

    result = await lifecycle_manager.load_module("test", mock_lock)

    assert result is False

  @pytest.mark.asyncio
  async def test_load_currently_loading(self, lifecycle_manager, mock_lock, mock_module_info):
    """Should return False if already loading."""
    mock_module_info.state = ModuleState.LOADING
    lifecycle_manager.modules["test"] = mock_module_info

    result = await lifecycle_manager.load_module("test", mock_lock)

    assert result is False

  @pytest.mark.asyncio
  async def test_load_success(self, lifecycle_manager, mock_lock, mock_module_info):
    """Should load module successfully."""
    lifecycle_manager.modules["test"] = mock_module_info

    result = await lifecycle_manager.load_module("test", mock_lock)

    assert result is True
    assert mock_module_info.state == ModuleState.LOADED
    assert mock_module_info.instance is not None
    lifecycle_manager.loader.load_module.assert_called_once()
    lifecycle_manager.registry.register_module.assert_called_once()
    lifecycle_manager.events.emit_event.assert_called()

  @pytest.mark.asyncio
  async def test_load_with_api_integration(self, lifecycle_manager, mock_lock, mock_module_info):
    """Should integrate API when integrator available."""
    mock_integrator = MagicMock()
    lifecycle_manager.set_api_integrator(mock_integrator)
    lifecycle_manager.modules["test"] = mock_module_info

    await lifecycle_manager.load_module("test", mock_lock)

    mock_integrator.integrate_module_api.assert_called_once()

  @pytest.mark.asyncio
  async def test_load_error_handling(self, lifecycle_manager, mock_lock, mock_module_info):
    """Should handle load errors."""
    lifecycle_manager.loader.load_module = AsyncMock(side_effect=Exception("Load failed"))
    lifecycle_manager.modules["test"] = mock_module_info

    result = await lifecycle_manager.load_module("test", mock_lock)

    assert result is False
    assert mock_module_info.state == ModuleState.ERROR
    assert mock_module_info.error_count == 1
    assert mock_module_info.last_error == "Load failed"

  @pytest.mark.asyncio
  async def test_load_with_dependencies(self, lifecycle_manager, mock_lock):
    """Should load dependencies first."""
    dep_module = MagicMock(spec=ModuleInfo)
    dep_module.name = "dependency"
    dep_module.state = ModuleState.DISCOVERED
    dep_module.enabled = True
    dep_module.dependencies = []
    dep_module.dependents = set()
    dep_module.manifest = {}

    main_module = MagicMock(spec=ModuleInfo)
    main_module.name = "main"
    main_module.state = ModuleState.DISCOVERED
    main_module.enabled = True
    main_module.dependencies = ["dependency"]
    main_module.dependents = set()
    main_module.manifest = {}

    lifecycle_manager.modules["dependency"] = dep_module
    lifecycle_manager.modules["main"] = main_module

    result = await lifecycle_manager.load_module("main", mock_lock)

    assert result is True
    assert dep_module.state == ModuleState.LOADED
    assert main_module.state == ModuleState.LOADED

  @pytest.mark.asyncio
  async def test_load_dependency_failure(self, lifecycle_manager, mock_lock):
    """Should fail if dependency fails to load."""
    dep_module = MagicMock(spec=ModuleInfo)
    dep_module.name = "dependency"
    dep_module.state = ModuleState.DISCOVERED
    dep_module.enabled = False
    dep_module.dependencies = []

    main_module = MagicMock(spec=ModuleInfo)
    main_module.name = "main"
    main_module.state = ModuleState.DISCOVERED
    main_module.enabled = True
    main_module.dependencies = ["dependency"]

    lifecycle_manager.modules["dependency"] = dep_module
    lifecycle_manager.modules["main"] = main_module

    result = await lifecycle_manager.load_module("main", mock_lock)

    assert result is False

class TestModuleLifecycleManagerStart:
  """Tests for start_module."""

  @pytest.mark.asyncio
  async def test_start_nonexistent(self, lifecycle_manager, mock_lock):
    """Should return False for non-existent module."""
    result = await lifecycle_manager.start_module("nonexistent", mock_lock)

    assert result is False

  @pytest.mark.asyncio
  async def test_start_already_running(self, lifecycle_manager, mock_lock, mock_module_info):
    """Should return True if already running."""
    mock_module_info.state = ModuleState.RUNNING
    lifecycle_manager.modules["test"] = mock_module_info

    result = await lifecycle_manager.start_module("test", mock_lock)

    assert result is True

  @pytest.mark.asyncio
  async def test_start_loads_if_needed(self, lifecycle_manager, mock_lock, mock_module_info):
    """Should load module if not loaded."""
    mock_module_info.state = ModuleState.DISCOVERED
    lifecycle_manager.modules["test"] = mock_module_info

    result = await lifecycle_manager.start_module("test", mock_lock)

    assert result is True
    lifecycle_manager.loader.load_module.assert_called()

  @pytest.mark.asyncio
  async def test_start_calls_start_method(self, lifecycle_manager, mock_lock, mock_module_info):
    """Should call module's start method."""
    mock_module_info.state = ModuleState.LOADED
    mock_instance = MagicMock()
    mock_instance.start = MagicMock()
    mock_module_info.instance = mock_instance
    lifecycle_manager.modules["test"] = mock_module_info

    result = await lifecycle_manager.start_module("test", mock_lock)

    assert result is True
    mock_instance.start.assert_called_once()
    assert mock_module_info.state == ModuleState.RUNNING

  @pytest.mark.asyncio
  async def test_start_async_start_method(self, lifecycle_manager, mock_lock, mock_module_info):
    """Should handle async start method."""
    mock_module_info.state = ModuleState.LOADED
    mock_instance = MagicMock()
    mock_instance.start = AsyncMock()
    mock_module_info.instance = mock_instance
    lifecycle_manager.modules["test"] = mock_module_info

    result = await lifecycle_manager.start_module("test", mock_lock)

    assert result is True
    mock_instance.start.assert_called_once()

  @pytest.mark.asyncio
  async def test_start_error_handling(self, lifecycle_manager, mock_lock, mock_module_info):
    """Should handle start errors."""
    mock_module_info.state = ModuleState.LOADED
    mock_instance = MagicMock()
    mock_instance.start = MagicMock(side_effect=Exception("Start failed"))
    mock_module_info.instance = mock_instance
    lifecycle_manager.modules["test"] = mock_module_info

    result = await lifecycle_manager.start_module("test", mock_lock)

    assert result is False
    assert mock_module_info.state == ModuleState.ERROR
    assert mock_module_info.error_count == 1

  @pytest.mark.asyncio
  async def test_start_emits_event(self, lifecycle_manager, mock_lock, mock_module_info):
    """Should emit started event."""
    mock_module_info.state = ModuleState.LOADED
    mock_module_info.instance = MagicMock()
    lifecycle_manager.modules["test"] = mock_module_info

    await lifecycle_manager.start_module("test", mock_lock)

    lifecycle_manager.events.emit_event.assert_called()

class TestModuleLifecycleManagerStop:
  """Tests for stop_module."""

  @pytest.mark.asyncio
  async def test_stop_nonexistent(self, lifecycle_manager, mock_lock):
    """Should return True for non-existent module."""
    result = await lifecycle_manager.stop_module("nonexistent", mock_lock)

    assert result is True

  @pytest.mark.asyncio
  async def test_stop_already_stopped(self, lifecycle_manager, mock_lock, mock_module_info):
    """Should return True if already stopped."""
    mock_module_info.state = ModuleState.STOPPED
    lifecycle_manager.modules["test"] = mock_module_info

    result = await lifecycle_manager.stop_module("test", mock_lock)

    assert result is True

  @pytest.mark.asyncio
  async def test_stop_running_module(self, lifecycle_manager, mock_lock, mock_module_info):
    """Should stop running module."""
    mock_module_info.state = ModuleState.RUNNING
    mock_instance = MagicMock()
    mock_instance.stop = MagicMock()
    mock_module_info.instance = mock_instance
    lifecycle_manager.modules["test"] = mock_module_info

    result = await lifecycle_manager.stop_module("test", mock_lock)

    assert result is True
    mock_instance.stop.assert_called_once()
    assert mock_module_info.state == ModuleState.STOPPED
    assert mock_module_info.instance is None

  @pytest.mark.asyncio
  async def test_stop_async_stop_method(self, lifecycle_manager, mock_lock, mock_module_info):
    """Should handle async stop method."""
    mock_module_info.state = ModuleState.RUNNING
    mock_instance = MagicMock()
    mock_instance.stop = AsyncMock()
    mock_module_info.instance = mock_instance
    lifecycle_manager.modules["test"] = mock_module_info

    result = await lifecycle_manager.stop_module("test", mock_lock)

    assert result is True
    mock_instance.stop.assert_called_once()

  @pytest.mark.asyncio
  async def test_stop_unloads_module(self, lifecycle_manager, mock_lock, mock_module_info):
    """Should unload module via loader."""
    mock_module_info.state = ModuleState.RUNNING
    mock_module_info.instance = MagicMock()
    lifecycle_manager.modules["test"] = mock_module_info

    await lifecycle_manager.stop_module("test", mock_lock)

    lifecycle_manager.loader.unload_module.assert_called_once_with("test")

  @pytest.mark.asyncio
  async def test_stop_unregisters_module(self, lifecycle_manager, mock_lock, mock_module_info):
    """Should unregister from registry."""
    mock_module_info.state = ModuleState.RUNNING
    mock_module_info.instance = MagicMock()
    lifecycle_manager.modules["test"] = mock_module_info

    await lifecycle_manager.stop_module("test", mock_lock)

    lifecycle_manager.registry.unregister_module.assert_called_once_with("test")

  @pytest.mark.asyncio
  async def test_stop_removes_api(self, lifecycle_manager, mock_lock, mock_module_info):
    """Should remove API when integrator available."""
    mock_integrator = MagicMock()
    lifecycle_manager.set_api_integrator(mock_integrator)
    mock_module_info.state = ModuleState.RUNNING
    mock_module_info.instance = MagicMock()
    lifecycle_manager.modules["test"] = mock_module_info

    await lifecycle_manager.stop_module("test", mock_lock)

    mock_integrator.remove_module_api.assert_called_once_with("test")

  @pytest.mark.asyncio
  async def test_stop_emits_event(self, lifecycle_manager, mock_lock, mock_module_info):
    """Should emit stopped event."""
    mock_module_info.state = ModuleState.RUNNING
    mock_module_info.instance = MagicMock()
    lifecycle_manager.modules["test"] = mock_module_info

    await lifecycle_manager.stop_module("test", mock_lock)

    lifecycle_manager.events.emit_event.assert_called()

  @pytest.mark.asyncio
  async def test_stop_error_handling(self, lifecycle_manager, mock_lock, mock_module_info):
    """Should handle stop errors."""
    mock_module_info.state = ModuleState.RUNNING
    mock_instance = MagicMock()
    mock_instance.stop = MagicMock(side_effect=Exception("Stop failed"))
    mock_module_info.instance = mock_instance
    lifecycle_manager.modules["test"] = mock_module_info

    result = await lifecycle_manager.stop_module("test", mock_lock)

    assert result is False