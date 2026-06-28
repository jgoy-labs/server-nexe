"""
────────────────────────────────────
Server Nexe
Author: Jordi Goy 
Location: core/server/exception_handlers.py
Description: Global exception handlers for FastAPI. Handles RateLimitExceeded, HTTPException,

www.jgoy.net · https://server-nexe.org
────────────────────────────────────
"""

import logging
import re
import uuid

from fastapi import FastAPI, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from slowapi.errors import RateLimitExceeded

from .helpers import translate

logger = logging.getLogger(__name__)

_RETRY_AFTER_DEFAULT = 60
_UNIT_SECONDS = {"second": 1, "minute": 60, "hour": 3600, "day": 86400}
_LIMIT_RE = re.compile(r"per\s+(\d+)\s*(second|minute|hour|day)", re.IGNORECASE)


def _retry_after_seconds(detail: str | None) -> int:
  """Best-effort parse of slowapi limit detail (`'<n> per <m> <unit>'`) → secs.

  Falls back to 60 when the detail string is missing or unparseable. Compliant
  with RFC 7231 §7.1.3: `Retry-After: <delay-seconds>` (integer).
  """
  if not detail:
    return _RETRY_AFTER_DEFAULT
  match = _LIMIT_RE.search(detail)
  if not match:
    return _RETRY_AFTER_DEFAULT
  multiplier_seconds = _UNIT_SECONDS[match.group(2).lower()]
  return int(match.group(1)) * multiplier_seconds

_JSON_PRIMITIVE = (str, int, float, bool, type(None))


def _sanitize_ctx(ctx: object) -> dict | None:
  """Keep only JSON-primitive ``ctx`` entries (B256).

  For a *custom* ``@field_validator`` that ``raise``s, Pydantic v2 packs the raw
  exception into ``ctx={'error': ValueError(...)}`` — a non-JSON-serialisable
  object. Left untouched it detonates twice: ``JSONResponse.render()`` raises
  ``TypeError: ... not JSON serializable`` (the 422 collapses into a latent 500),
  and the ``ValueError``'s repr — which may echo the user's value — reaches the
  log. Standard constraint failures use flat primitive ctx (e.g.
  ``{'max_length': 200}``), which survives untouched so diagnostics stay intact.
  """
  if not isinstance(ctx, dict):
    return None
  safe = {k: v for k, v in ctx.items() if k != "error" and isinstance(v, _JSON_PRIMITIVE)}
  return safe or None


def _sanitize_validation_errors(errors: list) -> list:
  """Strip non-diagnostic, value-bearing fields from Pydantic validation errors
  before they are logged or returned in the 422 body (B254 + B256).

  B254: ``input`` echoes the offending value — for an oversized HF-token paste
  that value IS the secret. B256: ``ctx`` may carry a non-serialisable exception
  from a custom validator (see ``_sanitize_ctx``). The client already holds the
  value and never reads the 422 body (only the status); the log does not need it
  either. ``type``/``loc``/``msg``/``url`` and primitive ``ctx`` entries carry no
  landmine, so diagnostics stay intact. Applies to every validated endpoint via
  the global handler below.

  B259 (design decision): ``msg`` is intentionally NOT genericised. Pydantic
  packs a custom validator's ``ValueError`` text into ``msg`` ("Value error,
  <text>"), so blanket-stripping it would discard useful domain diagnostics the
  client needs ("model not in allowlist", "must match ..."). The contract is the
  inverse and lives at the source: an HTTP request-body ``@field_validator`` MUST
  NOT interpolate the user's value into its ``ValueError`` message (keep it
  static). Today the only such validator is ``PullModelRequest._validate_name``
  (static; guarded by tests/core/server/test_validation_error_redaction.py).
  """
  out = []
  for err in errors:
    clean = {k: v for k, v in err.items() if k not in ("input", "ctx")}
    safe_ctx = _sanitize_ctx(err.get("ctx"))
    if safe_ctx is not None:
      clean["ctx"] = safe_ctx
    out.append(clean)
  return out


def register_exception_handlers(app: FastAPI, i18n) -> None:
  """Register global exception handlers for the application."""

  @app.exception_handler(RateLimitExceeded)
  async def rate_limit_handler(request: Request, exc: RateLimitExceeded):
    """Handle rate limit exceeded with SIEM logging"""
    if hasattr(request.app.state, 'security_logger'):
      client_ip = request.client.host if request.client else "unknown"
      request.app.state.security_logger.log_rate_limit_exceeded(
        ip_address=client_ip,
        endpoint=str(request.url.path),
        limit=None
      )

    response = JSONResponse(
      status_code=429,
      content={"error": translate(i18n, "core.server.rate_limit_exceeded_error", "Rate limit exceeded: {detail}", detail=exc.detail)}
    )

    if hasattr(request.state, 'view_rate_limit') and hasattr(request.app.state, 'limiter'):
      response = request.app.state.limiter._inject_headers(
        response, request.state.view_rate_limit
      )

    # RFC 7231 §7.1.3: 429 SHOULD carry Retry-After. slowapi's _inject_headers
    # emits X-RateLimit-* (de-facto) but not the standard header — add it
    # explicitly so well-behaved clients can back off correctly (auditoria r4 C13).
    response.headers["Retry-After"] = str(_retry_after_seconds(exc.detail))

    return response

  @app.exception_handler(HTTPException)
  async def http_exception_handler(request: Request, exc: HTTPException):
    """HTTP exception handler"""
    if exc.status_code == 401:
      logger.debug(
        "HTTP %s: %s - Path: %s (expected from UI)",
        exc.status_code,
        exc.detail,
        request.url.path
      )
    else:
      logger.warning(
        "HTTP %s: %s - Path: %s",
        exc.status_code,
        exc.detail,
        request.url.path
      )

    return JSONResponse(
      status_code=exc.status_code,
      content={
        "error": translate(i18n, 'server_core.errors.http_error', "HTTP error"),
        "detail": exc.detail
      }
    )

  @app.exception_handler(RequestValidationError)
  async def validation_exception_handler(request: Request, exc: RequestValidationError):
    """Validation error handler"""
    # B254: never log nor echo the offending value (Pydantic's ``input``) — for an
    # oversized HF-token paste that field is the secret itself.
    safe_errors = _sanitize_validation_errors(exc.errors())
    logger.error(
      "Validation error on %s: %s",
      request.url.path,
      safe_errors
    )

    return JSONResponse(
      status_code=422,
      content={
        "error": translate(i18n, 'server_core.errors.validation_error', "Validation error"),
        "detail": safe_errors
      }
    )

  @app.exception_handler(Exception)
  async def general_exception_handler(request: Request, exc: Exception):
    """General exception handler with structured logging"""
    trace_id = str(uuid.uuid4())

    logger.exception(
      "Unhandled exception [trace_id: %s] on %s: %s",
      trace_id,
      request.url.path,
      str(exc)
    )

    return JSONResponse(
      status_code=500,
      content={
        "error": translate(i18n, 'server_core.errors.internal_error', "Internal server error"),
        "trace_id": trace_id
      }
    )