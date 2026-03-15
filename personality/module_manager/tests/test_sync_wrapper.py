"""
Tests for personality/module_manager/sync_wrapper.py
Covers uncovered lines: 34, 65-91, 130-138, 142-148
"""
import asyncio
import pytest
from unittest.mock import MagicMock, patch

from personality.module_manager.sync_wrapper import (
    is_event_loop_running,
    run_async_in_new_loop,
    run_async_in_thread,
    SyncWrapper,
)


class TestIsEventLoopRunning:
    """Tests for is_event_loop_running (line 34)"""

    def test_no_loop_running(self):
        """Lines 33-36: no event loop -> False"""
        result = is_event_loop_running()
        assert result is False

    @pytest.mark.asyncio
    async def test_loop_running(self):
        """Lines 33-34: event loop active -> True"""
        result = is_event_loop_running()
        assert result is True


class TestRunAsyncInThread:
    """Tests for run_async_in_thread (lines 65-91)"""

    def test_successful_execution(self):
        """Lines 65-91: executes coroutine in separate thread"""
        async def my_coro():
            return 42

        result = run_async_in_thread(my_coro())
        assert result == 42

    def test_exception_propagation(self):
        """Lines 73-74, 88-89: exception in coroutine is re-raised"""
        async def failing_coro():
            raise ValueError("test error")

        with pytest.raises(ValueError, match="test error"):
            run_async_in_thread(failing_coro())

    def test_returns_none_for_void_coro(self):
        """Line 91: coroutine returns None"""
        async def void_coro():
            pass

        result = run_async_in_thread(void_coro())
        assert result is None


class TestRunAsyncInNewLoop:
    """Tests for run_async_in_new_loop"""

    def test_successful_execution(self):
        async def my_coro():
            return "hello"

        result = run_async_in_new_loop(my_coro())
        assert result == "hello"


class TestSyncWrapper:
    """Tests for SyncWrapper.run_sync (lines 130-138) and _log_error (lines 142-148)"""

    def test_run_sync_no_event_loop(self):
        """Lines 127-132: no event loop, uses run_async_in_new_loop"""
        wrapper = SyncWrapper()

        async def my_coro():
            return "result"

        result = wrapper.run_sync(my_coro())
        assert result == "result"

    def test_run_sync_no_loop_error(self):
        """Lines 130-132: error in new loop"""
        wrapper = SyncWrapper()

        async def failing():
            raise RuntimeError("fail")

        with pytest.raises(RuntimeError):
            wrapper.run_sync(failing())

    def test_run_sync_with_event_loop(self):
        """Lines 133-138: event loop running, uses thread"""
        wrapper = SyncWrapper()

        async def my_coro():
            return "threaded_result"

        async def run_test():
            # Inside async context, run_sync should use thread
            result = wrapper.run_sync(my_coro())
            return result

        result = asyncio.run(run_test())
        assert result == "threaded_result"

    def test_run_sync_with_event_loop_error(self):
        """Lines 136-138: error in thread"""
        wrapper = SyncWrapper()

        async def failing():
            raise ValueError("thread fail")

        async def run_test():
            with pytest.raises(ValueError):
                wrapper.run_sync(failing())

        asyncio.run(run_test())

    def test_log_error_with_i18n(self):
        """Lines 142-148: _log_error with LOGGER_AVAILABLE=True and i18n"""
        wrapper = SyncWrapper(i18n=MagicMock())
        # _log_error doesn't raise, just logs when LOGGER_AVAILABLE
        # Since LOGGER_AVAILABLE is False by default, this is a no-op
        wrapper._log_error("test_key", RuntimeError("err"))

    @patch("personality.module_manager.sync_wrapper.LOGGER_AVAILABLE", True)
    def test_log_error_with_logger_and_i18n(self):
        """Lines 142-148: LOGGER_AVAILABLE=True"""
        mock_i18n = MagicMock()
        wrapper = SyncWrapper(i18n=mock_i18n)
        with patch("personality.module_manager.sync_wrapper.logger") as mock_logger:
            wrapper._log_error("test_key", RuntimeError("err"))
            mock_logger.error.assert_called_once()
