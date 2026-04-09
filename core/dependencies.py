"""
────────────────────────────────────
Server Nexe
Author: Jordi Goy 
Location: core/dependencies.py
Description: Shared dependencies per dependency injection. Exposa limiters (global, by_key,

www.jgoy.net · https://server-nexe.org
────────────────────────────────────
"""

from fastapi import Request
from slowapi import Limiter
from slowapi.util import get_remote_address


def get_i18n(request: Request):
    """FastAPI Dependency: read i18n manager from app.state.

    Returns None if app.state has no i18n attribute (test/dev fallback).
    Single source of truth — replaces local copies in endpoints and plugins.

    Note: the `request: Request` type hint is REQUIRED for FastAPI to inject
    the Request object. Without it, FastAPI treats `request` as a query param.
    """
    return getattr(request.app.state, "i18n", None)

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
  'get_i18n',
  'limiter',
  'limiter_global',
  'limiter_by_key',
  'limiter_composite',
  'limiter_by_endpoint',
  'rate_limit_tracker',
  'start_rate_limit_cleanup_task',
  'ADVANCED_RATE_LIMITING',
]