"""
────────────────────────────────────
Server Nexe
Version: 0.8
Author: Jordi Goy 
Location: core/cli/manifest.py
Description: FastAPI manifest for the Nexe Central CLI. Defines public /cli router with endpoints

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
  Return health status for the Nexe Central CLI.
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
    logger.error(
      t(
        "cli.manifest.health_error",
        "Error checking CLI health: {error}",
        error=str(e)
      )
    )
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
    logger.error(
      t(
        "cli.manifest.info_error",
        "Error getting CLI info: {error}",
        error=str(e)
      )
    )
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
    logger.error(
      t(
        "cli.manifest.list_error",
        "Error listing CLIs: {error}",
        error=str(e)
      )
    )
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
  """Return the module public router."""
  return router_public

def get_metadata():
  """Return the module metadata."""
  return MODULE_METADATA

__all__ = [
  "router_public",
  "MODULE_METADATA",
  "get_router",
  "get_metadata",
]
