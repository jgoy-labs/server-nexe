"""
────────────────────────────────────
Server Nexe
Version: 0.8
Author: Jordi Goy 
Location: core/metrics/__init__.py
Description: Prometheus metrics module per Nexe 0.8.

www.jgoy.net
────────────────────────────────────
"""

from .registry import (
  get_metrics_registry,
  HTTP_REQUESTS_TOTAL,
  HTTP_REQUEST_DURATION,
  HTTP_ERRORS_TOTAL,
  ACTIVE_CONNECTIONS,
  MODULE_HEALTH_STATUS,
)
from .middleware import PrometheusMiddleware
from .endpoint import metrics_router

__all__ = [
  "get_metrics_registry",
  "HTTP_REQUESTS_TOTAL",
  "HTTP_REQUEST_DURATION",
  "HTTP_ERRORS_TOTAL",
  "ACTIVE_CONNECTIONS",
  "MODULE_HEALTH_STATUS",
  "PrometheusMiddleware",
  "metrics_router",
]