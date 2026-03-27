"""
────────────────────────────────────
Server Nexe
Version: 0.8
Author: Jordi Goy 
Location: core/cli/manifest.py
Description: Manifest FastAPI del CLI Central Nexe. Defineix router públic /cli amb endpoints

www.jgoy.net · https://server-nexe.org
────────────────────────────────────
"""

from pathlib import Path
from fastapi import APIRouter
from fastapi.responses import JSONResponse
import logging

logger = logging.getLogger(__name__)

router_public = APIRouter(prefix="/cli", tags=["cli-central"])

MODULE_PATH = Path(__file__).parent

@router_public.get("/health")
async def cli_health():
  """
  Return the health status of the Nexe Central CLI.
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
  Return information about the Nexe Central CLI.
  """
  try:
    from .router import CLIRouter
    router = CLIRouter()
    clis = router.discover_all()

    return JSONResponse(content={
      "name": "cli",
      "version": "1.0.0",
      "description": "Nexe Central CLI - Module CLI orchestrator",
      "features": [
        "Dynamic CLI discovery via manifest.toml",
        "Subprocess execution for isolation",
        "Offline mode support",
        "Web UI at /ui-control/clis",
        "API at /ui-control/api/clis"
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
  Return the list of available CLIs (redirects to /ui-control/api/clis).
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
  "description": "Nexe Central CLI - Nexe 0.8 module CLI orchestrator",
  "router": router_public,
  "prefix": "/cli",
  "tags": ["cli", "terminal", "commands"],
  "ui_available": True,
  "ui_path": "/ui-control/clis",
  "quadrant": "core",
  "type": "core"
}

def get_router():
  """Return the module's public router."""
  return router_public

def get_metadata():
  """Return the module's metadata."""
  return MODULE_METADATA

__all__ = [
  "router_public",
  "MODULE_METADATA",
  "get_router",
  "get_metadata",
]