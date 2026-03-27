"""
────────────────────────────────────
Server Nexe
Version: 0.8
Author: Jordi Goy 
Location: plugins/security/core/rate_limiting.py
Description: Advanced rate limiting for bare metal. Manages limits per IP and API key.

www.jgoy.net · https://server-nexe.org
────────────────────────────────────
"""

from fastapi import Request
from slowapi import Limiter
from slowapi.util import get_remote_address
from typing import Callable
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

  def __init__(self):
    self._counters = defaultdict(lambda: {"count": 0, "reset": None, "limit": 0})
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

async def add_rate_limit_headers(
  request: Request,
  call_next,
  identifier_func: Callable[[Request], str] = get_remote_address,
  limit: int = 100,
  window_seconds: int = 60
):
  """
  Middleware to add X-RateLimit-* headers to responses

  Args:
    request: FastAPI Request
    call_next: Next middleware in chain
    identifier_func: Function to get rate limit identifier
    limit: Max requests per window
    window_seconds: Time window in seconds

  Returns:
    Response with rate limit headers
  """
  identifier = identifier_func(request)

  state = await rate_limit_tracker.record_request(identifier, limit, window_seconds)

  response = await call_next(request)

  response.headers["X-RateLimit-Limit"] = str(state["limit"])
  response.headers["X-RateLimit-Remaining"] = str(state["remaining"])
  response.headers["X-RateLimit-Reset"] = str(state["reset"])
  response.headers["X-RateLimit-Used"] = str(state["used"])

  return response

def rate_limit_public(limit: str = None):
  """
  Rate limit for public endpoints (no auth)

  Usage:
    @router.get("/public")
    @rate_limit_public("30/minute")
    async def public_endpoint():
      return {"status": "ok"}
  """
  return limiter_global.limit(limit or DEFAULT_RATE_LIMITS["public"])

def rate_limit_authenticated(limit: str = None):
  """
  Rate limit for authenticated endpoints

  Higher limits than public endpoints.

  Usage:
    @router.post("/api/data")
    @rate_limit_authenticated("300/minute")
    async def authenticated_endpoint(api_key: str = Depends(require_api_key)):
      return {"data": "sensitive"}
  """
  return limiter_by_key.limit(limit or DEFAULT_RATE_LIMITS["authenticated"])

def rate_limit_admin(limit: str = None):
  """
  Rate limit for admin operations

  Usage:
    @router.post("/admin/config")
    @rate_limit_admin("100/minute")
    async def admin_endpoint(api_key: str = Depends(require_api_key)):
      return {"status": "updated"}
  """
  return limiter_composite.limit(limit or DEFAULT_RATE_LIMITS["admin"])

def rate_limit_health(limit: str = None):
  """
  Rate limit for health check endpoints

  Very high limits to allow monitoring systems to check frequently.

  Usage:
    @router.get("/health")
    @rate_limit_health("1000/minute")
    async def health_check():
      return {"status": "healthy"}
  """
  return limiter_global.limit(limit or DEFAULT_RATE_LIMITS["health"])

def get_rate_limit_stats() -> dict:
  """
  Get current rate limit statistics

  Useful for monitoring and debugging.

  Returns:
    Dict with stats about current rate limit state
  """
  return {
    "active_identifiers": len(rate_limit_tracker._counters),
    "trackers": {
      identifier: {
        "count": data["count"],
        "limit": data["limit"],
        "reset": data["reset"].isoformat() if data["reset"] else None
      }
      for identifier, data in rate_limit_tracker._counters.items()
    }
  }

async def start_rate_limit_cleanup_task():
  """
  Background task to cleanup expired rate limit counters

  Should be started when application starts.
  Runs every hour to prevent memory buildup.
  """
  while True:
    await asyncio.sleep(3600)
    await rate_limit_tracker.cleanup_expired()