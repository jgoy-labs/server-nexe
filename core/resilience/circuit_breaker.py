"""
────────────────────────────────────
Server Nexe
Version: 0.8
Author: Jordi Goy 
Location: core/resilience/circuit_breaker.py
Description: No description available.

www.jgoy.net
────────────────────────────────────
"""

from enum import Enum
from dataclasses import dataclass, field
from datetime import datetime
from typing import Callable, Optional, TypeVar
from contextlib import asynccontextmanager
import asyncio
import logging
from functools import wraps
from personality.i18n.resolve import t_modular

T = TypeVar("T")

from tenacity import (
  retry,
  stop_after_attempt,
  wait_exponential,
  retry_if_exception_type,
  before_sleep_log,
)

logger = logging.getLogger(__name__)

def _t(key: str, fallback: str, **kwargs) -> str:
  return t_modular(f"core.circuit_breaker.{key}", fallback, **kwargs)

class CircuitState(Enum):
  """Circuit breaker states."""
  CLOSED = "closed"
  OPEN = "open"
  HALF_OPEN = "half_open"

@dataclass
class CircuitBreakerConfig:
  """Circuit breaker configuration."""
  failure_threshold: int = 5
  success_threshold: int = 2
  timeout_seconds: int = 30

  max_retries: int = 3
  min_wait_seconds: float = 1.0
  max_wait_seconds: float = 10.0

@dataclass
class CircuitBreakerState:
  """Current circuit breaker state."""
  state: CircuitState = CircuitState.CLOSED
  failure_count: int = 0
  success_count: int = 0
  last_failure_time: Optional[datetime] = None
  last_state_change: datetime = field(default_factory=datetime.now)

class CircuitBreaker:
  """
  Circuit breaker to protect external services.

  Usage:
    cb = CircuitBreaker("ollama", config)

    @cb.protect
    async def call_ollama(prompt: str):
      return await ollama_client.generate(prompt)
  """

  def __init__(self, name: str, config: Optional[CircuitBreakerConfig] = None):
    self.name = name
    self.config = config or CircuitBreakerConfig()
    self._state = CircuitBreakerState()
    self.__lock: Optional[asyncio.Lock] = None

  @property
  def _lock(self) -> asyncio.Lock:
    """Lazy initialization of the lock to avoid event loop issues."""
    if self.__lock is None:
      self.__lock = asyncio.Lock()
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
    """Check if timeout has elapsed to transition to HALF_OPEN."""
    if self._state.last_failure_time is None:
      return False

    elapsed = datetime.now() - self._state.last_failure_time
    return elapsed.total_seconds() >= self.config.timeout_seconds

  async def _record_success(self):
    """Record a success."""
    async with self._lock:
      self._state.success_count += 1
      self._state.failure_count = 0

      if self._state.state == CircuitState.HALF_OPEN:
        if self._state.success_count >= self.config.success_threshold:
          self._transition_to(CircuitState.CLOSED)
          logger.info(
            _t(
              "closed_recovered",
              "CircuitBreaker [{name}]: CLOSED (recovered)",
              name=self.name,
            )
          )

  async def _record_failure(self, error: Exception):
    """Record a failure."""
    async with self._lock:
      self._state.failure_count += 1
      self._state.success_count = 0
      self._state.last_failure_time = datetime.now()

      if self._state.state == CircuitState.CLOSED:
        if self._state.failure_count >= self.config.failure_threshold:
          self._transition_to(CircuitState.OPEN)
          logger.warning(
            _t(
              "open_after_failures",
              "CircuitBreaker [{name}]: OPEN after {count} failures. Last error: {error}",
              name=self.name,
              count=self._state.failure_count,
              error=error,
            )
          )
      elif self._state.state == CircuitState.HALF_OPEN:
        self._transition_to(CircuitState.OPEN)
        logger.warning(
          _t(
            "half_open_failed",
            "CircuitBreaker [{name}]: OPEN (half-open failed)",
            name=self.name,
          )
        )

  def _transition_to(self, new_state: CircuitState):
    """Transition to a new state."""
    self._state.state = new_state
    self._state.last_state_change = datetime.now()
    self._state.success_count = 0
    self._state.failure_count = 0

  async def _can_execute(self) -> bool:
    """Determine whether execution is allowed."""
    async with self._lock:
      if self._state.state == CircuitState.CLOSED:
        return True

      if self._state.state == CircuitState.OPEN:
        if await self._check_timeout():
          self._transition_to(CircuitState.HALF_OPEN)
          logger.info(
            _t(
              "half_open_testing",
              "CircuitBreaker [{name}]: HALF_OPEN (testing)",
              name=self.name,
            )
          )
          return True
        return False

      return True

  def protect(self, func: Callable) -> Callable:
    """
    Decorator to protect functions with the circuit breaker.

    Usage:
      @circuit_breaker.protect
      async def my_function():
        ...
    """
    @wraps(func)
    async def wrapper(*args, **kwargs):
      if not await self._can_execute():
        raise CircuitOpenError(
          _t(
            "open_error",
            "Circuit [{name}] is OPEN. Will retry in {timeout}s",
            name=self.name,
            timeout=self.config.timeout_seconds,
          )
        )

      try:
        @retry(
          stop=stop_after_attempt(self.config.max_retries),
          wait=wait_exponential(
            multiplier=1,
            min=self.config.min_wait_seconds,
            max=self.config.max_wait_seconds
          ),
          retry=retry_if_exception_type((ConnectionError, TimeoutError)),
          before_sleep=before_sleep_log(logger, logging.WARNING),
        )
        async def _with_retry():
          return await func(*args, **kwargs)

        result = await _with_retry()
        await self._record_success()
        return result

      except Exception as e:
        await self._record_failure(e)
        raise

    return wrapper

  def get_status(self) -> dict:
    """Return current status for monitoring."""
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
        _t(
          "open_error",
          "Circuit [{name}] is OPEN. Will retry in {timeout}s",
          name=self.name,
          timeout=self.config.timeout_seconds,
        )
      )

    try:
      yield
      await self._record_success()
    except (ConnectionError, TimeoutError, Exception) as e:
      await self._record_failure(e)
      raise

  async def check_circuit(self) -> bool:
    """
    Public method to check whether the circuit allows execution.
    Alternative to guard_streaming when a context manager cannot be used.

    Returns:
      True if execution is allowed, False if the circuit is open
    """
    return await self._can_execute()

  async def record_success(self):
    """Public method to record success (for async generators)."""
    await self._record_success()

  async def record_failure(self, error: Exception):
    """Public method to record failure (for async generators)."""
    await self._record_failure(error)

class CircuitOpenError(Exception):
  """Exception raised when the circuit is open."""
  pass

ollama_breaker = CircuitBreaker(
  "ollama",
  CircuitBreakerConfig(
    failure_threshold=3,
    success_threshold=2,
    timeout_seconds=60,
    max_retries=2,
  )
)

qdrant_breaker = CircuitBreaker(
  "qdrant",
  CircuitBreakerConfig(
    failure_threshold=5,
    success_threshold=2,
    timeout_seconds=30,
    max_retries=3,
  )
)

http_breaker = CircuitBreaker(
  "http_external",
  CircuitBreakerConfig(
    failure_threshold=10,
    success_threshold=3,
    timeout_seconds=120,
    max_retries=3,
  )
)
