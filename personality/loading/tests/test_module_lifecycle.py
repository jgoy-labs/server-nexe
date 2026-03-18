"""
Tests for personality/loading/module_lifecycle.py
Covers uncovered lines: 38-65, 75-100
"""
import warnings
import pytest
from unittest.mock import MagicMock, AsyncMock

from personality.loading.module_lifecycle import ModuleLifecycle


class TestInitializeModule:
    """Tests for initialize_module (lines 38-65)"""

    @pytest.mark.asyncio
    async def test_calls_sync_init_method(self):
        """Lines 38-48: finds and calls sync init method"""
        lc = ModuleLifecycle()
        instance = MagicMock()
        instance.init = MagicMock()
        await lc.initialize_module(instance, "test_mod")
        instance.init.assert_called_once()

    @pytest.mark.asyncio
    async def test_calls_async_init_method(self):
        """Lines 45-46: finds and calls async init method"""
        lc = ModuleLifecycle()

        class FakeModule:
            def __init__(self):
                self.called = False
            async def init(self):
                self.called = True

        instance = FakeModule()
        await lc.initialize_module(instance, "test_mod")
        assert instance.called is True

    @pytest.mark.asyncio
    async def test_stops_after_first_successful_init(self):
        """Line 54: break after first successful init"""
        lc = ModuleLifecycle()
        instance = MagicMock()
        instance.init = MagicMock()
        instance.initialize = MagicMock()
        await lc.initialize_module(instance, "test_mod")
        instance.init.assert_called_once()
        instance.initialize.assert_not_called()

    @pytest.mark.asyncio
    async def test_init_error_warns_and_continues(self):
        """Lines 56-65: init raises, warns, continues to next method"""
        lc = ModuleLifecycle()
        instance = MagicMock()
        instance.init = MagicMock(side_effect=RuntimeError("init fail"))
        instance.initialize = MagicMock()
        with warnings.catch_warnings(record=True) as w:
            warnings.simplefilter("always")
            await lc.initialize_module(instance, "test_mod")
        assert len(w) == 1
        instance.initialize.assert_called_once()

    @pytest.mark.asyncio
    async def test_no_init_methods_does_nothing(self):
        """No init methods present"""
        lc = ModuleLifecycle()
        instance = MagicMock(spec=[])  # No methods
        await lc.initialize_module(instance, "test_mod")

    @pytest.mark.asyncio
    async def test_non_callable_init_skipped(self):
        """Line 43: hasattr but not callable"""
        lc = ModuleLifecycle()
        instance = MagicMock()
        instance.init = "not_callable"
        instance.initialize = MagicMock()
        await lc.initialize_module(instance, "test_mod")
        instance.initialize.assert_called_once()


class TestCleanupModule:
    """Tests for cleanup_module (lines 75-100)"""

    @pytest.mark.asyncio
    async def test_calls_sync_cleanup(self):
        """Lines 75-85: finds and calls sync cleanup"""
        lc = ModuleLifecycle()
        instance = MagicMock()
        instance.cleanup = MagicMock()
        await lc.cleanup_module(instance, "test_mod")
        instance.cleanup.assert_called_once()

    @pytest.mark.asyncio
    async def test_calls_async_cleanup(self):
        """Lines 82-83: async cleanup method"""
        lc = ModuleLifecycle()

        class FakeModule:
            def __init__(self):
                self.called = False
            async def cleanup(self):
                self.called = True

        instance = FakeModule()
        await lc.cleanup_module(instance, "test_mod")
        assert instance.called is True

    @pytest.mark.asyncio
    async def test_cleanup_error_warns_and_continues(self):
        """Lines 93-101: cleanup raises, warns, continues"""
        lc = ModuleLifecycle()
        instance = MagicMock()
        instance.cleanup = MagicMock(side_effect=RuntimeError("cleanup fail"))
        instance.shutdown = MagicMock()
        with warnings.catch_warnings(record=True) as w:
            warnings.simplefilter("always")
            await lc.cleanup_module(instance, "test_mod")
        assert len(w) == 1
        instance.shutdown.assert_called_once()

    @pytest.mark.asyncio
    async def test_stops_after_first_successful_cleanup(self):
        """Line 91: break after first successful cleanup"""
        lc = ModuleLifecycle()
        instance = MagicMock()
        instance.cleanup = MagicMock()
        instance.shutdown = MagicMock()
        await lc.cleanup_module(instance, "test_mod")
        instance.cleanup.assert_called_once()
        instance.shutdown.assert_not_called()
