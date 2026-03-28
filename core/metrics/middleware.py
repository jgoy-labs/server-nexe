"""
────────────────────────────────────
Server Nexe
Author: Jordi Goy 
Location: core/metrics/middleware.py
Description: Prometheus middleware per tracking HTTP requests.

www.jgoy.net · https://server-nexe.org
────────────────────────────────────
"""

import logging
import time
from typing import Callable

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response

from .registry import (
  HTTP_REQUESTS_TOTAL,
  HTTP_REQUEST_DURATION,
  HTTP_ERRORS_TOTAL,
  ACTIVE_CONNECTIONS,
  normalize_path,
)

logger = logging.getLogger(__name__)

class PrometheusMiddleware(BaseHTTPMiddleware):
  """
  Middleware for collecting Prometheus metrics from HTTP requests.

  Collected metrics:
  - core_http_requests_total: Total requests by method/path/status
  - core_http_request_duration_seconds: Latency by method/path
  - core_http_errors_total: Errors by method/path/error_type
  - core_active_connections: Active connections
  """

  EXCLUDED_PATHS = {
    "/metrics",
    "/health",
    "/favicon.ico",
    "/openapi.json",
    "/docs",
    "/redoc",
  }

  async def dispatch(
    self, request: Request, call_next: Callable
  ) -> Response:
    """
    Processes request and collects metrics.

    Args:
      request: HTTP request
      call_next: Next handler

    Returns:
      HTTP response
    """
    path = request.url.path

    if path in self.EXCLUDED_PATHS:
      return await call_next(request)

    method = request.method
    normalized_path = normalize_path(path)

    ACTIVE_CONNECTIONS.inc()

    start_time = time.perf_counter()
    status_code = 500
    error_type = None

    try:
      response = await call_next(request)
      status_code = response.status_code

      if status_code >= 400:
        error_type = self._categorize_error(status_code)
        HTTP_ERRORS_TOTAL.labels(
          method=method,
          path=normalized_path,
          error_type=error_type,
        ).inc()

      return response

    except Exception as e:
      error_type = type(e).__name__
      HTTP_ERRORS_TOTAL.labels(
        method=method,
        path=normalized_path,
        error_type=error_type,
      ).inc()
      raise

    finally:
      duration = time.perf_counter() - start_time

      HTTP_REQUESTS_TOTAL.labels(
        method=method,
        path=normalized_path,
        status=str(status_code),
      ).inc()

      HTTP_REQUEST_DURATION.labels(
        method=method,
        path=normalized_path,
      ).observe(duration)

      ACTIVE_CONNECTIONS.dec()

      if duration > 1.0:
        logger.warning(
          "slow_request",
          extra={
            "method": method,
            "path": path,
            "duration_seconds": round(duration, 3),
            "status": status_code,
          },
        )

  def _categorize_error(self, status_code: int) -> str:
    """
    Categorizes error by status code.

    Args:
      status_code: HTTP status code

    Returns:
      Error category
    """
    if status_code == 400:
      return "bad_request"
    elif status_code == 401:
      return "unauthorized"
    elif status_code == 403:
      return "forbidden"
    elif status_code == 404:
      return "not_found"
    elif status_code == 422:
      return "validation_error"
    elif status_code == 429:
      return "rate_limited"
    elif status_code >= 500:
      return "server_error"
    else:
      return f"client_error_{status_code}"

def setup_prometheus_middleware(app) -> None:
  """
  Configures the Prometheus middleware on the application.

  Args:
    app: FastAPI application
  """
  app.add_middleware(PrometheusMiddleware)
  logger.info("prometheus_middleware_enabled")