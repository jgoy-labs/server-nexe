"""
────────────────────────────────────
Server Nexe
Version: 0.8
Author: Jordi Goy 
Location: core/middleware.py
Description: FastAPI middleware configuration: CORS, rate limiting, security headers, request

www.jgoy.net · https://server-nexe.org
────────────────────────────────────
"""

from typing import Dict, Any
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from slowapi import _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded
from slowapi.middleware import SlowAPIMiddleware
from starlette.middleware.trustedhost import TrustedHostMiddleware
import logging

from core.dependencies import (
  limiter,
  ADVANCED_RATE_LIMITING
)

from core.security_headers import SecurityHeadersMiddleware
from core.request_size_limiter import RequestSizeLimiterMiddleware

logger = logging.getLogger(__name__)

# ═══════════════════════════════════════════════════════════════════════════
# CSRF EXEMPT PATTERNS - Pre-compiled at module load (not per-request)
# Using simple prefix patterns that starlette-csrf can match efficiently
# ═══════════════════════════════════════════════════════════════════════════
import re
_CSRF_EXEMPT_PATTERNS = [
    re.compile(r"^/v1/chat/completions"),
    re.compile(r"^/v1/memory/"),  # Memory API (CLI calls)
    re.compile(r"^/v1/audio/transcriptions"),
    re.compile(r"^/v1/"),        # All v1 API endpoints (API key auth)
    re.compile(r"^/rag/"),       # RAG API (API key auth, not session-based)
    re.compile(r"^/chat"),       # Chat endpoint (API key auth)
    re.compile(r"^/health"),
    re.compile(r"^/metrics"),
    re.compile(r"^/ui/"),  # UI uses X-API-Key auth (works for local + Tailscale)
]

def _translate(i18n, key: str, fallback: str, **kwargs) -> str:
  """Helper to translate with fallback (for non-endpoint functions)"""
  if not i18n:
    return fallback.format(**kwargs) if kwargs else fallback
  value = i18n.t(key, **kwargs)
  if value == key:
    return fallback.format(**kwargs) if kwargs else fallback
  return value

def setup_rate_limiting(app: FastAPI, i18n = None) -> None:
  """
  Setup rate limiting for the application

  Advanced rate limiting with:
  - Multiple limiters (IP, API key, composite, endpoint)
  - X-RateLimit-* headers
  - Background cleanup task (started via startup event)

  Args:
    app: FastAPI application instance
    i18n: Optional I18n instance for translations
  """
  app.state.limiter = limiter

  app.add_middleware(SlowAPIMiddleware)

  app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)

  if ADVANCED_RATE_LIMITING:
    try:
      from core.dependencies import (
        limiter_by_key,
        limiter_composite,
        limiter_by_endpoint,
        start_rate_limit_cleanup_task,
      )

      app.state.limiter_by_key = limiter_by_key
      app.state.limiter_composite = limiter_composite
      app.state.limiter_by_endpoint = limiter_by_endpoint

      app.state.start_rate_limit_cleanup = start_rate_limit_cleanup_task

      logger.info("Advanced rate limiting enabled")
      logger.info("  - IP rate limiting: OK")
      logger.info("  - API key rate limiting: OK")
      logger.info("  - Composite rate limiting: OK")
      logger.info("  - X-RateLimit-* headers: OK")

    except Exception as e:
      msg1 = _translate(i18n, "core.middleware.rate_limit_advanced_failed", "Advanced rate limiting setup failed: {error}", error=str(e))
      msg2 = _translate(i18n, "core.middleware.rate_limit_fallback", "  Falling back to basic rate limiting")
      logger.warning(msg1)
      logger.info(msg2)
  else:
    msg = _translate(i18n, "core.middleware.rate_limit_basic", "Using basic rate limiting (per-IP only)")
    logger.info(msg)

def setup_cors(app: FastAPI, config: Dict[str, Any], i18n = None) -> None:
  """
  Setup CORS middleware with strict validation
  SECURITY FIX: No wildcards allowed, explicit origins/methods/headers

  Args:
    app: FastAPI application instance
    config: Configuration dictionary
    i18n: Optional I18n instance for translations

  Raises:
    ValueError: If CORS config contains wildcards (not allowed in air-gapped mode)
  """
  import logging
  logger = logging.getLogger(__name__)

  server_config = config.get('core', {}).get('server', {})

  cors_origins = server_config.get('cors_origins', [])
  cors_methods = server_config.get('cors_methods', ["GET", "POST", "OPTIONS"])
  cors_headers = server_config.get('cors_headers', [
    "Content-Type", "Authorization", "X-API-Key"
  ])

  if "*" in cors_origins:
    msg = _translate(i18n, "core.cors.wildcard_not_allowed",
      "CORS wildcard '*' not allowed in air-gapped mode. Define explicit origins in server.toml [core.server] cors_origins")

    if hasattr(app.state, 'security_logger'):
      app.state.security_logger.log_config_validation_failed(
        config_key="cors_origins",
        invalid_value="*",
        reason="Wildcard not allowed in air-gapped mode"
      )

    raise ValueError(msg)

  if not cors_origins:
    msg = _translate(i18n, "core.cors.origins_not_configured",
      "CORS origins not configured. Define explicit origins in server.toml [core.server] cors_origins")

    if hasattr(app.state, 'security_logger'):
      app.state.security_logger.log_config_validation_failed(
        config_key="cors_origins",
        invalid_value="[]",
        reason="CORS origins not configured (empty list)"
      )

    raise ValueError(msg)

  logger.info(f"CORS configured: origins={cors_origins}")
  logger.debug(f"  methods={cors_methods}")
  logger.debug(f"  headers={cors_headers}")

  app.add_middleware(
    CORSMiddleware,
    allow_origins=cors_origins,
    allow_credentials=True,
    allow_methods=cors_methods,
    allow_headers=cors_headers,
  )

def setup_request_size_limit(app: FastAPI, config: Dict[str, Any]) -> None:
  """
  Setup request size limiter middleware

  Args:
    app: FastAPI application instance
    config: Configuration dictionary
  """
  import logging
  logger = logging.getLogger(__name__)

  server_config = config.get('core', {}).get('server', {})

  max_request_size = server_config.get('max_request_size', 104857600)

  app.add_middleware(RequestSizeLimiterMiddleware, max_size=max_request_size)

  logger.info(f"Request size limit: {max_request_size / (1024**2):.1f} MB")

def setup_prometheus_metrics(app: FastAPI) -> None:
  """
  Setup Prometheus metrics middleware.

  Args:
    app: FastAPI application instance
  """
  try:
    from core.metrics.middleware import PrometheusMiddleware
    app.add_middleware(PrometheusMiddleware)
    logger.info("prometheus_metrics_middleware_enabled")
  except ImportError as e:
    logger.warning(f"prometheus_metrics_not_available: {e}")

def setup_csrf_protection(app: FastAPI, config: Dict[str, Any]) -> None:
  """
  Setup CSRF protection middleware.

  Args:
    app: FastAPI application instance
    config: Configuration dictionary
  """
  import os

  csrf_secret = os.getenv("NEXE_CSRF_SECRET")
  is_prod = os.getenv("NEXE_ENV", "development") == "production"

  if not csrf_secret:
    if is_prod:
      # In production, require explicit CSRF secret configuration
      logger.error("NEXE_CSRF_SECRET not configured in production mode!")
      logger.error("   Sessions will be invalidated on each restart.")
      logger.error("   Set NEXE_CSRF_SECRET in .env for persistent sessions.")
      # Generate temporary but log clearly
      import secrets
      csrf_secret = secrets.token_hex(32)
    else:
      # Development mode: generate temporary secret with warning
      import secrets
      csrf_secret = secrets.token_hex(32)
      logger.warning("CSRF_SECRET not configured. Using temporary secret (dev mode only)")

  try:
    from starlette.middleware import Middleware
    from starlette_csrf import CSRFMiddleware

    # SECURITY FIX: cookie_secure only if HTTPS is actually used.
    # Avoids issues in development environments or local tests without SSL.
    # Note: is_prod already defined above
    server_config = config.get('core', {}).get('server', {})
    
    # Default True in prod, False in dev, but disabled if known local host
    # unless explicitly forced in config.
    host = server_config.get('host', '127.0.0.1')
    is_local = host in ("localhost", "127.0.0.1", "::1", "0.0.0.0")
    
    cookie_secure = is_prod and not is_local
    
    # Allow manual override if user has SSL locally or not in prod
    if "csrf_cookie_secure" in server_config:
      cookie_secure = server_config["csrf_cookie_secure"]
      logger.info(f"  CSRF cookie_secure manual override: {cookie_secure}")

    # Use pre-compiled patterns from module level (more efficient)
    # header_name must match the JS fetchWithCsrf() which sends 'X-CSRF-Token'
    app.add_middleware(
      CSRFMiddleware,
      secret=csrf_secret,
      cookie_name="nexe_csrf_token",
      header_name="X-CSRF-Token",
      cookie_secure=cookie_secure,
      cookie_samesite="strict",
      exempt_urls=_CSRF_EXEMPT_PATTERNS,  # Pre-compiled at module load
    )
    logger.info("CSRF protection enabled")
  except ImportError:
    logger.warning("starlette-csrf not installed. CSRF protection disabled.")
    logger.warning("  Install with: pip install starlette-csrf")

def setup_trusted_hosts(app: FastAPI, config: Dict[str, Any]) -> None:
  """
  Setup TrustedHostMiddleware to block DNS rebinding attacks.

  A malicious web page could bind its domain to 127.0.0.1 and then
  make cross-origin requests to localhost:9119. This middleware rejects
  requests with unexpected Host headers.

  Args:
    app: FastAPI application instance
    config: Configuration dictionary
  """
  server_config = config.get('core', {}).get('server', {})
  host = server_config.get('host', '127.0.0.1')

  # Base allowed hosts: always include localhost variants
  allowed = {"localhost", "127.0.0.1", "::1"}

  # If server binds to a custom host/domain, allow it too
  if host and host not in ("0.0.0.0", ""):
    allowed.add(host)

  app.add_middleware(TrustedHostMiddleware, allowed_hosts=list(allowed))
  logger.info("TrustedHostMiddleware: allowed_hosts=%s", sorted(allowed))


def setup_all_middleware(app: FastAPI, config: Dict[str, Any], i18n = None) -> None:
  """
  Setup all middleware for the application

  Args:
    app: FastAPI application instance
    config: Configuration dictionary
    i18n: Optional I18n instance for translations
  """
  setup_prometheus_metrics(app)

  app.add_middleware(SecurityHeadersMiddleware)

  setup_csrf_protection(app, config)

  setup_request_size_limit(app, config)

  setup_rate_limiting(app, i18n)
  setup_cors(app, config, i18n)

  # TrustedHostMiddleware last (outermost layer — first to see requests)
  setup_trusted_hosts(app, config)