"""
────────────────────────────────────
Server Nexe
Author: Jordi Goy 
Location: core/security/rate_limiting.py
Description: Advanced rate limiting for bare metal. Manages limits per IP and API key.

www.jgoy.net · https://server-nexe.org
────────────────────────────────────
"""

from typing import Any, DefaultDict, Dict
from collections import defaultdict
from datetime import datetime, timedelta, timezone
import asyncio

# MC-103 dead-code sweep: the limiter objects (global/by_key/composite/by_endpoint)
# defined here were imported only by core/dependencies.py. The advanced ones were
# already unwired (MC-123/124) and the per-IP `limiter` now lives in core itself,
# so all four are dead and have been removed.
#
# #877 dead-code sweep (2026-08-28): DEFAULT_RATE_LIMITS, the identifier helpers
# (get_api_key_identifier/get_composite_identifier/get_endpoint_identifier),
# rate_limit_tracker and start_rate_limit_cleanup_task all had zero production
# call-sites (only their own tests exercised them) — none of them is wired to
# core/dependencies.py's `limiter` or any endpoint. Removed. RateLimitTracker
# stays: plugins/security/checks/rate_limit_check.py instantiates it as a
# real availability check.

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