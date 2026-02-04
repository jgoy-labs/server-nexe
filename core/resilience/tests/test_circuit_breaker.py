"""
────────────────────────────────────
Server Nexe
Version: 0.8
Author: Jordi Goy 
Location: core/resilience/tests/test_circuit_breaker.py
Description: No description available.

www.jgoy.net
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
  qdrant_breaker,
  http_breaker,
)

class TestCircuitBreakerBasic:
  """Tests bàsics del Circuit Breaker"""

  @pytest.fixture
  def breaker(self):
    """Circuit breaker amb configuració de test (ràpid)"""
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
    """El circuit comença tancat"""
    assert breaker.state == CircuitState.CLOSED
    assert breaker.is_closed
    assert not breaker.is_open

  def test_initial_status(self, breaker):
    """Estat inicial retorna valors correctes"""
    status = breaker.get_status()

    assert status["name"] == "test"
    assert status["state"] == "closed"
    assert status["failure_count"] == 0
    assert status["success_count"] == 0
    assert status["last_failure"] is None
    assert "last_state_change" in status

  @pytest.mark.asyncio
  async def test_can_execute_when_closed(self, breaker):
    """Permet execució quan està tancat"""
    can_execute = await breaker._can_execute()
    assert can_execute is True

class TestCircuitBreakerTransitions:
  """Tests de transicions d'estat"""

  @pytest.fixture
  def breaker(self):
    """Circuit breaker amb configuració de test"""
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
    """El circuit s'obre després de N fallades"""
    for i in range(3):
      await breaker._record_failure(Exception(f"failure {i}"))

    assert breaker.state == CircuitState.OPEN
    assert breaker.is_open

  @pytest.mark.asyncio
  async def test_stays_closed_under_threshold(self, breaker):
    """El circuit es manté tancat si no arriba al threshold"""
    await breaker._record_failure(Exception("failure 1"))
    await breaker._record_failure(Exception("failure 2"))

    assert breaker.state == CircuitState.CLOSED
    assert breaker.is_closed

  @pytest.mark.asyncio
  async def test_rejects_when_open(self, breaker):
    """Rebutja peticions quan està obert"""
    for _ in range(3):
      await breaker._record_failure(Exception("test"))

    assert breaker.is_open

    can_execute = await breaker._can_execute()
    assert can_execute is False

  @pytest.mark.asyncio
  async def test_half_open_after_timeout(self, breaker):
    """Passa a half-open després del timeout"""
    for _ in range(3):
      await breaker._record_failure(Exception("test"))

    assert breaker.is_open

    await asyncio.sleep(1.1)

    can_execute = await breaker._can_execute()
    assert can_execute is True
    assert breaker.state == CircuitState.HALF_OPEN

  @pytest.mark.asyncio
  async def test_closes_after_successes_in_half_open(self, breaker):
    """Es tanca després de N èxits en half-open"""
    breaker._transition_to(CircuitState.HALF_OPEN)
    assert breaker.state == CircuitState.HALF_OPEN

    await breaker._record_success()
    await breaker._record_success()

    assert breaker.state == CircuitState.CLOSED
    assert breaker.is_closed

  @pytest.mark.asyncio
  async def test_reopens_on_failure_in_half_open(self, breaker):
    """Es torna a obrir si falla en half-open"""
    breaker._transition_to(CircuitState.HALF_OPEN)
    assert breaker.state == CircuitState.HALF_OPEN

    await breaker._record_failure(Exception("half-open failure"))

    assert breaker.state == CircuitState.OPEN
    assert breaker.is_open

class TestCircuitBreakerProtectDecorator:
  """Tests del decorador protect"""

  @pytest.fixture
  def breaker(self):
    """Circuit breaker per tests de decorador"""
    return CircuitBreaker(
      "test_protect",
      CircuitBreakerConfig(
        failure_threshold=2,
        success_threshold=1,
        timeout_seconds=1,
        max_retries=1,
        min_wait_seconds=0.01,
        max_wait_seconds=0.1,
      )
    )

  @pytest.mark.asyncio
  async def test_protect_success(self, breaker):
    """Decorador permet èxits"""
    @breaker.protect
    async def successful_func():
      return "success"

    result = await successful_func()
    assert result == "success"

    status = breaker.get_status()
    assert status["success_count"] == 1
    assert status["failure_count"] == 0

  @pytest.mark.asyncio
  async def test_protect_raises_circuit_open_error(self, breaker):
    """Decorador llença CircuitOpenError quan obert"""
    for _ in range(2):
      await breaker._record_failure(Exception("force open"))

    @breaker.protect
    async def any_func():
      return "won't reach"

    with pytest.raises(CircuitOpenError) as exc_info:
      await any_func()

    assert "OPEN" in str(exc_info.value)
    assert breaker.name in str(exc_info.value)

  @pytest.mark.asyncio
  async def test_protect_propagates_exceptions(self, breaker):
    """Decorador propaga excepcions originals"""
    @breaker.protect
    async def failing_func():
      raise ValueError("custom error")

    with pytest.raises(ValueError) as exc_info:
      await failing_func()

    assert "custom error" in str(exc_info.value)

class TestPreConfiguredBreakers:
  """Tests dels circuit breakers pre-configurats"""

  def test_ollama_breaker_exists(self):
    """Ollama breaker està configurat"""
    assert ollama_breaker is not None
    assert ollama_breaker.name == "ollama"
    assert ollama_breaker.config.failure_threshold == 3
    assert ollama_breaker.config.timeout_seconds == 60

  def test_qdrant_breaker_exists(self):
    """Qdrant breaker està configurat"""
    assert qdrant_breaker is not None
    assert qdrant_breaker.name == "qdrant"
    assert qdrant_breaker.config.failure_threshold == 5
    assert qdrant_breaker.config.timeout_seconds == 30

  def test_http_breaker_exists(self):
    """HTTP breaker està configurat"""
    assert http_breaker is not None
    assert http_breaker.name == "http_external"
    assert http_breaker.config.failure_threshold == 10
    assert http_breaker.config.timeout_seconds == 120

  def test_all_breakers_start_closed(self):
    """Tots els breakers comencen tancats"""
    assert ollama_breaker.is_closed
    assert qdrant_breaker.is_closed
    assert http_breaker.is_closed

class TestCircuitBreakerConcurrency:
  """Tests de concurrència del Circuit Breaker"""

  @pytest.fixture
  def breaker(self):
    """Circuit breaker per tests de concurrència"""
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
    """Gestiona fallades concurrents correctament"""
    async def record_failure():
      await breaker._record_failure(Exception("concurrent"))

    await asyncio.gather(*[record_failure() for _ in range(10)])

    assert breaker.is_open

  @pytest.mark.asyncio
  async def test_concurrent_successes(self, breaker):
    """Gestiona èxits concurrents correctament"""
    breaker._transition_to(CircuitState.HALF_OPEN)

    async def record_success():
      await breaker._record_success()

    await asyncio.gather(*[record_success() for _ in range(5)])

    assert breaker.is_closed