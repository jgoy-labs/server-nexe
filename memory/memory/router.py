"""
────────────────────────────────────
Server Nexe
Author: Jordi Goy 
Location: memory/memory/router.py
Description: FastAPI router for the Memory module.

www.jgoy.net · https://server-nexe.org
────────────────────────────────────
"""

from fastapi import APIRouter, Depends
from fastapi.responses import JSONResponse
import structlog

from plugins.security.core.auth_dependencies import require_api_key

from .constants import MANIFEST

logger = structlog.get_logger()

router_public = APIRouter(prefix="/memory", tags=["Memory"])

@router_public.get("/health", dependencies=[Depends(require_api_key)])
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

@router_public.get("/info", dependencies=[Depends(require_api_key)])
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
      "/memory/info",
      "/memory/stats/{user_id}",
      "/memory/profile/{user_id}",
    ]
  }

@router_public.get("/stats/{user_id}", dependencies=[Depends(require_api_key)])
async def get_memory_stats(user_id: str):
  """Get memory statistics for a user via MemoryService."""
  try:
    from .module import get_memory_service
    svc = get_memory_service()
    if not svc:
      return JSONResponse(content={"error": "MemoryService not initialized"}, status_code=503)
    stats = await svc.stats(user_id)
    return stats.model_dump()
  except Exception as e:
    logger.error("memory_stats_error", error=str(e), exc_info=True)
    return JSONResponse(content={"error": str(e)}, status_code=500)

@router_public.get("/profile/{user_id}", dependencies=[Depends(require_api_key)])
async def get_memory_profile(user_id: str):
  """Get profile for a user via MemoryService."""
  try:
    from .module import get_memory_service
    svc = get_memory_service()
    if not svc:
      return JSONResponse(content={"error": "MemoryService not initialized"}, status_code=503)
    profile = await svc.get_profile(user_id)
    return profile
  except Exception as e:
    logger.error("memory_profile_error", error=str(e), exc_info=True)
    return JSONResponse(content={"error": str(e)}, status_code=500)

__all__ = [
  "router_public"
]