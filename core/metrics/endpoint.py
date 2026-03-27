"""
────────────────────────────────────
Server Nexe
Version: 0.8
Author: Jordi Goy 
Location: core/metrics/endpoint.py
Description: /metrics endpoint to expose Prometheus metrics.

www.jgoy.net · https://server-nexe.org
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

logger = logging.getLogger(__name__)

metrics_router = APIRouter(tags=["metrics"])

@metrics_router.get(
  "/metrics",
  summary="Prometheus metrics",
  description="Exposes metrics in Prometheus format for scraping",
  response_class=Response,
  responses={
    200: {
      "description": "Prometheus metrics",
      "content": {"text/plain": {}},
    }
  },
)
async def get_metrics() -> Response:
  """
  Returns metrics in Prometheus format.

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
  summary="Metrics health check",
  description="Verifies that the metrics system is working",
)
async def metrics_health() -> Dict[str, Any]:
  """
  Metrics system health check.

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
    logger.error("metrics_health_check_failed", extra={"error": str(e)})
    return {
      "status": "unhealthy",
      "error": str(e),
    }

@metrics_router.get(
  "/metrics/json",
  summary="Metrics summary (JSON)",
  description="Summary of key metrics in JSON format",
)
async def get_metrics_json() -> Dict[str, Any]:
  """
  Returns metrics summary in JSON (for debugging).

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
  Updates module health status before exposing metrics.
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
    logger.debug("module_health_update_skipped", extra={"reason": str(e)})