"""
────────────────────────────────────
Server Nexe
Version: 0.8
Author: Jordi Goy 
Location: personality/module_manager/manifest.py
Description: FastAPI router for the ModuleManager module. Exposes REST endpoints for:

www.jgoy.net
────────────────────────────────────
"""

import logging
from pathlib import Path

from fastapi import APIRouter
from fastapi.responses import HTMLResponse, JSONResponse

from personality.i18n.resolve import t_modular

logger = logging.getLogger(__name__)

def _t_log(key: str, fallback: str, **kwargs) -> str:
  return t_modular(f"module_manager.logs.{key}", fallback, **kwargs)

router_public = APIRouter(prefix="/modules", tags=["modules"])

MODULE_PATH = Path(__file__).parent
UI_PATH = MODULE_PATH / "ui"

@router_public.get("/ui", response_class=HTMLResponse)
async def serve_modules_ui():
  """
  Serve the main ModuleManager UI page.

  Returns:
    HTMLResponse: UI HTML content
  """
  index_path = UI_PATH / "index.html"

  if not index_path.exists():
    return HTMLResponse(
      content=f"<h1>{t_modular('module_manager.ui.not_found', 'Module Manager UI not found')}</h1>",
      status_code=404
    )

  with open(index_path, 'r', encoding='utf-8') as f:
    content = f.read()

  return HTMLResponse(content=content)

@router_public.get("/health")
async def module_manager_health():
  """
  Health check for the ModuleManager module.

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
    logger.error(
      _t_log(
        "health_failed",
        "Health check failed: {error}",
        error=str(e),
      )
    )
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
  Return information about the ModuleManager module.

  Returns:
    {"name": "module_manager", "version": "...", ...}
  """
  try:
    from . import __version__

    return JSONResponse(content={
      "name": "module_manager",
      "version": __version__,
      "description": t_modular(
        "module_manager.info.description",
        "Centralized management system for Nexe 0.8 modules"
      ),
      "features": [
        t_modular("module_manager.info.feature_auto_discovery", "Module auto-discovery"),
        t_modular("module_manager.info.feature_lifecycle", "Lifecycle management"),
        t_modular("module_manager.info.feature_registry", "Centralized registry"),
        t_modular("module_manager.info.feature_config_validation", "Configuration validation"),
        t_modular("module_manager.info.feature_ui", "Web management UI"),
      ],
      "path": str(MODULE_PATH),
      "ui_available": UI_PATH.exists()
    })

  except Exception as e:
    logger.error(
      _t_log(
        "info_failed",
        "Error getting module info: {error}",
        error=str(e),
      )
    )
    return JSONResponse(
      content={"error": str(e)},
      status_code=500
    )

@router_public.get("/list")
async def list_registered_modules():
  """
  Return the list of registered modules.

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
    logger.error(
      _t_log(
        "list_failed",
        "Error listing modules: {error}",
        error=str(e),
      )
    )
    return JSONResponse(
      content={"error": str(e), "modules": [], "total": 0},
      status_code=500
    )

MODULE_METADATA = {
  "name": "module_manager",
  "version": "0.8.0",
  "description": t_modular(
    "module_manager.metadata.description",
    "Centralized management system for Nexe 0.8 modules"
  ),
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
