"""
────────────────────────────────────
Server Nexe
Author: Jordi Goy 
Location: core/request_size_limiter.py
Description: Middleware to limit request size. Prevents DoS via large payloads (CWE-400).

www.jgoy.net · https://server-nexe.org
────────────────────────────────────
"""

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse
import logging

logger = logging.getLogger(__name__)

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
    logger.info(f"Request size limiter enabled: max {max_size / (1024**2):.1f} MB")

  def _reject_too_large(self, size: int, client_ip: str, request: Request, streaming: bool = False) -> JSONResponse:
    """Log security event and return a 413 rejection response."""
    endpoint = str(request.url.path)

    if hasattr(request.app.state, 'security_logger'):
      request.app.state.security_logger.log_request_too_large(
        size=size,
        max_size=self.max_size,
        ip_address=client_ip,
        endpoint=endpoint,
      )

    if streaming:
      logger.warning(
        f"Streaming request rejected: {size} bytes "
        f"exceeds limit {self.max_size} from {client_ip}"
      )
      error_label = "Request Entity Too Large (streaming)"
      detail = f"Body size ({size}) exceeds max ({self.max_size})"
    else:
      logger.warning(
        f"Request rejected: size {size / (1024**2):.2f} MB "
        f"exceeds limit {self.max_size / (1024**2):.2f} MB "
        f"from {client_ip} to {endpoint}"
      )
      error_label = "Request Entity Too Large"
      detail = f"Content-Length ({size}) exceeds max ({self.max_size})"

    return JSONResponse(
      status_code=413,
      content={
        "error": error_label,
        "detail": detail,
        "max_size_mb": round(self.max_size / (1024**2), 2),
      }
    )

  async def _read_streaming_body(self, request: Request, client_ip: str):
    """Read request body via streaming, reject if too large.

    On success, replaces ``request._receive`` so downstream handlers
    can read the already-consumed body.  Returns ``None`` on success
    or a :class:`JSONResponse` on error/rejection.
    """
    body_bytes = 0
    body_chunks = []

    try:
      async for chunk in request.stream():
        body_bytes += len(chunk)

        if body_bytes > self.max_size:
          return self._reject_too_large(body_bytes, client_ip, request, streaming=True)

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
      return None

    except Exception as e:
      logger.error(f"Error reading request body: {e}")
      return JSONResponse(
        status_code=400,
        content={"error": "Failed to read request body"}
      )

  async def dispatch(self, request: Request, call_next):
    """
    Check request size and reject if too large.

    SECURITY: Validates both Content-Length and chunked/streaming bodies.

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
          raise ValueError("Negative Content-Length")

        if content_length_int > self.max_size:
          return self._reject_too_large(content_length_int, client_ip, request)

      except ValueError:
        logger.warning(f"Invalid Content-Length header: {content_length}")
        content_length = None

    if request.method in ("POST", "PUT", "PATCH") and not content_length:
      result = await self._read_streaming_body(request, client_ip)
      if result is not None:
        return result

    response = await call_next(request)
    return response
