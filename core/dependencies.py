"""
────────────────────────────────────
Server Nexe
Author: Jordi Goy 
Location: core/dependencies.py
Description: Shared dependencies for dependency injection. Exposes limiters (global, by_key,

www.jgoy.net · https://server-nexe.org
────────────────────────────────────
"""

import os

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

# MC-103: the per-IP limiter is defined HERE, in core, with no import from
# plugins. Previously core imported limiter_global from
# plugins.security.core.rate_limiting (core→plugins, the wrong direction) and
# plugins.security re-imported `limiter` back from core — a latent import cycle
# hidden behind a try/except. The advanced limiters it pulled (by_key/composite/
# by_endpoint) were dead wiring already removed in MC-123/124. This definition is
# byte-equivalent to the old plugins one (same key_func/limits/storage/strategy),
# so rate-limiting behaviour is unchanged; the dependency now flows plugins→core.
limiter = Limiter(
  key_func=get_remote_address,
  default_limits=[os.getenv("NEXE_RATE_LIMIT_GLOBAL", "100/minute")],
  storage_uri="memory://",
  strategy="fixed-window",
)
# Only the per-IP limiter is enforced (via SlowAPIMiddleware). Kept as a named
# constant because core/middleware.py imports it.
ADVANCED_RATE_LIMITING = False

__all__ = [
  'get_i18n',
  'limiter',
  'ADVANCED_RATE_LIMITING',
]