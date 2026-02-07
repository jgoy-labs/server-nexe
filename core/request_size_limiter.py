"""
────────────────────────────────────
Server Nexe
Version: 0.8
Author: Jordi Goy 
Location: core/request_size_limiter.py
Description: Middleware to limit request size. Prevents DoS via large payloads (CWE-400).

www.jgoy.net
────────────────────────────────────
"""

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse
import logging
from personality.i18n.resolve import t_modular

logger = logging.getLogger(__name__)

def _t_log(key: str, fallback: str, **kwargs) -> str:
  return t_modular(f"core.request_size.{key}", fallback, **kwargs)

def _t(request: Request, key: str, fallback: str, **kwargs) -> str:
  try:
    i18n = getattr(request.app.state, "i18n", None)
  except Exception:
    i18n = None

  if i18n:
    try:
      value = i18n.t(key, **kwargs)
      if value != key:
        return value
    except Exception:
      pass

  if kwargs:
    try:
      return fallback.format(**kwargs)
    except (KeyError, ValueError):
      return fallback
  return fallback

class RequestSizeLimiterMiddleware(BaseHTTPMiddleware):
  """
  Middleware to enforce maximum request body size.

  Prevents DoS attacks via large payloads (CWE-400: Uncontrolled Resource Consumption).

  Configuration:
    max_size: Maximum request body size in bytes (default: 100MB = 104857600)

  Behavior:
    - If Content-Length header exceeds max_size → reject immediately (413)
    - If no Content-Length but body exceeds max_size → reject during read (413)
    - Logs security event for rejected requests
  """

  def __init__(self, app, max_size: int = 104857600):
    """
    Initialize request size limiter.

    Args:
      app: ASGI application
      max_size: Maximum request body size in bytes (default: 100MB)
    """
    super().__init__(app)
    self.max_size = max_size
    logger.info(
      _t_log(
        "limiter_enabled",
        "Request size limiter enabled: max {size_mb:.1f} MB",
        size_mb=max_size / (1024**2),
      )
    )

  async def dispatch(self, request: Request, call_next):
    """
    Check request size and reject if too large.

    SECURITY: Checks both Content-Length and chunked/streaming.

    Args:
      request: Incoming HTTP request
      call_next: Next middleware/handler in chain

    Returns:
      Response (either 413 error or normal response from handler)
    """
    client_ip = request.client.host if request.client else "unknown"

    content_length = request.headers.get("content-length")

    if content_length:
      try:
        content_length_int = int(content_length)
        if content_length_int < 0:
          raise ValueError(_t_log(
            "negative_content_length",
            "Negative Content-Length"
          ))

        if content_length_int > self.max_size:
          if hasattr(request.app.state, 'security_logger'):
            request.app.state.security_logger.log_request_too_large(
              size=content_length_int,
              max_size=self.max_size,
              ip_address=client_ip,
              endpoint=str(request.url.path)
            )

          logger.warning(
            _t(
              request,
              "core.request_size.request_rejected",
              "Request rejected: size {size_mb:.2f} MB exceeds limit {limit_mb:.2f} MB from {ip} to {path}",
              size_mb=content_length_int / (1024**2),
              limit_mb=self.max_size / (1024**2),
              ip=client_ip,
              path=request.url.path,
            )
          )

          return JSONResponse(
            status_code=413,
            content={
              "error": _t(
                request,
                "core.request_size.error_entity_too_large",
                "Request Entity Too Large"
              ),
              "detail": _t(
                request,
                "core.request_size.detail_content_length",
                "Content-Length ({content_length}) exceeds max ({max_size})",
                content_length=content_length_int,
                max_size=self.max_size
              ),
              "max_size_mb": round(self.max_size / (1024**2), 2),
            }
          )

      except ValueError:
        logger.warning(
          _t(
            request,
            "core.request_size.invalid_content_length",
            "Invalid Content-Length header: {value}",
            value=content_length,
          )
        )
        content_length = None

    if request.method in ("POST", "PUT", "PATCH") and not content_length:
      body_bytes = 0
      body_chunks = []

      try:
        async for chunk in request.stream():
          body_bytes += len(chunk)

          if body_bytes > self.max_size:
            if hasattr(request.app.state, 'security_logger'):
              request.app.state.security_logger.log_request_too_large(
                size=body_bytes,
                max_size=self.max_size,
                ip_address=client_ip,
                endpoint=str(request.url.path)
              )

            logger.warning(
              _t(
                request,
                "core.request_size.streaming_rejected",
                "Streaming request rejected: {size} bytes exceeds limit {limit} from {ip}",
                size=body_bytes,
                limit=self.max_size,
                ip=client_ip,
              )
            )

            return JSONResponse(
              status_code=413,
              content={
                "error": _t(
                  request,
                  "core.request_size.error_entity_too_large_streaming",
                  "Request Entity Too Large (streaming)"
                ),
                "detail": _t(
                  request,
                  "core.request_size.detail_body_size",
                  "Body size ({body_size}) exceeds max ({max_size})",
                  body_size=body_bytes,
                  max_size=self.max_size
                ),
                "max_size_mb": round(self.max_size / (1024**2), 2),
              }
            )

          body_chunks.append(chunk)

        body = b"".join(body_chunks)

        body_consumed = False

        async def receive():
          nonlocal body_consumed
          if not body_consumed:
            body_consumed = True
            return {"type": "http.request", "body": body, "more_body": False}
          return {"type": "http.request", "body": b"", "more_body": False}

        request._receive = receive

      except Exception as e:
        logger.error(
          _t(
            request,
            "core.request_size.body_read_error_log",
            "Error reading request body: {error}",
            error=str(e),
          )
        )
        return JSONResponse(
          status_code=400,
          content={
            "error": _t(
              request,
              "core.request_size.error_body_read",
              "Failed to read request body"
            )
          }
        )

    response = await call_next(request)
    return response
