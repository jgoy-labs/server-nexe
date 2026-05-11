"""
Tests for personality/module_manager/system_lifecycle.py
Covers uncovered lines: 49-82, 86-100, 104, 108
"""
import pytest
from unittest.mock import MagicMock, AsyncMock

from personality.module_manager.system_lifecycle import SystemLifecycleManager
from personality.module_manager.module_lifecycle import ModuleLifecycleManager
from personality.module_manager.types import SystemLifecycleConfig


def _make_module_info(name="mod", auto_start=True, enabled=True, state=None):
    info = MagicMock()
    info.name = name
    info.auto_start = auto_start
    info.enabled = enabled
    if state:
        info.state = state
    return info


def _make_slm(modules=None, lifecycle=None, discovery=None, list_modules=None, i18n=None):
    """Helper to build SystemLifecycleManager via SystemLifecycleConfig."""
    return SystemLifecycleManager(SystemLifecycleConfig(
        modules=modules if modules is not None else {},
        module_lifecycle=lifecycle or MagicMock(spec=ModuleLifecycleManager),
        discovery_func=discovery or AsyncMock(),
        list_modules_func=list_modules or MagicMock(),
        i18n=i18n,
    ))


class TestStartSystem:
    """Tests for start_system (lines 49-82)"""

    @pytest.mark.asyncio
    async def test_start_system_success(self):
        """Lines 49-74: successful startup"""
        mod_info = _make_module_info()
        discovery = AsyncMock(return_value=["mod"])
        list_modules = MagicMock(return_value=[mod_info])
        lifecycle = MagicMock(spec=ModuleLifecycleManager)
        lifecycle.load_module = AsyncMock(return_value=True)
        lifecycle.start_module = AsyncMock(return_value=True)

        mgr = _make_slm(lifecycle=lifecycle, discovery=discovery, list_modules=list_modules)

        result = await mgr.start_system()
        assert result is True
        assert mgr.is_running() is True
        discovery.assert_awaited_once_with(force=True)

    @pytest.mark.asyncio
    async def test_start_system_skips_disabled(self):
        """Lines 60: skips non-auto_start or disabled modules"""
        mod_info = _make_module_info(auto_start=False, enabled=True)
        discovery = AsyncMock(return_value=[])
        list_modules = MagicMock(return_value=[mod_info])
        lifecycle = MagicMock(spec=ModuleLifecycleManager)
        lifecycle.load_module = AsyncMock(return_value=True)
        lifecycle.start_module = AsyncMock(return_value=True)

        mgr = _make_slm(lifecycle=lifecycle, discovery=discovery, list_modules=list_modules)

        result = await mgr.start_system()
        assert result is True
        lifecycle.load_module.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_start_system_load_fails(self):
        """Lines 61-62: module load returns False"""
        mod_info = _make_module_info()
        discovery = AsyncMock(return_value=["mod"])
        list_modules = MagicMock(return_value=[mod_info])
        lifecycle = MagicMock(spec=ModuleLifecycleManager)
        lifecycle.load_module = AsyncMock(return_value=False)
        lifecycle.start_module = AsyncMock(return_value=True)

        mgr = _make_slm(lifecycle=lifecycle, discovery=discovery, list_modules=list_modules)

        result = await mgr.start_system()
        assert result is True
        lifecycle.start_module.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_start_system_exception(self):
        """Lines 76-82: exception during startup"""
        discovery = AsyncMock(side_effect=RuntimeError("discovery fail"))
        list_modules = MagicMock(return_value=[])

        mgr = _make_slm(discovery=discovery, list_modules=list_modules)

        result = await mgr.start_system()
        assert result is False
        assert mgr.is_running() is False


class TestShutdownSystem:
    """Tests for shutdown_system (lines 86-100)"""

    @pytest.mark.asyncio
    async def test_shutdown_running_modules(self):
        """Lines 86-100: stops all running modules"""
        from personality.data.models import ModuleState
        mod_info = _make_module_info(state=ModuleState.RUNNING)
        lifecycle = MagicMock(spec=ModuleLifecycleManager)
        lifecycle.stop_module = AsyncMock()
        list_modules = MagicMock(return_value=[mod_info])

        mgr = _make_slm(lifecycle=lifecycle, list_modules=list_modules)
        mgr._running = True

        await mgr.shutdown_system()
        assert mgr.is_running() is False
        lifecycle.stop_module.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_shutdown_no_running_modules(self):
        """Lines 86-100: no running modules"""
        lifecycle = MagicMock(spec=ModuleLifecycleManager)
        lifecycle.stop_module = AsyncMock()
        list_modules = MagicMock(return_value=[])

        mgr = _make_slm(lifecycle=lifecycle, list_modules=list_modules)
        mgr._running = True

        await mgr.shutdown_system()
        assert mgr.is_running() is False
        lifecycle.stop_module.assert_not_awaited()


class TestIsRunningAndGetLock:
    """Tests for is_running and _get_lock (lines 104, 108)"""

    def test_is_running_default_false(self):
        """Line 104"""
        mgr = _make_slm()
        assert mgr.is_running() is False

    def test_get_lock_returns_none(self):
        """Line 108"""
        mgr = _make_slm()
        assert mgr._get_lock() is None
