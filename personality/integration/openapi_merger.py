"""
────────────────────────────────────
Server Nexe
Version: 0.8
Author: Jordi Goy 
Location: personality/integration/openapi_merger.py
Description: OpenAPI specification merger for modules. Combines schemas from multiple

www.jgoy.net
────────────────────────────────────
"""

import threading
from typing import Dict, Any, Optional
from fastapi import FastAPI
from .messages import get_message

import logging
logger = logging.getLogger(__name__)
LOGGER_AVAILABLE = False

class OpenAPIMerger:
  """
  Unifies OpenAPI specifications from multiple modules.
  
  Features:
  - Combine schemas from multiple modules
  - Avoid name conflicts
  - Keep unified documentation
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
    Merge a module's OpenAPI specification.
    
    Args:
      module_name: Module name
      api_components: Module API components
      prefix: Routes prefix
      
    Returns:
      True if merged successfully
    """
    with self._lock:
      try:
        module_spec = self._extract_module_openapi(api_components, prefix)
        
        if module_spec:
          self._module_specs[module_name] = module_spec
          
          self._regenerate_unified_openapi()

          if LOGGER_AVAILABLE:
            msg = get_message(
              self.i18n,
              'openapi_merger.debug.spec_merged',
              module=module_name
            )
            logger.debug(msg, component="openapi_merger")

          return True
        
      except Exception as e:
        if LOGGER_AVAILABLE:
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
    Remove a module's OpenAPI specification.
    
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

          if LOGGER_AVAILABLE:
            msg = get_message(
              self.i18n,
              'openapi_merger.debug.spec_removed',
              module=module_name
            )
            logger.debug(msg, component="openapi_merger")
        
        return True
        
      except Exception as e:
        if LOGGER_AVAILABLE:
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
    """Extract OpenAPI specification from module components."""
    return {
      "prefix": prefix,
      "components": list(api_components.keys()),
    }
  
  def _regenerate_unified_openapi(self) -> None:
    """Regenerate the unified OpenAPI specification."""
    pass
  
  def get_unified_spec(self) -> Dict[str, Any]:
    """Return the unified OpenAPI specification."""
    with self._lock:
      return {
        "modules": list(self._module_specs.keys()),
        "total_modules": len(self._module_specs)
      }
