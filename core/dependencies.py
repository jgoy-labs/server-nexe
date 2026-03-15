"""
────────────────────────────────────
Server Nexe
Version: 0.8
Author: Jordi Goy 
Location: core/dependencies.py
Description: Shared dependencies per dependency injection. Exposa limiters (global, by_key,

www.jgoy.net · https://server-nexe.org
────────────────────────────────────
"""

from slowapi import Limiter
from slowapi.util import get_remote_address

try:
  from plugins.security.core.rate_limiting import (
    limiter_global,
    limiter_by_key,
    limiter_composite,
    limiter_by_endpoint,
    rate_limit_tracker,
    start_rate_limit_cleanup_task,
  )
  ADVANCED_RATE_LIMITING = True
except ImportError:
  limiter_global = Limiter(key_func=get_remote_address)
  limiter_by_key = None
  limiter_composite = None
  limiter_by_endpoint = None
  rate_limit_tracker = None
  start_rate_limit_cleanup_task = None
  ADVANCED_RATE_LIMITING = False

limiter = limiter_global

__all__ = [
  'limiter',
  'limiter_global',
  'limiter_by_key',
  'limiter_composite',
  'limiter_by_endpoint',
  'rate_limit_tracker',
  'start_rate_limit_cleanup_task',
  'ADVANCED_RATE_LIMITING',
]