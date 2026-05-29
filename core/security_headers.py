"""
────────────────────────────────────
Server Nexe
Author: Jordi Goy 
Location: core/security_headers.py
Description: Middleware per security headers OWASP-compliant. Afegeix CSP, HSTS, X-Frame-Options,

www.jgoy.net · https://server-nexe.org
────────────────────────────────────
"""

import logging

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response

logger = logging.getLogger(__name__)


class SecurityHeadersMiddleware(BaseHTTPMiddleware):
  """
  Middleware that adds security headers to all HTTP responses.

  Headers added:
  - Content-Security-Policy: Prevents XSS and data injection attacks
  - Strict-Transport-Security: Enforces HTTPS (air-gapped: localhost only)
  - X-Frame-Options: Prevents clickjacking
  - X-Content-Type-Options: Prevents MIME type sniffing
  - X-XSS-Protection: Legacy XSS protection (for older browsers)
  - Referrer-Policy: Controls referrer information
  - Permissions-Policy: Controls browser features
  """

  async def dispatch(self, request: Request, call_next) -> Response:
    """
    Add security headers to response.

    Args:
      request: Incoming HTTP request
      call_next: Next middleware/handler in chain

    Returns:
      Response with security headers added
    """
    response = await call_next(request)

    # CSP policy:
    # - script-src: NO 'unsafe-inline' in standalone (XSS protection); relaxat
    #   en mode sidecar Tauri (la seguretat la dóna el webview aïllat de Tauri).
    # - style-src: 'unsafe-inline' allowed (needed for Web UI, low security risk)
    # - upgrade-insecure-requests: only on HTTPS (Safari blocks CSS/JS on HTTP if set)
    is_https = request.url.scheme == "https"

    # Relaxar script-src en mode sidecar.
    # En Tauri, el webview executa scripts dins un sandbox aïllat; la garantia
    # de seguretat XSS la dóna l'aïllament del context Tauri, no aquesta CSP.
    # Sense aquesta excepció, els scripts inline del web_ui (plugins/web_ui_module)
    # són bloquejats i la UI no carrega.
    script_src_extra = ""
    try:
      from core.sidecar_config import get_sidecar_config
      if get_sidecar_config().is_sidecar:
        script_src_extra = " 'unsafe-inline' 'unsafe-eval'"
    except Exception as exc:  # pragma: no cover — fallback comportament pre-F2.1
      logger.debug("SidecarConfig unavailable, using strict CSP: %s", exc)

    csp = (
      "default-src 'self'; "
      f"script-src 'self'{script_src_extra}; "
      "style-src 'self' 'unsafe-inline'; "
      "img-src 'self' data:; "
      "font-src 'self' data:; "
      "connect-src 'self'; "
      "frame-ancestors 'none'; "
      "base-uri 'self'; "
      "form-action 'self'"
    )
    if is_https:
      csp += "; upgrade-insecure-requests"
    response.headers["Content-Security-Policy"] = csp

    if is_https:
      response.headers["Strict-Transport-Security"] = (
        "max-age=31536000; includeSubDomains"
      )

    response.headers["X-Frame-Options"] = "DENY"

    response.headers["X-Content-Type-Options"] = "nosniff"

    response.headers["X-XSS-Protection"] = "0"

    response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"

    response.headers["Permissions-Policy"] = (
      "camera=(), "
      "microphone=(), "
      "geolocation=(), "
      "payment=(), "
      "usb=(), "
      "magnetometer=(), "
      "gyroscope=(), "
      "accelerometer=()"
    )

    response.headers["X-Permitted-Cross-Domain-Policies"] = "none"

    is_static = (request.url.path.startswith("/static/")
                 or request.url.path.startswith("/ui/static/"))
    if not is_static:
      response.headers["Cache-Control"] = "no-store, no-cache, must-revalidate, max-age=0"
      response.headers["Pragma"] = "no-cache"
      response.headers["Expires"] = "0"

    return response