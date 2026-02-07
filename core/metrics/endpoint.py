"""
────────────────────────────────────
Server Nexe
Version: 0.8
Author: Jordi Goy 
Location: core/metrics/endpoint.py
Description: /metrics endpoint to expose Prometheus metrics.

www.jgoy.net
────────────────────────────────────
"""

import logging
from typing import Dict, Any

from fastapi import APIRouter, Response
from prometheus_client import (
  generate_latest,
  CONTENT_TYPE_LATEST,
  REGISTRY,
)

from .registry import set_module_health
from personality.i18n.resolve import t_modular

logger = logging.getLogger(__name__)

def _t(key: str, fallback: str, **kwargs) -> str:
  return t_modular(f"core_metrics.logs.{key}", fallback, **kwargs)

metrics_router = APIRouter(tags=["metrics"])

@metrics_router.get(
  "/metrics",
  summary=t_modular(
    "core_metrics.endpoint.prometheus_summary",
    "Prometheus metrics"
  ),
  description=t_modular(
    "core_metrics.endpoint.prometheus_description",
    "Expose metrics in Prometheus format for scraping"
  ),
  response_class=Response,
  responses={
    200: {
      "description": t_modular(
        "core_metrics.endpoint.prometheus_response_desc",
        "Prometheus metrics"
      ),
      "content": {"text/plain": {}},
    }
  },
)
async def get_metrics() -> Response:
  """
  Return metrics in Prometheus format.

  Returns:
    Response with text/plain metrics
  """
  await _update_module_health()

  metrics_output = generate_latest(REGISTRY)

  return Response(
    content=metrics_output,
    media_type=CONTENT_TYPE_LATEST,
  )

@metrics_router.get(
  "/metrics/health",
  summary=t_modular(
    "core_metrics.endpoint.health_summary",
    "Metrics health check"
  ),
  description=t_modular(
    "core_metrics.endpoint.health_description",
    "Verify the metrics system is working"
  ),
)
async def metrics_health() -> Dict[str, Any]:
  """
  Health check for the metrics system.

  Returns:
    Dict with system status
  """
  try:
    metrics_output = generate_latest(REGISTRY)
    metrics_size = len(metrics_output)

    return {
      "status": "healthy",
      "metrics_size_bytes": metrics_size,
      "registry": "prometheus_client",
    }
  except Exception as e:
    logger.error(_t(
      "health_check_failed",
      "Metrics health check failed: {error}",
      error=str(e)
    ))
    return {
      "status": "unhealthy",
      "error": str(e),
    }

@metrics_router.get(
  "/metrics/json",
  summary=t_modular(
    "core_metrics.endpoint.json_summary",
    "Metrics summary (JSON)"
  ),
  description=t_modular(
    "core_metrics.endpoint.json_description",
    "Summary of key metrics in JSON format"
  ),
)
async def get_metrics_json() -> Dict[str, Any]:
  """
  Return a metrics summary in JSON (for debugging).

  Returns:
    Dict with metrics summary
  """
  from .registry import ACTIVE_CONNECTIONS

  return {
    "http": {
      "active_connections": ACTIVE_CONNECTIONS._value.get(),
      "note": "Full metrics available at /metrics in Prometheus format",
    },
    "endpoints": {
      "prometheus": "/metrics",
      "health": "/metrics/health",
      "json": "/metrics/json",
    },
  }

async def _update_module_health() -> None:
  """
  Update module health status before exposing metrics.
  """
  try:
    from personality.module_manager.module_manager import ModuleManager

    mm = ModuleManager()
    modules = mm.list_modules()

    for module_name, module_info in modules.items():
      if hasattr(module_info, "get_health"):
        try:
          health = module_info.get_health()
          status = health.get("status", "unknown")
          set_module_health(module_name, status)
        except Exception:
          set_module_health(module_name, "unhealthy")

  except ImportError:
    pass
  except Exception as e:
    logger.debug(_t(
      "module_health_update_skipped",
      "Module health update skipped: {error}",
      error=str(e)
    ))
