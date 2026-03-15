"""
────────────────────────────────────
Server Nexe
Version: 0.8
Author: Jordi Goy 
Location: memory/memory/router.py
Description: FastAPI router per mòdul Memory.

www.jgoy.net · https://server-nexe.org
────────────────────────────────────
"""

from fastapi import APIRouter
from fastapi.responses import JSONResponse
import structlog

from .constants import MANIFEST

logger = structlog.get_logger()

router_public = APIRouter(prefix="/memory", tags=["Memory"])

@router_public.get("/health")
async def get_memory_health():
  """
  Health check del mòdul Memory.

  Returns:
    {
      "status": "healthy"|"degraded"|"unhealthy",
      "checks": [...],
      "metadata": {...}
    }
  """
  try:
    from .module import MemoryModule

    module = MemoryModule.get_instance()
    health_data = module.get_health()

    logger.debug("memory_health_check_requested", status=health_data.get("status"))

    return JSONResponse(
      content=health_data,
      status_code=200 if health_data.get("status") == "healthy" else 503
    )

  except Exception as e:
    logger.error("memory_health_check_error", error=str(e), exc_info=True)

    return JSONResponse(
      content={
        "status": "unhealthy",
        "error": str(e),
        "checks": []
      },
      status_code=503
    )

@router_public.get("/info")
async def get_memory_info():
  """
  Informació del mòdul Memory.

  Returns:
    Metadata del mòdul (manifest)
  """
  return {
    "module": "Memory",
    "manifest": MANIFEST,
    "endpoints": [
      "/memory/health",
      "/memory/info"
    ]
  }

__all__ = [
  "router_public"
]