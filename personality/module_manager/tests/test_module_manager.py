"""
────────────────────────────────────
Server Nexe
Version: 0.8
Author: Jordi Goy 
Location: personality/module_manager/tests/test_module_manager.py
Description: Tests per ModuleManager facade. Valida coordinació de components,

www.jgoy.net · https://server-nexe.org
────────────────────────────────────
"""

import pytest
from pathlib import Path
from unittest.mock import patch, MagicMock, AsyncMock
from datetime import datetime, timezone

from personality.data.models import ModuleInfo, ModuleState

class TestModuleManagerInitialization:
  """Tests for ModuleManager initialization."""

  @patch('personality.module_manager.module_manager.I18nManager')
  @patch('personality.module_manager.module_manager.ConfigManager')
  @patch('personality.module_manager.module_manager.EventSystem')
  @patch('personality.module_manager.module_manager.MetricsCollector')
  @patch('personality.module_manager.module_manager.ModuleRegistry')
  @patch('personality.module_manager.module_manager.ModuleLoader')
  @patch('personality.module_manager.module_manager.PathDiscovery')
  @patch('personality.module_manager.module_manager.ModuleLifecycleManager')
  @patch('personality.module_manager.module_manager.SystemLifecycleManager')
  def test_init_creates_all_components(
    self, mock_sys_lifecycle, mock_mod_lifecycle, mock_path_discovery,
    mock_loader, mock_registry, mock_metrics, mock_events,
    mock_config_manager, mock_i18n
  ):
    """ModuleManager should initialize all facade components."""
    from personality.module_manager.module_manager import ModuleManager

    mock_config = MagicMock()
    mock_config.config_path = Path("/fake/config.toml")
    mock_config.manifests_path = Path("/fake/manifests")
    mock_config.get_config.return_value = {}
    mock_config_manager.return_value = mock_config

    mock_i18n_instance = MagicMock()
    mock_i18n.return_value = mock_i18n_instance

    manager = ModuleManager(config_path=Path("/fake/config.toml"))

    assert mock_i18n.called
    assert mock_config_manager.called
    assert mock_events.called
    assert mock_metrics.called
    assert mock_registry.called
    assert mock_loader.called
    assert mock_path_discovery.called
    assert mock_mod_lifecycle.called
    assert mock_sys_lifecycle.called

  @patch('personality.module_manager.module_manager.I18nManager')
  @patch('personality.module_manager.module_manager.ConfigManager')
  @patch('personality.module_manager.module_manager.EventSystem')
  @patch('personality.module_manager.module_manager.MetricsCollector')
  @patch('personality.module_manager.module_manager.ModuleRegistry')
  @patch('personality.module_manager.module_manager.ModuleLoader')
  @patch('personality.module_manager.module_manager.PathDiscovery')
  @patch('personality.module_manager.module_manager.ModuleLifecycleManager')
  @patch('personality.module_manager.module_manager.SystemLifecycleManager')
  def test_init_not_running(
    self, mock_sys_lifecycle, mock_mod_lifecycle, mock_path_discovery,
    mock_loader, mock_registry, mock_metrics, mock_events,
    mock_config_manager, mock_i18n
  ):
    """ModuleManager should start in not running state."""
    from personality.module_manager.module_manager import ModuleManager

    mock_config = MagicMock()
    mock_config.config_path = Path("/fake/config.toml")
    mock_config.manifests_path = Path("/fake/manifests")
    mock_config.get_config.return_value = {}
    mock_config_manager.return_value = mock_config

    manager = ModuleManager(config_path=Path("/fake/config.toml"))

    assert manager._running is False
    assert len(manager._modules) == 0

class TestModuleManagerModuleListing:
  """Tests for module listing functionality."""

  def test_list_modules_empty(self):
    """Should return empty list when no modules."""
    from personality.module_manager.module_manager import ModuleManager

    with patch.object(ModuleManager, '__init__', lambda x, **kwargs: None):
      manager = ModuleManager()
      manager._modules = {}
      manager._lock = MagicMock()

      result = manager.list_modules()

      assert result == []

  def test_list_modules_returns_sorted_by_priority(self):
    """Should return modules sorted by priority."""
    from personality.module_manager.module_manager import ModuleManager

    with patch.object(ModuleManager, '__init__', lambda x, **kwargs: None):
      manager = ModuleManager()
      manager._lock = MagicMock()

      module_low = MagicMock(spec=ModuleInfo)
      module_low.priority = 100
      module_low.state = ModuleState.LOADED

      module_high = MagicMock(spec=ModuleInfo)
      module_high.priority = 1
      module_high.state = ModuleState.LOADED

      module_mid = MagicMock(spec=ModuleInfo)
      module_mid.priority = 50
      module_mid.state = ModuleState.LOADED

      manager._modules = {
        "low": module_low,
        "high": module_high,
        "mid": module_mid
      }

      result = manager.list_modules()

      assert len(result) == 3
      assert result[0].priority == 1
      assert result[1].priority == 50
      assert result[2].priority == 100

  def test_list_modules_with_state_filter(self):
    """Should filter modules by state."""
    from personality.module_manager.module_manager import ModuleManager

    with patch.object(ModuleManager, '__init__', lambda x, **kwargs: None):
      manager = ModuleManager()
      manager._lock = MagicMock()

      module_running = MagicMock(spec=ModuleInfo)
      module_running.state = ModuleState.RUNNING
      module_running.priority = 1

      module_loaded = MagicMock(spec=ModuleInfo)
      module_loaded.state = ModuleState.LOADED
      module_loaded.priority = 2

      manager._modules = {
        "running": module_running,
        "loaded": module_loaded
      }

      result = manager.list_modules(state_filter=ModuleState.RUNNING)

      assert len(result) == 1
      assert result[0].state == ModuleState.RUNNING

class TestModuleManagerGetModuleInfo:
  """Tests for get_module_info functionality."""

  def test_get_module_info_existing(self):
    """Should return module info for existing module."""
    from personality.module_manager.module_manager import ModuleManager

    with patch.object(ModuleManager, '__init__', lambda x, **kwargs: None):
      manager = ModuleManager()

      mock_module = MagicMock(spec=ModuleInfo)
      mock_module.name = "test_module"
      manager._modules = {"test_module": mock_module}

      result = manager.get_module_info("test_module")

      assert result == mock_module

  def test_get_module_info_nonexistent(self):
    """Should return None for nonexistent module."""
    from personality.module_manager.module_manager import ModuleManager

    with patch.object(ModuleManager, '__init__', lambda x, **kwargs: None):
      manager = ModuleManager()
      manager._modules = {}

      result = manager.get_module_info("nonexistent")

      assert result is None

class TestModuleManagerSystemStatus:
  """Tests for system status functionality."""

  def test_get_system_status_not_running(self):
    """Should return status when system not running."""
    from personality.module_manager.module_manager import ModuleManager

    with patch.object(ModuleManager, '__init__', lambda x, **kwargs: None):
      manager = ModuleManager()
      manager._running = False
      manager._modules = {}
      manager._system_start_time = datetime.now(timezone.utc)

      mock_metrics = MagicMock()
      mock_metrics.get_system_metrics.return_value = {}
      manager.metrics = mock_metrics

      mock_path_discovery = MagicMock()
      mock_path_discovery.get_stats.return_value = {}
      manager.path_discovery = mock_path_discovery

      result = manager.get_system_status()

      assert result["running"] is False
      assert result["total_modules"] == 0
      assert "modules_by_state" in result
      assert "metrics" in result
      assert "uptime_seconds" in result

  def test_get_system_status_with_modules(self):
    """Should count modules by state correctly."""
    from personality.module_manager.module_manager import ModuleManager

    with patch.object(ModuleManager, '__init__', lambda x, **kwargs: None):
      manager = ModuleManager()
      manager._running = True
      manager._system_start_time = datetime.now(timezone.utc)

      module1 = MagicMock()
      module1.state = ModuleState.RUNNING

      module2 = MagicMock()
      module2.state = ModuleState.RUNNING

      module3 = MagicMock()
      module3.state = ModuleState.LOADED

      manager._modules = {
        "mod1": module1,
        "mod2": module2,
        "mod3": module3
      }

      mock_metrics = MagicMock()
      mock_metrics.get_system_metrics.return_value = {}
      manager.metrics = mock_metrics

      mock_path_discovery = MagicMock()
      mock_path_discovery.get_stats.return_value = {}
      manager.path_discovery = mock_path_discovery

      result = manager.get_system_status()

      assert result["running"] is True
      assert result["total_modules"] == 3
      assert result["modules_by_state"][ModuleState.RUNNING.value] == 2
      assert result["modules_by_state"][ModuleState.LOADED.value] == 1

class TestModuleManagerUpdateEnabled:
  """Tests for update_module_enabled functionality."""

  def test_update_enabled_nonexistent_module(self):
    """Should return False for nonexistent module."""
    from personality.module_manager.module_manager import ModuleManager

    with patch.object(ModuleManager, '__init__', lambda x, **kwargs: None):
      manager = ModuleManager()
      manager._modules = {}

      result = manager.update_module_enabled("nonexistent", True)

      assert result is False

  def test_update_enabled_cannot_disable_core(self):
    """Should prevent disabling core modules."""
    from personality.module_manager.module_manager import ModuleManager

    with patch.object(ModuleManager, '__init__', lambda x, **kwargs: None):
      manager = ModuleManager()

      mock_module = MagicMock()
      mock_module.path = Path("/project/core/module")
      manager._modules = {"core_module": mock_module}

      result = manager.update_module_enabled("core_module", False)

      assert result is False

  def test_update_enabled_success(self):
    """Should update module enabled state."""
    from personality.module_manager.module_manager import ModuleManager

    with patch.object(ModuleManager, '__init__', lambda x, **kwargs: None):
      manager = ModuleManager()

      mock_module = MagicMock()
      mock_module.path = Path("/project/modules/custom")
      mock_module.enabled = True
      mock_module.state = ModuleState.LOADED
      manager._modules = {"custom_module": mock_module}

      mock_config = MagicMock()
      mock_config.update_module_enabled.return_value = True
      manager.config_manager = mock_config

      result = manager.update_module_enabled("custom_module", False)

      assert result is True
      assert mock_module.enabled is False
      assert mock_module.state == ModuleState.DISABLED

class TestModuleManagerEventListener:
  """Tests for event listener functionality."""

  def test_add_event_listener_delegates(self):
    """Should delegate to EventSystem."""
    from personality.module_manager.module_manager import ModuleManager

    with patch.object(ModuleManager, '__init__', lambda x, **kwargs: None):
      manager = ModuleManager()

      mock_events = MagicMock()
      manager.events = mock_events

      callback = lambda x: x
      manager.add_event_listener(callback, "test_event")

      mock_events.add_event_listener.assert_called_once_with(callback, "test_event")

class TestModuleManagerMetrics:
  """Tests for metrics functionality."""

  def test_get_module_metrics_existing(self):
    """Should return metrics for existing module."""
    from personality.module_manager.module_manager import ModuleManager

    with patch.object(ModuleManager, '__init__', lambda x, **kwargs: None):
      manager = ModuleManager()

      mock_module = MagicMock()
      manager._modules = {"test": mock_module}

      mock_metrics = MagicMock()
      mock_metrics.get_module_metrics.return_value = {"metric1": 100}
      manager.metrics = mock_metrics

      result = manager.get_module_metrics("test")

      assert result == {"metric1": 100}
      mock_metrics.get_module_metrics.assert_called_once_with(mock_module)

  def test_get_module_metrics_nonexistent(self):
    """Should return empty dict for nonexistent module."""
    from personality.module_manager.module_manager import ModuleManager

    with patch.object(ModuleManager, '__init__', lambda x, **kwargs: None):
      manager = ModuleManager()
      manager._modules = {}
      manager.metrics = MagicMock()

      result = manager.get_module_metrics("nonexistent")

      assert result == {}

class TestModuleManagerApiIntegrator:
  """Tests for API integrator functionality."""

  def test_set_api_integrator(self):
    """Should set API integrator on manager and lifecycle."""
    from personality.module_manager.module_manager import ModuleManager

    with patch.object(ModuleManager, '__init__', lambda x, **kwargs: None):
      manager = ModuleManager()

      mock_lifecycle = MagicMock()
      manager.module_lifecycle = mock_lifecycle

      mock_integrator = MagicMock()
      manager.set_api_integrator(mock_integrator)

      assert manager.api_integrator == mock_integrator
      mock_lifecycle.set_api_integrator.assert_called_once_with(mock_integrator)

class TestModuleManagerRegistryInfo:
  """Tests for registry info functionality."""

  def test_get_registry_info_delegates(self):
    """Should delegate to ModuleRegistry."""
    from personality.module_manager.module_manager import ModuleManager

    with patch.object(ModuleManager, '__init__', lambda x, **kwargs: None):
      manager = ModuleManager()

      mock_registry = MagicMock()
      mock_registry.get_registry_stats.return_value = {"total": 5}
      manager.registry = mock_registry

      result = manager.get_registry_info()

      assert result == {"total": 5}
      mock_registry.get_registry_stats.assert_called_once()

class TestModuleManagerConfigPath:
  """Tests for config path discovery."""

  def test_find_initial_config_explicit_path(self):
    """Should use explicit config path if provided and exists."""
    from personality.module_manager.module_manager import ModuleManager

    with patch.object(ModuleManager, '__init__', lambda x, **kwargs: None):
      manager = ModuleManager()

      # Mock security validation to allow test path
      with patch('personality.module_manager.module_manager.SECURITY_VALIDATION_AVAILABLE', False):
        with patch('pathlib.Path.exists', return_value=True):
          result = manager._find_initial_config(Path("/explicit/config.toml"))

      assert result == Path("/explicit/config.toml")

  def test_find_initial_config_searches_paths(self):
    """Should search standard paths if no explicit path."""
    from personality.module_manager.module_manager import ModuleManager

    with patch.object(ModuleManager, '__init__', lambda x, **kwargs: None):
      manager = ModuleManager()

      call_count = [0]
      def mock_exists(self):
        call_count[0] += 1
        return call_count[0] == 2

      with patch.object(Path, 'exists', mock_exists):
        with patch.object(Path, 'resolve', lambda self: self):
          result = manager._find_initial_config(None)

      assert isinstance(result, Path)

  def test_find_initial_config_default_fallback(self):
    """Should return default path if nothing found."""
    from personality.module_manager.module_manager import ModuleManager

    with patch.object(ModuleManager, '__init__', lambda x, **kwargs: None):
      manager = ModuleManager()

      with patch.object(Path, 'exists', return_value=False):
        result = manager._find_initial_config(None)

      assert result == Path("personality/server.toml")