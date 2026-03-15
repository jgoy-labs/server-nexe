"""
────────────────────────────────────
Server Nexe
Version: 0.8
Author: Jordi Goy 
Location: core/security_headers.py
Description: Middleware per security headers OWASP-compliant. Afegeix CSP, HSTS, X-Frame-Options,

www.jgoy.net · https://server-nexe.org
────────────────────────────────────
"""

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response

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
    # - script-src: NO 'unsafe-inline' (XSS protection)
    # - style-src: 'unsafe-inline' allowed (needed for Web UI, low security risk)
    # - upgrade-insecure-requests: only on HTTPS (Safari blocks CSS/JS on HTTP if set)
    is_https = request.url.scheme == "https"
    csp = (
      "default-src 'self'; "
      "script-src 'self'; "
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

    response.headers["X-XSS-Protection"] = "1; mode=block"

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

    if not request.url.path.startswith("/static/"):
      response.headers["Cache-Control"] = "no-store, no-cache, must-revalidate, max-age=0"
      response.headers["Pragma"] = "no-cache"
      response.headers["Expires"] = "0"

    return response