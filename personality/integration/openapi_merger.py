"""
────────────────────────────────────
Server Nexe
Author: Jordi Goy 
Location: personality/integration/openapi_merger.py
Description: Module OpenAPI specification merger. Combines schemas from multiple

www.jgoy.net · https://server-nexe.org
────────────────────────────────────
"""

import threading
from typing import Dict, Any, Optional
from fastapi import FastAPI
from .messages import get_message

from personality._logger import get_logger
logger = get_logger(__name__)

class OpenAPIMerger:
  """
  Tracks per-module OpenAPI metadata for introspection.

  NOTE (PERS-007): this class does NOT build a merged OpenAPI document.
  FastAPI generates the unified ``/openapi.json`` natively from every route
  registered on ``main_app`` (the RouteManager includes module routers /
  mounts module apps onto it), so a manual merge is unnecessary. What this
  class provides is a lightweight per-module spec registry (prefix + component
  names) exposed via :meth:`get_unified_spec` for introspection/debugging.
  """
  
  def __init__(self, main_app: FastAPI, i18n_manager=None):
    """
    Initialize the OpenAPI merger.

    Args:
      main_app: Main FastAPI application
      i18n_manager: Internationalization manager
    """
    self.main_app = main_app
    self.i18n = i18n_manager
    
    self._module_specs: Dict[str, Dict[str, Any]] = {}
    self._lock = threading.RLock()
  
  def merge_module_openapi(self, module_name: str, api_components: Dict[str, Any], 
              prefix: str) -> bool:
    """
    Merge the OpenAPI specification of a module.

    Args:
      module_name: Module name
      api_components: API components of the module
      prefix: Route prefix

    Returns:
      True if merged successfully
    """
    with self._lock:
      try:
        module_spec = self._extract_module_openapi(api_components, prefix)
        
        if module_spec:
          self._module_specs[module_name] = module_spec
          
          self._regenerate_unified_openapi()

          msg = get_message(
            self.i18n,
            'openapi_merger.debug.spec_merged',
            module=module_name
          )
          logger.debug(msg, component="openapi_merger")

          return True
        
      except Exception as e:
        msg = get_message(
          self.i18n,
          'openapi_merger.errors.merge_failed',
          module=module_name,
          error=str(e)
        )
        logger.error(msg, component="openapi_merger", exc_info=True)

      return False
  
  def remove_module_openapi(self, module_name: str) -> bool:
    """
    Remove the OpenAPI specification for a module.

    Args:
      module_name: Module name

    Returns:
      True if removed successfully
    """
    with self._lock:
      try:
        if module_name in self._module_specs:
          del self._module_specs[module_name]
          
          self._regenerate_unified_openapi()

          msg = get_message(
            self.i18n,
            'openapi_merger.debug.spec_removed',
            module=module_name
          )
          logger.debug(msg, component="openapi_merger")
        
        return True
        
      except Exception as e:
        msg = get_message(
          self.i18n,
          'openapi_merger.errors.removal_failed',
          module=module_name,
          error=str(e)
        )
        logger.error(msg, component="openapi_merger")
        return False
  
  def _extract_module_openapi(self, api_components: Dict[str, Any], 
               prefix: str) -> Optional[Dict[str, Any]]:
    """Extract the OpenAPI specification from the module components."""
    return {
      "prefix": prefix,
      "components": list(api_components.keys()),
    }
  
  def _regenerate_unified_openapi(self) -> None:
    """No-op by design.

    The unified OpenAPI document is produced by FastAPI itself from the routes
    registered on ``main_app`` — there is nothing to regenerate here. Kept as
    an explicit extension hook (and so callers/tests have a stable seam) rather
    than implying a merge step that does not exist (PERS-007).
    """
    return None
  
  def get_unified_spec(self) -> Dict[str, Any]:
    """Return the unified OpenAPI specification."""
    with self._lock:
      return {
        "modules": list(self._module_specs.keys()),
        "total_modules": len(self._module_specs)
      }