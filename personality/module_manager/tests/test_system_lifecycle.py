"""
Tests for personality/module_manager/system_lifecycle.py
Covers uncovered lines: 49-82, 86-100, 104, 108
"""
import pytest
from unittest.mock import MagicMock, AsyncMock

from personality.module_manager.system_lifecycle import SystemLifecycleManager


def _make_module_info(name="mod", auto_start=True, enabled=True, state=None):
    info = MagicMock()
    info.name = name
    info.auto_start = auto_start
    info.enabled = enabled
    if state:
        info.state = state
    return info


class TestStartSystem:
    """Tests for start_system (lines 49-82)"""

    @pytest.mark.asyncio
    async def test_start_system_success(self):
        """Lines 49-74: successful startup"""
        mod_info = _make_module_info()
        discovery = AsyncMock(return_value=["mod"])
        list_modules = MagicMock(return_value=[mod_info])
        lifecycle = MagicMock()
        lifecycle.load_module = AsyncMock(return_value=True)
        lifecycle.start_module = AsyncMock(return_value=True)

        mgr = SystemLifecycleManager(
            modules={}, module_lifecycle=lifecycle,
            discovery_func=discovery, list_modules_func=list_modules
        )

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
        lifecycle = MagicMock()
        lifecycle.load_module = AsyncMock(return_value=True)
        lifecycle.start_module = AsyncMock(return_value=True)

        mgr = SystemLifecycleManager(
            modules={}, module_lifecycle=lifecycle,
            discovery_func=discovery, list_modules_func=list_modules
        )

        result = await mgr.start_system()
        assert result is True
        lifecycle.load_module.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_start_system_load_fails(self):
        """Lines 61-62: module load returns False"""
        mod_info = _make_module_info()
        discovery = AsyncMock(return_value=["mod"])
        list_modules = MagicMock(return_value=[mod_info])
        lifecycle = MagicMock()
        lifecycle.load_module = AsyncMock(return_value=False)
        lifecycle.start_module = AsyncMock(return_value=True)

        mgr = SystemLifecycleManager(
            modules={}, module_lifecycle=lifecycle,
            discovery_func=discovery, list_modules_func=list_modules
        )

        result = await mgr.start_system()
        assert result is True
        lifecycle.start_module.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_start_system_exception(self):
        """Lines 76-82: exception during startup"""
        discovery = AsyncMock(side_effect=RuntimeError("discovery fail"))
        list_modules = MagicMock(return_value=[])

        mgr = SystemLifecycleManager(
            modules={}, module_lifecycle=MagicMock(),
            discovery_func=discovery, list_modules_func=list_modules
        )

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
        lifecycle = MagicMock()
        lifecycle.stop_module = AsyncMock()
        list_modules = MagicMock(return_value=[mod_info])

        mgr = SystemLifecycleManager(
            modules={}, module_lifecycle=lifecycle,
            discovery_func=AsyncMock(), list_modules_func=list_modules
        )
        mgr._running = True

        await mgr.shutdown_system()
        assert mgr.is_running() is False
        lifecycle.stop_module.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_shutdown_no_running_modules(self):
        """Lines 86-100: no running modules"""
        lifecycle = MagicMock()
        lifecycle.stop_module = AsyncMock()
        list_modules = MagicMock(return_value=[])

        mgr = SystemLifecycleManager(
            modules={}, module_lifecycle=lifecycle,
            discovery_func=AsyncMock(), list_modules_func=list_modules
        )
        mgr._running = True

        await mgr.shutdown_system()
        assert mgr.is_running() is False
        lifecycle.stop_module.assert_not_awaited()


class TestIsRunningAndGetLock:
    """Tests for is_running and _get_lock (lines 104, 108)"""

    def test_is_running_default_false(self):
        """Line 104"""
        mgr = SystemLifecycleManager(
            modules={}, module_lifecycle=MagicMock(),
            discovery_func=MagicMock(), list_modules_func=MagicMock()
        )
        assert mgr.is_running() is False

    def test_get_lock_returns_none(self):
        """Line 108"""
        mgr = SystemLifecycleManager(
            modules={}, module_lifecycle=MagicMock(),
            discovery_func=MagicMock(), list_modules_func=MagicMock()
        )
        assert mgr._get_lock() is None
