"""
────────────────────────────────────
Server Nexe
Version: 0.8
Author: Jordi Goy 
Location: core/metrics/endpoint.py
Description: Endpoint /metrics per exposar mètriques Prometheus.

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

logger = logging.getLogger(__name__)

metrics_router = APIRouter(tags=["metrics"])

@metrics_router.get(
  "/metrics",
  summary="Prometheus metrics",
  description="Exposa mètriques en format Prometheus per scraping",
  response_class=Response,
  responses={
    200: {
      "description": "Mètriques Prometheus",
      "content": {"text/plain": {}},
    }
  },
)
async def get_metrics() -> Response:
  """
  Retorna mètriques en format Prometheus.

  Returns:
    Response amb mètriques text/plain
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
  description="Verifica que el sistema de mètriques funciona",
)
async def metrics_health() -> Dict[str, Any]:
  """
  Health check del sistema de mètriques.

  Returns:
    Dict amb estat del sistema
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
  description="Resum de mètriques principals en format JSON",
)
async def get_metrics_json() -> Dict[str, Any]:
  """
  Retorna resum de mètriques en JSON (per debugging).

  Returns:
    Dict amb resum de mètriques
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
  Actualitza l'estat de salut dels mòduls abans d'exposar mètriques.
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