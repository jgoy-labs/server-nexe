"""
────────────────────────────────────
Server Nexe
Author: Jordi Goy 
Location: core/resilience/circuit_breaker.py
Description: Circuit Breaker with exponential retry to protect external services (Ollama, Qdrant, HTTP).

www.jgoy.net · https://server-nexe.org
────────────────────────────────────
"""

from enum import Enum
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Optional, TypeVar
from contextlib import asynccontextmanager
import asyncio
import logging

T = TypeVar("T")

logger = logging.getLogger(__name__)

class CircuitState(Enum):
  """Circuit breaker states"""
  CLOSED = "closed"
  OPEN = "open"
  HALF_OPEN = "half_open"

@dataclass
class CircuitBreakerConfig:
  """Circuit breaker configuration"""
  failure_threshold: int = 5
  success_threshold: int = 2
  timeout_seconds: int = 30

  max_retries: int = 3
  min_wait_seconds: float = 1.0
  max_wait_seconds: float = 10.0

@dataclass
class CircuitBreakerState:
  """Current circuit breaker state"""
  state: CircuitState = CircuitState.CLOSED
  failure_count: int = 0
  success_count: int = 0
  last_failure_time: Optional[datetime] = None
  last_state_change: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
  # WS7-03: number of probes admitted while HALF_OPEN and not yet resolved
  # via record_success/record_failure. Bounds the herd to one probe at a time.
  half_open_inflight: int = 0

class CircuitBreaker:
  """
  Circuit Breaker to protect external services

  Usage (manual guard — the pattern the live ollama call-sites use;
  it distinguishes infrastructure errors, which count, from semantic
  HTTP 4xx errors, which must not trip the breaker):

    if not await breaker.check_circuit():
      raise CircuitOpenError(...)
    try:
      result = await call_external_service()
      await breaker.record_success()
    except TRANSPORT_ERRORS as e:
      await breaker.record_failure(e)
      raise
  """

  def __init__(self, name: str, config: Optional[CircuitBreakerConfig] = None):
    self.name = name
    self.config = config or CircuitBreakerConfig()
    self._state = CircuitBreakerState()
    self.__lock: Optional[asyncio.Lock] = None
    self.__lock_loop: Optional[asyncio.AbstractEventLoop] = None

  @property
  def _lock(self) -> asyncio.Lock:
    """Lazy lock initialization to avoid event loop issues."""
    loop = asyncio.get_running_loop()
    if self.__lock is None or self.__lock_loop is not loop:
      self.__lock = asyncio.Lock()
      self.__lock_loop = loop
    return self.__lock

  @property
  def state(self) -> CircuitState:
    return self._state.state

  @property
  def is_closed(self) -> bool:
    return self._state.state == CircuitState.CLOSED

  @property
  def is_open(self) -> bool:
    return self._state.state == CircuitState.OPEN

  async def _check_timeout(self) -> bool:
    """Checks if the timeout has elapsed to transition to HALF_OPEN"""
    if self._state.last_failure_time is None:
      return False

    elapsed = datetime.now(timezone.utc) - self._state.last_failure_time
    return elapsed.total_seconds() >= self.config.timeout_seconds

  async def _record_success(self):
    """Records a success"""
    async with self._lock:
      self._state.success_count += 1
      self._state.failure_count = 0

      if self._state.state == CircuitState.HALF_OPEN:
        # WS7-03: this probe has resolved — free the slot for the next one
        self._state.half_open_inflight = max(0, self._state.half_open_inflight - 1)
        if self._state.success_count >= self.config.success_threshold:
          self._transition_to(CircuitState.CLOSED)
          logger.info(f"CircuitBreaker [{self.name}]: CLOSED (recovered)")

  async def _record_failure(self, error: Exception):
    """Records a failure"""
    async with self._lock:
      self._state.failure_count += 1
      self._state.success_count = 0
      self._state.last_failure_time = datetime.now(timezone.utc)

      if self._state.state == CircuitState.CLOSED:
        if self._state.failure_count >= self.config.failure_threshold:
          self._transition_to(CircuitState.OPEN)
          logger.warning(
            f"CircuitBreaker [{self.name}]: OPEN after {self._state.failure_count} failures. "
            f"Last error: {error}"
          )
      elif self._state.state == CircuitState.HALF_OPEN:
        self._transition_to(CircuitState.OPEN)
        logger.warning(f"CircuitBreaker [{self.name}]: OPEN (half-open failed)")

  def _transition_to(self, new_state: CircuitState):
    """Transitions to a new state"""
    self._state.state = new_state
    self._state.last_state_change = datetime.now(timezone.utc)
    self._state.success_count = 0
    self._state.failure_count = 0
    self._state.half_open_inflight = 0

  async def _can_execute(self) -> bool:
    """Determines whether execution is allowed"""
    async with self._lock:
      if self._state.state == CircuitState.CLOSED:
        return True

      if self._state.state == CircuitState.OPEN:
        if await self._check_timeout():
          self._transition_to(CircuitState.HALF_OPEN)
          self._state.half_open_inflight = 1
          logger.info(f"CircuitBreaker [{self.name}]: HALF_OPEN (testing)")
          return True
        return False

      # HALF_OPEN (WS7-03): admit one probe at a time — a herd of concurrent
      # callers must not hammer a service that is still recovering. The slot
      # frees when the probe resolves via record_success/record_failure; a
      # probe that never resolves (e.g. cancelled task) must not wedge the
      # breaker, so the slot goes stale after timeout_seconds.
      elapsed = (datetime.now(timezone.utc) - self._state.last_state_change).total_seconds()
      if self._state.half_open_inflight == 0 or elapsed >= self.config.timeout_seconds:
        self._state.half_open_inflight = 1
        self._state.last_state_change = datetime.now(timezone.utc)  # re-arm staleness window
        return True
      return False

  def get_status(self) -> dict:
    """Returns current state for monitoring"""
    return {
      "name": self.name,
      "state": self._state.state.value,
      "failure_count": self._state.failure_count,
      "success_count": self._state.success_count,
      "last_failure": self._state.last_failure_time.isoformat() if self._state.last_failure_time else None,
      "last_state_change": self._state.last_state_change.isoformat(),
    }

  @asynccontextmanager
  async def guard_streaming(self):
    """
    Public context manager to protect async generators/streaming.

    Usage:
      async def my_streaming_function():
        async with breaker.guard_streaming():
          async for chunk in stream:
            yield chunk

    Raises:
      CircuitOpenError: If the circuit is open
    """
    if not await self._can_execute():
      raise CircuitOpenError(
        f"Circuit [{self.name}] is OPEN. "
        f"Will retry in {self.config.timeout_seconds}s"
      )

    try:
      yield
      await self._record_success()
    except (ConnectionError, TimeoutError, OSError) as e:
      # MC-020: unlike protect() (which counts every Exception), guard_streaming
      # only trips on transport errors — an app-level error mid-stream should not
      # open the transport circuit. NOTE: this context manager is currently unused
      # in production (all streaming paths use protect()/check_circuit); kept for
      # completeness. Revisit the scope if a real streaming caller adopts it.
      await self._record_failure(e)
      raise

  async def check_circuit(self) -> bool:
    """
    Public method to check whether the circuit allows execution.
    Alternative to guard_streaming for cases where a context manager cannot be used.

    Returns:
      True if execution is allowed, False if the circuit is open
    """
    return await self._can_execute()

  async def record_success(self):
    """Public method to record a success (for async generators)"""
    await self._record_success()

  async def record_failure(self, error: Exception):
    """Public method to record a failure (for async generators)"""
    await self._record_failure(error)

  def reset(self) -> None:
    """Resets the circuit breaker to clean CLOSED state. N03.

    Called from lifespan shutdown to prevent corrupt state
    from one session contaminating the next server restart.
    """
    self._state = CircuitBreakerState()
    logger.debug("CircuitBreaker [%s]: reset to CLOSED", self.name)

class CircuitOpenError(Exception):
  """Exception raised when the circuit is open"""
  pass

# WS7-01: ollama_breaker is the ONLY global breaker — the former
# qdrant_breaker/http_breaker were defined but never wired to any call
# (they always reported CLOSED, which /health/circuits surfaced as fake
# observability). If Qdrant/external-HTTP protection is ever wanted, wire
# a new breaker with the manual-guard pattern the ollama call-sites use.
ollama_breaker = CircuitBreaker(
  "ollama",
  CircuitBreakerConfig(
    # 5 (no 3): a brief Ollama hiccup shouldn't block AI for everyone for 60s.
    failure_threshold=5,
    success_threshold=2,
    timeout_seconds=60,
    max_retries=2,
  )
)


def reset_all_circuit_breakers() -> None:
  """Resets all global circuit breakers to clean CLOSED state. N03.

  Called from lifespan shutdown. Prevents an OPEN breaker from a previous
  session from contaminating the next server restart (corrupt state on restart).
  """
  for _breaker in (ollama_breaker,):
    _breaker.reset()