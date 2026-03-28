"""
────────────────────────────────────
Server Nexe
Author: Jordi Goy 
Location: core/server/exception_handlers.py
Description: Exception handlers globals per FastAPI. Gestiona RateLimitExceeded, HTTPException,

www.jgoy.net · https://server-nexe.org
────────────────────────────────────
"""

import logging
import uuid

from fastapi import FastAPI, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from slowapi.errors import RateLimitExceeded

from .helpers import translate

logger = logging.getLogger(__name__)

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
    logger.error(
      "Validation error on %s: %s",
      request.url.path,
      exc.errors()
    )

    return JSONResponse(
      status_code=422,
      content={
        "error": translate(i18n, 'server_core.errors.validation_error', "Validation error"),
        "detail": exc.errors()
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