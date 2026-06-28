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

@router_public.get("/ui", response_class=HTMLResponse, operation_id="serve_modules_ui")
async def serve_modules_ui():
  """
  Serve the main ModuleManager UI page.

  Returns:
    HTMLResponse: HTML content of the UI
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

@router_public.get("/health", response_model=dict, operation_id="module_manager_health")
async def module_manager_health():
  """
  Health check for the ModuleManager module.

  Returns:
    {"name": "module_manager", "status": "HEALTHY|UNHEALTHY", ...}
  """
  try:
    from . import __version__
    # Availability probe: importing the class confirms the package can load.
    from .module_manager import ModuleManager  # noqa: F401

    return JSONResponse(content={
      "name": "module_manager",
      "status": "HEALTHY",
      "version": __version__,
      "checks": {
        "module_manager_available": True,
        "ui_available": UI_PATH.exists()
      }
    })

  except Exception:
    # MC-132: la traça completa va NOMÉS al log intern; el cos de la resposta
    # mai retorna str(e) (evita info-disclosure d'estructura interna sense auth).
    logger.exception("Health check failed")
    return JSONResponse(
      content={
        "name": "module_manager",
        "status": "UNHEALTHY",
        "error": "internal error"
      },
      status_code=500
    )

@router_public.get("/info", response_model=dict, operation_id="module_manager_info")
async def module_manager_info():
  """
  Return information about the ModuleManager module.

  Returns:
    {"name": "module_manager", "version": "...", ...}
  """
  try:
    from . import __version__

    return JSONResponse(content={
      "name": "module_manager",
      "version": __version__,
      "description": "Centralized module management system for server-nexe",
      "features": [
        "Auto-discovery of modules",
        "Lifecycle management",
        "Centralized registry",
        "Configuration validation",
        "Management web UI"
      ],
      # MC-132: "location" relativa (no la ruta absoluta del filesystem) per no
      # filtrar l'estructura interna de directoris a un endpoint sense auth.
      "location": "personality/module_manager/",
      "ui_available": UI_PATH.exists()
    })

  except Exception:
    logger.exception("Error getting module info")
    return JSONResponse(
      content={"error": "internal error"},
      status_code=500
    )

@router_public.get("/list", response_model=dict, operation_id="list_registered_modules")
async def list_registered_modules():
  """
  Return the list of registered modules.

  Returns:
    {"modules": [...], "total": N}
  """
  try:
    from .registry import ModuleRegistry

    registry = ModuleRegistry()
    # B133: list_modules() is the real API (returns List[ModuleRegistration]);
    # get_all_modules() never existed and would raise AttributeError.
    modules = registry.list_modules()

    module_list = []
    for reg in modules:
      module_list.append({
        "name": reg.name,
        "status": getattr(reg, 'status', 'unknown'),
        "version": getattr(reg, 'version', 'unknown'),
        # MC-132: només el nom del directori, no la ruta absoluta del filesystem.
        "path": Path(str(getattr(reg, 'path', ''))).name,
      })

    return JSONResponse(content={
      "modules": module_list,
      "total": len(module_list)
    })

  except Exception:
    logger.exception("Error listing modules")
    return JSONResponse(
      content={"error": "internal error", "modules": [], "total": 0},
      status_code=500
    )

MODULE_METADATA = {
  "name": "module_manager",
  "version": "0.9.1",
  "description": "Centralized module management system for server-nexe",
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