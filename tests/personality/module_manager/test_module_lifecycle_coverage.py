"""
Tests for uncovered lines in personality/module_manager/module_lifecycle.py.
Targets: 31 lines missing
"""
import asyncio
import threading
import pytest
from unittest.mock import MagicMock, AsyncMock, patch
from personality.data.models import ModuleInfo, ModuleState, SystemEvent
from pathlib import Path


def _make_module_info(name, state=ModuleState.DISCOVERED, enabled=True, deps=None):
    return ModuleInfo(
        name=name, path=Path(f"/fake/{name}"),
        manifest_path=Path(f"/fake/{name}/manifest.toml"),
        state=state, enabled=enabled,
        dependencies=deps or []
    )


class TestModuleLifecycleManager:

    @pytest.fixture
    def lm(self):
        from personality.module_manager.module_lifecycle import ModuleLifecycleManager
        modules = {}
        loader = MagicMock()
        loader.load_module = AsyncMock(return_value=MagicMock())
        loader.unload_module = AsyncMock()
        registry = MagicMock()
        events = MagicMock()
        events.emit_event = AsyncMock()
        metrics = MagicMock()
        return ModuleLifecycleManager(modules, loader, registry, events, metrics)

    def test_load_module_not_in_modules(self, lm):
        """Line 64-65: module not in modules dict."""
        lock = threading.RLock()
        result = asyncio.run(lm.load_module("nonexistent"))
        assert result is False

    def test_load_module_already_loaded(self, lm):
        """Lines 69-70: module already loaded."""
        lock = threading.RLock()
        mod = _make_module_info("test", state=ModuleState.LOADED)
        lm.modules["test"] = mod
        result = asyncio.run(lm.load_module("test"))
        assert result is True

    def test_load_module_disabled(self, lm):
        """Lines 72-77: module disabled."""
        lock = threading.RLock()
        mod = _make_module_info("test", enabled=False)
        lm.modules["test"] = mod
        result = asyncio.run(lm.load_module("test"))
        assert result is False

    def test_load_module_loading_state(self, lm):
        """Lines 79-80: module already loading."""
        lock = threading.RLock()
        mod = _make_module_info("test", state=ModuleState.LOADING)
        lm.modules["test"] = mod
        result = asyncio.run(lm.load_module("test"))
        assert result is False

    def test_load_module_dependency_failed(self, lm):
        """Lines 82-88: dependency load fails."""
        lock = threading.RLock()
        mod = _make_module_info("test", deps=["missing_dep"])
        lm.modules["test"] = mod
        result = asyncio.run(lm.load_module("test"))
        assert result is False

    def test_load_module_with_api_integrator(self, lm):
        """Lines 118-127: api_integrator integration."""
        lock = threading.RLock()
        mod = _make_module_info("test")
        lm.modules["test"] = mod
        mock_integrator = MagicMock()
        lm.api_integrator = mock_integrator

        result = asyncio.run(lm.load_module("test"))
        assert result is True
        mock_integrator.integrate_module_api.assert_called_once()

    def test_load_module_api_integrator_failure(self, lm):
        """Lines 123-127: api_integrator integration fails."""
        lock = threading.RLock()
        mod = _make_module_info("test")
        lm.modules["test"] = mod
        mock_integrator = MagicMock()
        mock_integrator.integrate_module_api.side_effect = Exception("fail")
        lm.api_integrator = mock_integrator

        result = asyncio.run(lm.load_module("test"))
        assert result is True  # Module still loads despite API error

    def test_load_module_error(self, lm):
        """Lines 147-158: load raises exception."""
        lock = threading.RLock()
        mod = _make_module_info("test")
        lm.modules["test"] = mod
        lm.loader.load_module = AsyncMock(side_effect=Exception("load error"))

        result = asyncio.run(lm.load_module("test"))
        assert result is False
        assert mod.state == ModuleState.ERROR
        assert mod.error_count == 1

    def test_start_module_not_found(self, lm):
        """Lines 172-173: start module not in modules."""
        lock = threading.RLock()
        result = asyncio.run(lm.start_module("nonexistent"))
        assert result is False

    def test_start_module_already_running(self, lm):
        """Lines 177-178: already running."""
        lock = threading.RLock()
        mod = _make_module_info("test", state=ModuleState.RUNNING)
        lm.modules["test"] = mod
        result = asyncio.run(lm.start_module("test"))
        assert result is True

    def test_start_module_sync_start(self, lm):
        """Lines 198-199: sync start() method."""
        lock = threading.RLock()
        mod = _make_module_info("test", state=ModuleState.LOADED)
        mock_instance = MagicMock()
        mock_instance.start = MagicMock()  # sync
        mod.instance = mock_instance
        lm.modules["test"] = mod

        result = asyncio.run(lm.start_module("test"))
        assert result is True
        mock_instance.start.assert_called_once()

    def test_start_module_error(self, lm):
        """Lines 222-233: start fails."""
        lock = threading.RLock()
        mod = _make_module_info("test", state=ModuleState.LOADED)
        mock_instance = MagicMock()
        mock_instance.start.side_effect = Exception("start failed")
        mod.instance = mock_instance
        lm.modules["test"] = mod

        result = asyncio.run(lm.start_module("test"))
        assert result is False
        assert mod.state == ModuleState.ERROR

    def test_stop_module_not_found(self, lm):
        """Lines 247-248: stop non-existent module."""
        lock = threading.RLock()
        result = asyncio.run(lm.stop_module("nonexistent"))
        assert result is True

    def test_stop_module_not_running(self, lm):
        """Lines 252-253: not in running/loaded state."""
        lock = threading.RLock()
        mod = _make_module_info("test", state=ModuleState.STOPPED)
        lm.modules["test"] = mod
        result = asyncio.run(lm.stop_module("test"))
        assert result is True

    def test_stop_module_sync_stop(self, lm):
        """Lines 267-268: sync stop() method."""
        lock = threading.RLock()
        mod = _make_module_info("test", state=ModuleState.RUNNING)
        mock_instance = MagicMock()
        mock_instance.stop = MagicMock()  # sync
        mod.instance = mock_instance
        lm.modules["test"] = mod

        result = asyncio.run(lm.stop_module("test"))
        assert result is True
        mock_instance.stop.assert_called_once()

    def test_stop_module_with_api_integrator(self, lm):
        """Lines 272-279: api_integrator removal."""
        lock = threading.RLock()
        mod = _make_module_info("test", state=ModuleState.RUNNING)
        mod.instance = MagicMock(spec=[])
        lm.modules["test"] = mod

        mock_integrator = MagicMock()
        lm.api_integrator = mock_integrator

        result = asyncio.run(lm.stop_module("test"))
        assert result is True
        mock_integrator.remove_module_api.assert_called_once()

    def test_stop_module_error(self, lm):
        """Lines 302-308: stop fails."""
        lock = threading.RLock()
        mod = _make_module_info("test", state=ModuleState.RUNNING)
        mod.instance = MagicMock()
        lm.modules["test"] = mod
        lm.loader.unload_module = AsyncMock(side_effect=Exception("stop error"))

        result = asyncio.run(lm.stop_module("test"))
        assert result is False

    def test_set_api_integrator(self, lm):
        mock = MagicMock()
        lm.set_api_integrator(mock)
        assert lm.api_integrator is mock

    def test_load_module_with_dependencies(self, lm):
        """Lines 82-88, 111-113: successful dependency chain + dependents tracking."""
        lock = threading.RLock()
        dep_mod = _make_module_info("dep_mod")
        main_mod = _make_module_info("main_mod", deps=["dep_mod"])
        lm.modules["dep_mod"] = dep_mod
        lm.modules["main_mod"] = main_mod

        result = asyncio.run(lm.load_module("main_mod"))
        assert result is True
        # dep_mod should track main_mod as dependent
        assert "main_mod" in dep_mod.dependents

    def test_load_module_logger_available_false(self, lm):
        """Lines 74-76, 85-87, 95-97, 140-142, 154-156:
        LOGGER_AVAILABLE is False so these branches don't execute."""
        # This test just verifies no crash when LOGGER_AVAILABLE=False
        lock = threading.RLock()
        mod = _make_module_info("test", enabled=False)
        lm.modules["test"] = mod
        result = asyncio.run(lm.load_module("test"))
        assert result is False

    def test_start_module_needs_load_first(self, lm):
        """Lines 180-183: module not loaded, auto-loads first."""
        lock = threading.RLock()
        mod = _make_module_info("test", state=ModuleState.DISCOVERED)
        lm.modules["test"] = mod

        result = asyncio.run(lm.start_module("test"))
        assert result is True
        assert mod.state == ModuleState.RUNNING

    def test_start_module_async_start(self, lm):
        """Lines 196-197: async start() method."""
        lock = threading.RLock()
        mod = _make_module_info("test", state=ModuleState.LOADED)
        mock_instance = MagicMock()
        mock_instance.start = AsyncMock()
        mod.instance = mock_instance
        lm.modules["test"] = mod

        result = asyncio.run(lm.start_module("test"))
        assert result is True
        mock_instance.start.assert_called_once()

    def test_stop_module_async_stop(self, lm):
        """Lines 265-266: async stop() method."""
        lock = threading.RLock()
        mod = _make_module_info("test", state=ModuleState.RUNNING)
        mock_instance = MagicMock()
        mock_instance.stop = AsyncMock()
        mod.instance = mock_instance
        lm.modules["test"] = mod

        result = asyncio.run(lm.stop_module("test"))
        assert result is True
        mock_instance.stop.assert_called_once()

    def test_stop_module_api_integrator_error(self, lm):
        """Lines 275-279: api_integrator removal error is handled."""
        lock = threading.RLock()
        mod = _make_module_info("test", state=ModuleState.RUNNING)
        mod.instance = MagicMock(spec=[])
        lm.modules["test"] = mod

        mock_integrator = MagicMock()
        mock_integrator.remove_module_api.side_effect = Exception("removal error")
        lm.api_integrator = mock_integrator

        result = asyncio.run(lm.stop_module("test"))
        assert result is True  # Still succeeds
