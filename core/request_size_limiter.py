"""
────────────────────────────────────
Server Nexe
Version: 0.8
Author: Jordi Goy 
Location: core/request_size_limiter.py
Description: Middleware per limitar mida de requests. Prevé DoS via large payloads (CWE-400).

www.jgoy.net
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

  async def dispatch(self, request: Request, call_next):
    """
    Check request size and reject if too large.

    SEGURETAT: Controla tant Content-Length com chunked/streaming.

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
          if hasattr(request.app.state, 'security_logger'):
            request.app.state.security_logger.log_request_too_large(
              size=content_length_int,
              max_size=self.max_size,
              ip_address=client_ip,
              endpoint=str(request.url.path)
            )

          logger.warning(
            f"Request rejected: size {content_length_int / (1024**2):.2f} MB "
            f"exceeds limit {self.max_size / (1024**2):.2f} MB "
            f"from {client_ip} to {request.url.path}"
          )

          return JSONResponse(
            status_code=413,
            content={
              "error": "Request Entity Too Large",
              "detail": f"Content-Length ({content_length_int}) exceeds max ({self.max_size})",
              "max_size_mb": round(self.max_size / (1024**2), 2),
            }
          )

      except ValueError:
        logger.warning(f"Invalid Content-Length header: {content_length}")
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
              f"Streaming request rejected: {body_bytes} bytes "
              f"exceeds limit {self.max_size} from {client_ip}"
            )

            return JSONResponse(
              status_code=413,
              content={
                "error": "Request Entity Too Large (streaming)",
                "detail": f"Body size ({body_bytes}) exceeds max ({self.max_size})",
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
        logger.error(f"Error reading request body: {e}")
        return JSONResponse(
          status_code=400,
          content={"error": "Failed to read request body"}
        )

    response = await call_next(request)
    return response
