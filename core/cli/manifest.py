"""
────────────────────────────────────
Server Nexe
Version: 0.8
Author: Jordi Goy 
Location: core/cli/manifest.py
Description: Manifest FastAPI del CLI Central Nexe. Defineix router públic /cli amb endpoints

www.jgoy.net
────────────────────────────────────
"""

from pathlib import Path
from fastapi import APIRouter
from fastapi.responses import JSONResponse
import logging

from .i18n import t

logger = logging.getLogger(__name__)

router_public = APIRouter(prefix="/cli", tags=["cli-central"])

MODULE_PATH = Path(__file__).parent

@router_public.get("/health")
async def cli_health():
  """
  Retorna l'estat de salut del CLI Central Nexe.
  """
  try:
    from .router import CLIRouter
    router = CLIRouter()
    clis = router.discover_all()

    return JSONResponse(content={
      "name": "cli",
      "status": "HEALTHY",
      "version": "1.0.0",
      "metrics": {
        "total_clis": len(clis),
        "quadrants": list(set(c.quadrant for c in clis if c.quadrant))
      }
    })
  except Exception as e:
    logger.error(f"Error checking CLI health: {e}")
    return JSONResponse(
      content={
        "name": "cli",
        "status": "UNHEALTHY",
        "error": str(e)
      },
      status_code=500
    )

@router_public.get("/info")
async def cli_info():
  """
  Retorna informació del CLI Central Nexe.
  """
  try:
    from .router import CLIRouter
    router = CLIRouter()
    clis = router.discover_all()

    return JSONResponse(content={
      "name": "cli",
      "version": "1.0.0",
      "description": t(
        "cli.manifest.description",
        "CLI Central Nexe - Module CLI Orchestrator"
      ),
      "features": [
        t(
          "cli.manifest.features.discovery",
          "Dynamic CLI discovery via manifest.toml"
        ),
        t(
          "cli.manifest.features.subprocess",
          "Subprocess execution for isolation"
        ),
        t(
          "cli.manifest.features.offline",
          "Offline mode support"
        ),
        t(
          "cli.manifest.features.ui",
          "Web UI at /ui-control/clis"
        ),
        t(
          "cli.manifest.features.api",
          "API at /ui-control/api/clis"
        ),
      ],
      "path": str(MODULE_PATH),
      "clis_available": len(clis),
      "cli_list": [c.alias for c in clis],
      "ui_path": "/ui-control/clis",
      "api_path": "/ui-control/api/clis"
    })
  except Exception as e:
    logger.error(f"Error getting CLI info: {e}")
    return JSONResponse(
      content={"error": str(e)},
      status_code=500
    )

@router_public.get("/list")
async def cli_list():
  """
  Retorna la llista de CLIs disponibles (redirect a /ui-control/api/clis).
  """
  try:
    from .router import CLIRouter
    router = CLIRouter()
    return JSONResponse(content=router.get_all_clis_dict())
  except Exception as e:
    logger.error(f"Error listing CLIs: {e}")
    return JSONResponse(
      content={"error": str(e)},
      status_code=500
    )

MODULE_METADATA = {
  "name": "cli",
  "version": "1.0.0",
  "description": t(
    "cli.manifest.description",
    "CLI Central Nexe - Module CLI Orchestrator"
  ),
  "router": router_public,
  "prefix": "/cli",
  "tags": ["cli", "terminal", "commands"],
  "ui_available": True,
  "ui_path": "/ui-control/clis",
  "quadrant": "core",
  "type": "core"
}

def get_router():
  """Retorna el router públic del mòdul"""
  return router_public

def get_metadata():
  """Retorna la metadata del mòdul"""
  return MODULE_METADATA

__all__ = [
  "router_public",
  "MODULE_METADATA",
  "get_router",
  "get_metadata",
]
