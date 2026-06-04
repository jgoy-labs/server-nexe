"""
────────────────────────────────────
Server Nexe
Author: Jordi Goy 
Location: core/middleware.py
Description: FastAPI middleware configuration: CORS, rate limiting, security headers, request

www.jgoy.net · https://server-nexe.org
────────────────────────────────────
"""

from typing import Dict, Any, List, Tuple
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from slowapi import _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded
from slowapi.middleware import SlowAPIMiddleware
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.middleware.trustedhost import TrustedHostMiddleware
from starlette.requests import Request
import logging
import re

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
    # /admin/system/* is X-API-Key authenticated and called
    # from the Tauri Rust client (cookie-less). Without this exemption,
    # starlette-csrf returned 403 on the graceful shutdown POST and lifecycle.rs
    # always fell back to SIGKILL.
    re.compile(r"^/admin/"),
    # /installer/* is called by the onboarding wizard
    # ABANS que l'usuari tingui API key. Loopback-only (127.0.0.1) + Tauri
    # WebView. POST /installer/finalize sense exempció = 403 → wizard mai
    # acaba. Descobert empíricament al cicle local 2026-05-20.
    re.compile(r"^/installer/"),
]

from core.server.helpers import translate as _translate  # noqa: E402

# ═══════════════════════════════════════════════════════════════════════════
# REMOVED DIRECT ROUTES GUARD
#
# Routes declared in manifest.removed_direct_routes are registered here at
# plugin load time (by personality/module_manager/module_manager.py).
# The middleware checks every incoming request against this registry and
# returns 403 before any other processing.
#
# Design notes:
# - Registry is module-level (mutable) and populated at startup. By the
#   time the first request arrives all plugins are already loaded → safe.
# - Guard is positioned second-to-outermost (just inside TrustedHostMiddleware)
#   so blocked requests bypass CORS, SlowAPI, CSRF, and handlers entirely.
#   Consequence: 403 responses do NOT include CORS headers. This is intentional
#   — an attacker attempting a direct-endpoint bypass gets no extra info.
# ═══════════════════════════════════════════════════════════════════════════

# {full_route: (plugin_name, manifest_route)}
_REMOVED_ROUTE_REGISTRY: Dict[str, Tuple[str, str]] = {}

# [(compiled_pattern, plugin_name, manifest_route, full_route), ...]
_REMOVED_ROUTE_PATTERNS: List[Tuple[re.Pattern, str, str, str]] = []


def _build_route_pattern(route: str) -> re.Pattern:
    """Compile a FastAPI route pattern to a regex.

    Handles {param} (single segment) and {param:path} (multi-segment).
    """
    parts = re.split(r"\{[^}]+\}", route)
    params = re.findall(r"\{([^}]+)\}", route)
    result = re.escape(parts[0])
    for i, param in enumerate(params):
        result += (".+" if ":path" in param else "[^/]+")
        result += re.escape(parts[i + 1])
    return re.compile(f"^{result}$")


def register_removed_route(plugin_name: str, manifest_route: str, prefix: str) -> None:
    """Register a removed direct route in the guard registry.

    Called from module_manager._load_plugin_routers_from_manifest at plugin
    load time. Idempotent: re-registering the same full_route is a no-op.

    Args:
        plugin_name:    Plugin module name (e.g. "mlx_module").
        manifest_route: Relative route from removed_direct_routes (e.g. "/chat").
        prefix:         Router prefix (e.g. "/mlx"). Comes from router.prefix.
    """
    full_route = (prefix.rstrip("/") + manifest_route) if prefix else manifest_route
    if full_route in _REMOVED_ROUTE_REGISTRY:
        return
    _REMOVED_ROUTE_REGISTRY[full_route] = (plugin_name, manifest_route)
    _REMOVED_ROUTE_PATTERNS.append((
        _build_route_pattern(full_route),
        plugin_name,
        manifest_route,
        full_route,
    ))
    logger.info("RemovedDirectRoutesGuard: registered %s (plugin=%s)", full_route, plugin_name)


class RemovedDirectRoutesGuard(BaseHTTPMiddleware):
    """Block HTTP requests to routes declared as removed in plugin manifests.

    Returns 403 with error code 'direct_plugin_endpoint_disabled' for any
    request whose path matches a route in _REMOVED_ROUTE_PATTERNS. Runs
    before SlowAPI, CORS, CSRF, and route handlers.
    """

    async def dispatch(self, request: Request, call_next):
        """Return 403 for paths matching removed plugin routes; pass through otherwise."""
        path = request.url.path
        for pattern, plugin_name, manifest_route, full_route in _REMOVED_ROUTE_PATTERNS:
            if pattern.match(path):
                client_ip = request.client.host if request.client else "unknown"
                user_agent = request.headers.get("user-agent", "unknown")
                logger.warning(
                    "security.plugin.direct_access_blocked",
                    extra={
                        "event": "security.plugin.direct_access_blocked",
                        "plugin_name": plugin_name,
                        "route": manifest_route,
                        "full_route": full_route,
                        "client_ip": client_ip,
                        "user_agent": user_agent,
                    },
                )
                return JSONResponse(
                    status_code=403,
                    content={
                        "error": "direct_plugin_endpoint_disabled",
                        "message": (
                            "Direct plugin endpoint access is disabled. "
                            "Use /ui/chat or /v1/chat/completions."
                        ),
                        "removed_route": full_route,
                    },
                )
        return await call_next(request)


def setup_removed_direct_routes_guard(app: FastAPI) -> None:
    """Add RemovedDirectRoutesGuard to the middleware stack."""
    app.add_middleware(RemovedDirectRoutesGuard)
    logger.info("RemovedDirectRoutesGuard middleware registered")


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

  # in sidecar mode, override cors_origins with SidecarConfig
  # which includes tauri://localhost + http://localhost:1420 (resolves A8).
  # Standalone (no NEXE_SIDECAR): server.toml mana.
  try:
    from core.sidecar_config import get_sidecar_config
    sidecar_cfg = get_sidecar_config()
    if sidecar_cfg.is_sidecar:
      cors_origins = list(sidecar_cfg.cors_origins)
      logger.info(
        "CORS: sidecar mode override — using SidecarConfig.cors_origins "
        "(includes Tauri origins)"
      )
  except Exception as e:  # pragma: no cover
    # Defensive: si get_sidecar_config() falla per qualsevol motiu,
    # fall back to cors_origins from server.toml (pre-sidecar behaviour).
    logger.warning("CORS: SidecarConfig unavailable, falling back to server.toml: %s", e)

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

def _load_or_create_persistent_csrf_secret() -> str:
  """Load or generate-and-persist the CSRF cookie-signing secret.

  Without persistence the previous implementation generated a fresh secret
  on every boot via ``secrets.token_hex(32)``, which silently invalidated
  every signed CSRF cookie and forced users to re-authenticate after each
  restart. ``NEXE_CSRF_SECRET`` and ``SidecarConfig.csrf_secret`` still take
  priority and are checked by the caller; this helper is the last-resort
  fallback that stores the generated secret under the appropriate data
  directory (``SidecarConfig.data_dir`` in sidecar mode, ``~/.nexe``
  otherwise) with permission 0600.
  """
  import os
  import secrets
  from pathlib import Path

  secret_path = None
  try:
    from core.sidecar_config import get_sidecar_config
    cfg = get_sidecar_config()
    if cfg.is_sidecar and getattr(cfg, "data_dir", None):
      secret_path = Path(cfg.data_dir) / "csrf_secret"
  except Exception as exc:
    logger.debug("SidecarConfig unavailable in csrf secret loader: %s", exc)  # nosemgrep: python-logger-credential-disclosure

  if secret_path is None:
    secret_path = Path.home() / ".nexe" / "csrf_secret"

  try:
    if secret_path.exists():
      existing = secret_path.read_text(encoding="ascii").strip()
      if len(existing) >= 32:
        logger.info("CSRF secret loaded from %s (persistent)", secret_path)  # nosemgrep: python-logger-credential-disclosure
        return existing
      logger.warning(  # nosemgrep: python-logger-credential-disclosure
        "CSRF secret file %s is too short (%d chars), regenerating",
        secret_path, len(existing),
      )
  except Exception as exc:
    logger.warning("failed to read %s, regenerating: %s", secret_path, exc)  # nosemgrep: python-logger-credential-disclosure

  new_secret = secrets.token_hex(32)
  try:
    secret_path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = secret_path.with_suffix(".tmp")
    tmp_path.write_text(new_secret, encoding="ascii")
    os.chmod(tmp_path, 0o600)
    tmp_path.replace(secret_path)
    logger.info("CSRF secret generated and persisted to %s", secret_path)  # nosemgrep: python-logger-credential-disclosure
  except Exception as exc:
    logger.warning(  # nosemgrep: python-logger-credential-disclosure
      "failed to persist CSRF secret to %s (sessions will "
      "be invalidated on next boot): %s",
      secret_path, exc,
    )

  return new_secret


def setup_csrf_protection(app: FastAPI, config: Dict[str, Any]) -> None:
  """
  Setup CSRF protection middleware.

  In sidecar mode use SidecarConfig.csrf_secret + is_production
  (override de NEXE_CSRF_SECRET + NEXE_ENV directes per consistència amb la resta
  de consumers).

  If neither env nor SidecarConfig carry a secret, the helper
  _load_or_create_persistent_csrf_secret() persisteix un secret estable a
  disc (0600) en comptes de regenerar-lo a cada boot.

  Args:
    app: FastAPI application instance
    config: Configuration dictionary
  """
  import os

  csrf_secret = os.getenv("NEXE_CSRF_SECRET")
  config_mode = config.get("core", {}).get("environment", {}).get("mode", "").lower()

  # prefer SidecarConfig.is_production over direct NEXE_ENV,
  # combinem amb OR sobre el raw env per a robustesa davant singletons stale.
  # Session 3 part 3 already overrode csrf_secret + is_prod with SidecarConfig.
  raw_is_prod = os.getenv("NEXE_ENV", "development") == "production"
  sidecar_is_prod = False
  try:
    from core.sidecar_config import get_sidecar_config
    cfg = get_sidecar_config()
    sidecar_is_prod = cfg.is_production
    if cfg.is_sidecar and cfg.csrf_secret:
      csrf_secret = cfg.csrf_secret
  except Exception as exc:
    logger.debug(
      "SidecarConfig unavailable in setup_csrf, using NEXE_ENV fallback: %s",
      exc,
    )
  is_prod = sidecar_is_prod or raw_is_prod or config_mode == "production"

  if not csrf_secret:
    # persist a stable secret on disk so cookies survive
    # restarts. NEXE_CSRF_SECRET still wins when set; this fallback just
    # avoids the old "regenerate every boot" failure mode.
    if is_prod:
      logger.warning(
        "NEXE_CSRF_SECRET not configured in production. Falling back to "
        "the persistent on-disk secret. Set NEXE_CSRF_SECRET in .env if you "
        "prefer to manage the secret via configuration."
      )
    csrf_secret = _load_or_create_persistent_csrf_secret()

  from starlette_csrf import CSRFMiddleware

  # SECURITY FIX: cookie_secure only if HTTPS is actually used.
  # Avoids issues in development environments or local tests without SSL.
  # Note: is_prod already defined above
  server_config = config.get('core', {}).get('server', {})

  # Default True in prod, False in dev, but disabled if known local host
  # unless explicitly forced in config.
  from core.config import DEFAULT_HOST, get_localhost_aliases
  host = server_config.get('host', DEFAULT_HOST)
  is_local = host in set(get_localhost_aliases())
  # 0.0.0.0 binds ALL interfaces including public — treat as non-local

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
  from core.config import DEFAULT_HOST, get_localhost_aliases
  server_config = config.get('core', {}).get('server', {})
  host = server_config.get('host', DEFAULT_HOST)

  # Base allowed hosts: always include localhost variants (Q4.4 DRY fix)
  allowed = set(get_localhost_aliases())

  # If server binds to a custom host/domain, allow it too
  if host and host not in ("0.0.0.0", ""):  # nosec B104: comparing to "0.0.0.0" string, not binding to it (allow-list construction for TrustedHostMiddleware)
    allowed.add(host)

  # in sidecar mode, SidecarConfig.trusted_hosts can add aliases
  # custom (NEXE_LOCALHOST_ALIASES). Union amb el set actual per no perdre defaults.
  try:
    from core.sidecar_config import get_sidecar_config
    sidecar_cfg = get_sidecar_config()
    if sidecar_cfg.is_sidecar:
      allowed.update(sidecar_cfg.trusted_hosts)
      logger.debug("TrustedHosts: sidecar mode — union with SidecarConfig.trusted_hosts")
  except Exception as e:  # pragma: no cover
    logger.warning("TrustedHosts: SidecarConfig unavailable: %s", e)

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
  # Starlette: last added = outermost (first to see request, last to see response)
  # Order below: innermost → outermost
  setup_prometheus_metrics(app)           # innermost — metrics collection
  setup_cors(app, config, i18n)           # CORS headers
  setup_rate_limiting(app, i18n)          # rate limiting
  setup_request_size_limit(app, config)   # request size check
  setup_csrf_protection(app, config)      # CSRF validation
  app.add_middleware(SecurityHeadersMiddleware)   # security headers on responses
  setup_removed_direct_routes_guard(app)  # blocks removed plugin routes (before TrustedHost)
  setup_trusted_hosts(app, config)        # outermost — host validation first