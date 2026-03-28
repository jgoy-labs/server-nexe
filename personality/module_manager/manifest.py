"""
────────────────────────────────────
Server Nexe
Author: Jordi Goy 
Location: personality/module_manager/manifest.py
Description: FastAPI router for the ModuleManager module. Exposes REST endpoints for:

www.jgoy.net · https://server-nexe.org
────────────────────────────────────
"""

import logging
from pathlib import Path

from fastapi import APIRouter
from fastapi.responses import HTMLResponse, JSONResponse

logger = logging.getLogger(__name__)

router_public = APIRouter(prefix="/modules", tags=["modules"])

MODULE_PATH = Path(__file__).parent
UI_PATH = MODULE_PATH / "ui"

@router_public.get("/ui", response_class=HTMLResponse)
async def serve_modules_ui():
  """
  Serveix la pàgina principal de la UI del ModuleManager.

  Returns:
    HTMLResponse: Contingut HTML de la UI
  """
  index_path = UI_PATH / "index.html"

  if not index_path.exists():
    return HTMLResponse(
      content="<h1>Module Manager UI not found</h1>",
      status_code=404
    )

  with open(index_path, 'r', encoding='utf-8') as f:
    content = f.read()

  return HTMLResponse(content=content)

@router_public.get("/health")
async def module_manager_health():
  """
  Health check del mòdul ModuleManager.

  Returns:
    {"name": "module_manager", "status": "HEALTHY|UNHEALTHY", ...}
  """
  try:
    from . import __version__
    from .module_manager import ModuleManager

    return JSONResponse(content={
      "name": "module_manager",
      "status": "HEALTHY",
      "version": __version__,
      "checks": {
        "module_manager_available": True,
        "ui_available": UI_PATH.exists()
      }
    })

  except Exception as e:
    logger.error(f"Health check failed: {e}")
    return JSONResponse(
      content={
        "name": "module_manager",
        "status": "UNHEALTHY",
        "error": str(e)
      },
      status_code=500
    )

@router_public.get("/info")
async def module_manager_info():
  """
  Retorna informació del mòdul ModuleManager.

  Returns:
    {"name": "module_manager", "version": "...", ...}
  """
  try:
    from . import __version__

    return JSONResponse(content={
      "name": "module_manager",
      "version": __version__,
      "description": "Centralized module management system for Nexe 0.8",
      "features": [
        "Auto-discovery of modules",
        "Lifecycle management",
        "Centralized registry",
        "Configuration validation",
        "Management web UI"
      ],
      "path": str(MODULE_PATH),
      "ui_available": UI_PATH.exists()
    })

  except Exception as e:
    logger.error(f"Error getting module info: {e}")
    return JSONResponse(
      content={"error": str(e)},
      status_code=500
    )

@router_public.get("/list")
async def list_registered_modules():
  """
  Retorna la llista de mòduls registrats.

  Returns:
    {"modules": [...], "total": N}
  """
  try:
    from .registry import ModuleRegistry

    registry = ModuleRegistry()
    modules = registry.get_all_modules()

    module_list = []
    for name, info in modules.items():
      module_list.append({
        "name": name,
        "status": getattr(info, 'status', 'unknown'),
        "version": getattr(info, 'version', 'unknown'),
        "path": str(getattr(info, 'path', '')),
      })

    return JSONResponse(content={
      "modules": module_list,
      "total": len(module_list)
    })

  except Exception as e:
    logger.error("Error listing modules: %s", e)
    return JSONResponse(
      content={"error": str(e), "modules": [], "total": 0},
      status_code=500
    )

MODULE_METADATA = {
  "name": "module_manager",
  "version": "0.8.5",
  "description": "Centralized module management system for Nexe 0.8",
  "router": router_public,
  "prefix": "/modules",
  "tags": ["modules", "management", "core"],
  "ui_available": True,
  "ui_path": "/modules/ui",
  "location": "personality/module_manager/",
  "type": "core"
}

def get_router():
  """Return the public router for the module."""
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