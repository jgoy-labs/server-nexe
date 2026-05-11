"""
Tests for uncovered lines in core/resilience/circuit_breaker.py.
Targets: lines 100, 154, 222-233, 247
"""
import asyncio
import pytest
from core.resilience.circuit_breaker import (
    CircuitBreaker,
    CircuitBreakerConfig,
    CircuitState,
    CircuitOpenError,
)


class TestCheckTimeout:
    """Line 100: _check_timeout returns False when last_failure_time is None."""

    def test_check_timeout_no_failure(self):
        breaker = CircuitBreaker("test", CircuitBreakerConfig(timeout_seconds=1))
        result = asyncio.run(breaker._check_timeout())
        assert result is False


class TestCanExecuteHalfOpen:
    """Line 154: _can_execute returns True when HALF_OPEN."""

    def test_can_execute_in_half_open(self):
        breaker = CircuitBreaker("test", CircuitBreakerConfig())
        breaker._transition_to(CircuitState.HALF_OPEN)
        result = asyncio.run(breaker._can_execute())
        assert result is True


class TestGuardStreaming:
    """Lines 222-233: guard_streaming context manager."""

    def test_guard_streaming_open_raises(self):
        """Lines 222-226: guard_streaming raises when circuit is open."""
        breaker = CircuitBreaker("test", CircuitBreakerConfig(failure_threshold=2))

        async def _test():
            for _ in range(2):
                await breaker._record_failure(Exception("fail"))
            async with breaker.guard_streaming():
                pass

        with pytest.raises(CircuitOpenError):
            asyncio.run(_test())

    def test_guard_streaming_success(self):
        """Lines 228-230: guard_streaming records success."""
        breaker = CircuitBreaker("test", CircuitBreakerConfig())

        async def _test():
            async with breaker.guard_streaming():
                pass

        asyncio.run(_test())
        assert breaker._state.success_count == 1

    def test_guard_streaming_failure(self):
        """Lines 231-233: guard_streaming records failure on exception."""
        breaker = CircuitBreaker("test", CircuitBreakerConfig())

        async def _test():
            async with breaker.guard_streaming():
                raise ConnectionError("lost connection")

        with pytest.raises(ConnectionError):
            asyncio.run(_test())
        assert breaker._state.failure_count == 1


class TestPublicMethods:
    """Line 247: record_success and record_failure public methods."""

    def test_public_record_success(self):
        breaker = CircuitBreaker("test", CircuitBreakerConfig())
        asyncio.run(breaker.record_success())
        assert breaker._state.success_count == 1

    def test_public_record_failure(self):
        breaker = CircuitBreaker("test", CircuitBreakerConfig())
        asyncio.run(breaker.record_failure(Exception("test")))
        assert breaker._state.failure_count == 1

    def test_check_circuit(self):
        breaker = CircuitBreaker("test", CircuitBreakerConfig())
        result = asyncio.run(breaker.check_circuit())
        assert result is True
