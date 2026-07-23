"""
────────────────────────────────────
Server Nexe
Author: Jordi Goy 
Location: core/resilience/tests/test_circuit_breaker.py
Description: No description available.

www.jgoy.net · https://server-nexe.org
────────────────────────────────────
"""

import pytest
import asyncio

from core.resilience.circuit_breaker import (
  CircuitBreaker,
  CircuitBreakerConfig,
  CircuitState,
  CircuitOpenError,
  ollama_breaker,
)

class TestCircuitBreakerBasic:
  """Basic tests for the Circuit Breaker"""

  @pytest.fixture
  def breaker(self):
    """Circuit breaker with test configuration (fast)"""
    return CircuitBreaker(
      "test",
      CircuitBreakerConfig(
        failure_threshold=3,
        success_threshold=2,
        timeout_seconds=1,
        max_retries=1,
        min_wait_seconds=0.1,
        max_wait_seconds=0.5,
      )
    )

  def test_starts_closed(self, breaker):
    """The circuit starts closed"""
    assert breaker.state == CircuitState.CLOSED
    assert breaker.is_closed
    assert not breaker.is_open

  def test_initial_status(self, breaker):
    """Initial state returns correct values"""
    status = breaker.get_status()

    assert status["name"] == "test"
    assert status["state"] == "closed"
    assert status["failure_count"] == 0
    assert status["success_count"] == 0
    assert status["last_failure"] is None
    assert "last_state_change" in status

  @pytest.mark.asyncio
  async def test_can_execute_when_closed(self, breaker):
    """Allows execution when closed"""
    can_execute = await breaker._can_execute()
    assert can_execute is True

class TestCircuitBreakerTransitions:
  """Tests for state transitions"""

  @pytest.fixture
  def breaker(self):
    """Circuit breaker with test configuration"""
    return CircuitBreaker(
      "test_transitions",
      CircuitBreakerConfig(
        failure_threshold=3,
        success_threshold=2,
        timeout_seconds=1,
        max_retries=1,
      )
    )

  @pytest.mark.asyncio
  async def test_opens_after_failures(self, breaker):
    """The circuit opens after N failures"""
    for i in range(3):
      await breaker._record_failure(Exception(f"failure {i}"))

    assert breaker.state == CircuitState.OPEN
    assert breaker.is_open

  @pytest.mark.asyncio
  async def test_stays_closed_under_threshold(self, breaker):
    """The circuit stays closed if the threshold is not reached"""
    await breaker._record_failure(Exception("failure 1"))
    await breaker._record_failure(Exception("failure 2"))

    assert breaker.state == CircuitState.CLOSED
    assert breaker.is_closed

  @pytest.mark.asyncio
  async def test_rejects_when_open(self, breaker):
    """Rejects requests when open"""
    for _ in range(3):
      await breaker._record_failure(Exception("test"))

    assert breaker.is_open

    can_execute = await breaker._can_execute()
    assert can_execute is False

  @pytest.mark.asyncio
  async def test_half_open_after_timeout(self, breaker):
    """Transitions to half-open after the timeout"""
    for _ in range(3):
      await breaker._record_failure(Exception("test"))

    assert breaker.is_open

    await asyncio.sleep(1.1)

    can_execute = await breaker._can_execute()
    assert can_execute is True
    assert breaker.state == CircuitState.HALF_OPEN

  @pytest.mark.asyncio
  async def test_closes_after_successes_in_half_open(self, breaker):
    """Closes after N successes in half-open"""
    breaker._transition_to(CircuitState.HALF_OPEN)
    assert breaker.state == CircuitState.HALF_OPEN

    await breaker._record_success()
    await breaker._record_success()

    assert breaker.state == CircuitState.CLOSED
    assert breaker.is_closed

  @pytest.mark.asyncio
  async def test_reopens_on_failure_in_half_open(self, breaker):
    """Reopens if it fails in half-open"""
    breaker._transition_to(CircuitState.HALF_OPEN)
    assert breaker.state == CircuitState.HALF_OPEN

    await breaker._record_failure(Exception("half-open failure"))

    assert breaker.state == CircuitState.OPEN
    assert breaker.is_open

class TestPreConfiguredBreakers:
  """Tests for pre-configured circuit breakers"""

  def test_ollama_breaker_exists(self):
    """Ollama breaker is configured"""
    assert ollama_breaker is not None
    assert ollama_breaker.name == "ollama"
    assert ollama_breaker.config.failure_threshold == 5
    assert ollama_breaker.config.timeout_seconds == 60

  def test_ollama_is_the_only_global_breaker(self):
    """WS7-01: qdrant/http breakers were decorative (never wired) and are gone."""
    import core.resilience as resilience
    assert not hasattr(resilience, "qdrant_breaker")
    assert not hasattr(resilience, "http_breaker")

  def test_all_breakers_start_closed(self):
    """All breakers start closed"""
    assert ollama_breaker.is_closed

class TestCircuitBreakerConcurrency:
  """Concurrency tests for the Circuit Breaker"""

  @pytest.fixture
  def breaker(self):
    """Circuit breaker for concurrency tests"""
    return CircuitBreaker(
      "test_concurrency",
      CircuitBreakerConfig(
        failure_threshold=5,
        success_threshold=2,
        timeout_seconds=1,
      )
    )

  @pytest.mark.asyncio
  async def test_concurrent_failures(self, breaker):
    """Handles concurrent failures correctly"""
    async def record_failure():
      await breaker._record_failure(Exception("concurrent"))

    await asyncio.gather(*[record_failure() for _ in range(10)])

    assert breaker.is_open

  @pytest.mark.asyncio
  async def test_concurrent_successes(self, breaker):
    """Handles concurrent successes correctly"""
    breaker._transition_to(CircuitState.HALF_OPEN)

    async def record_success():
      await breaker._record_success()

    await asyncio.gather(*[record_success() for _ in range(5)])

    assert breaker.is_closed