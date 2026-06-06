"""
────────────────────────────────────
Server Nexe
Author: Jordi Goy 
Location: plugins/security/core/rate_limiting.py
Description: Advanced rate limiting for bare metal. Manages limits per IP and API key.

www.jgoy.net · https://server-nexe.org
────────────────────────────────────
"""

from fastapi import Request
from slowapi import Limiter
from slowapi.util import get_remote_address
from typing import Any, DefaultDict, Dict
from collections import defaultdict
from datetime import datetime, timedelta, timezone
import asyncio
import os

DEFAULT_RATE_LIMITS = {
  "global": os.getenv("NEXE_RATE_LIMIT_GLOBAL", "100/minute"),

  "public": os.getenv("NEXE_RATE_LIMIT_PUBLIC", "30/minute"),

  "authenticated": os.getenv("NEXE_RATE_LIMIT_AUTHENTICATED", "300/minute"),

  "admin": os.getenv("NEXE_RATE_LIMIT_ADMIN", "100/minute"),

  "health": os.getenv("NEXE_RATE_LIMIT_HEALTH", "1000/minute"),
}

def get_api_key_identifier(request: Request) -> str:
  """
  Get rate limit key based on API key

  Used for rate limiting per API key instead of per IP.
  Useful when multiple clients share same IP (Nexe, proxy).

  Args:
    request: FastAPI Request object

  Returns:
    API key or IP address if no key provided
  """
  api_key = request.headers.get("x-api-key", "")

  if api_key:
    import hashlib
    key_hash = hashlib.sha256(api_key.encode()).hexdigest()[:16]
    return f"apikey:{key_hash}"

  return f"ip:{get_remote_address(request)}"

def get_composite_identifier(request: Request) -> str:
  """
  Get composite identifier (IP + API key)

  Most restrictive: limits per IP AND per API key combination.
  Prevents both IP-based and key-based abuse.

  Args:
    request: FastAPI Request object

  Returns:
    Composite identifier
  """
  ip = get_remote_address(request)
  api_key = request.headers.get("x-api-key", "")

  if api_key:
    import hashlib
    key_hash = hashlib.sha256(api_key.encode()).hexdigest()[:16]
    return f"composite:{ip}:{key_hash}"

  return f"composite:{ip}:nokey"

def get_endpoint_identifier(request: Request) -> str:
  """
  Get identifier including endpoint path

  Allows different limits for different endpoints.

  Args:
    request: FastAPI Request object

  Returns:
    Endpoint-specific identifier
  """
  ip = get_remote_address(request)
  path = request.url.path

  path = path.rstrip("/")

  return f"endpoint:{ip}:{path}"

limiter_global = Limiter(
  key_func=get_remote_address,
  default_limits=[DEFAULT_RATE_LIMITS["global"]],
  storage_uri="memory://",
  strategy="fixed-window"
)

limiter_by_key = Limiter(
  key_func=get_api_key_identifier,
  storage_uri="memory://",
  strategy="fixed-window"
)

limiter_composite = Limiter(
  key_func=get_composite_identifier,
  storage_uri="memory://",
  strategy="fixed-window"
)

limiter_by_endpoint = Limiter(
  key_func=get_endpoint_identifier,
  storage_uri="memory://",
  strategy="fixed-window"
)

class RateLimitTracker:
  """
  Track rate limit usage to populate X-RateLimit-* headers

  Stores request counts and reset times for each identifier.

  SECURITY: Implements MAX_TRACKED_IDENTIFIERS to prevent memory exhaustion
  from tracking unlimited unique identifiers.
  """

  # Maximum number of tracked identifiers to prevent memory exhaustion
  MAX_TRACKED_IDENTIFIERS = 10000

  def __init__(self) -> None:
    # Per-identifier counter state. `reset` is Optional[datetime]; `count`/`limit` are int.
    # Heterogeneous values → annotate as Dict[str, Any] to silence reportOperatorIssue
    # without losing runtime safety (initial values + assignments below are correct).
    self._counters: DefaultDict[str, Dict[str, Any]] = defaultdict(
      lambda: {"count": 0, "reset": None, "limit": 0}
    )
    self._lock = asyncio.Lock()

  async def record_request(
    self,
    identifier: str,
    limit: int,
    window_seconds: int
  ) -> dict:
    """
    Record a request and return current rate limit state

    Args:
      identifier: Unique identifier (IP, API key, etc.)
      limit: Max requests allowed in window
      window_seconds: Time window in seconds

    Returns:
      Dict with 'remaining', 'limit', 'reset' keys
    """
    async with self._lock:
      now = datetime.now(timezone.utc)

      # SECURITY: Check memory limit before adding new identifiers
      if identifier not in self._counters:
        if len(self._counters) >= self.MAX_TRACKED_IDENTIFIERS:
          # Evict oldest expired entries first
          expired = [
            key for key, value in self._counters.items()
            if value["reset"] and now >= value["reset"]
          ]
          for key in expired[:100]:  # Batch eviction
            del self._counters[key]

          # If still at limit, evict oldest entries
          if len(self._counters) >= self.MAX_TRACKED_IDENTIFIERS:
            import logging
            logging.getLogger(__name__).warning(
              "Rate limit tracker at capacity (%d). Evicting oldest entries.",
              self.MAX_TRACKED_IDENTIFIERS
            )
            # Sort by reset time and remove oldest 10%
            sorted_keys = sorted(
              self._counters.keys(),
              key=lambda k: self._counters[k]["reset"] or now
            )
            for key in sorted_keys[:self.MAX_TRACKED_IDENTIFIERS // 10]:
              del self._counters[key]

      counter = self._counters[identifier]

      if counter["reset"] is None or now >= counter["reset"]:
        counter["count"] = 0
        counter["reset"] = now + timedelta(seconds=window_seconds)
        counter["limit"] = limit

      counter["count"] += 1

      remaining = max(0, limit - counter["count"])

      reset_timestamp = int(counter["reset"].timestamp())

      return {
        "remaining": remaining,
        "limit": limit,
        "reset": reset_timestamp,
        "used": counter["count"]
      }

  async def cleanup_expired(self):
    """
    Clean up expired counters (periodic task)

    Should be called periodically to prevent memory buildup.
    """
    async with self._lock:
      now = datetime.now(timezone.utc)
      expired = [
        key for key, value in self._counters.items()
        if value["reset"] and now >= value["reset"] + timedelta(hours=1)
      ]
      for key in expired:
        del self._counters[key]

rate_limit_tracker = RateLimitTracker()

async def start_rate_limit_cleanup_task():
  """
  Background task to cleanup expired rate limit counters

  Should be started when application starts.
  Runs every hour to prevent memory buildup.
  """
  while True:
    await asyncio.sleep(3600)
    await rate_limit_tracker.cleanup_expired()