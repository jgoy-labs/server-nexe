"""
────────────────────────────────────
Server Nexe
Version: 0.8
Author: Jordi Goy 
Location: personality/integration/openapi_merger.py
Description: Fusionador d'especificacions OpenAPI de mòduls. Combina schemas de múltiples

www.jgoy.net · https://server-nexe.org
────────────────────────────────────
"""

import threading
from typing import Dict, Any, Optional
from fastapi import FastAPI
from .messages import get_message

from personality._logger import get_logger
logger = get_logger(__name__)
LOGGER_AVAILABLE = True

class OpenAPIMerger:
  """
  Unifica especificacions OpenAPI de múltiples mòduls.
  
  Funcionalitats:
  - Combina schemas de múltiples mòduls
  - Evita conflictes de noms
  - Manté documentació unificada
  """
  
  def __init__(self, main_app: FastAPI, i18n_manager=None):
    """
    Inicialitza el merger d'OpenAPI.
    
    Args:
      main_app: Aplicació FastAPI principal
      i18n_manager: Gestor d'internacionalització
    """
    self.main_app = main_app
    self.i18n = i18n_manager
    
    self._module_specs: Dict[str, Dict[str, Any]] = {}
    self._lock = threading.RLock()
  
  def merge_module_openapi(self, module_name: str, api_components: Dict[str, Any], 
              prefix: str) -> bool:
    """
    Combina l'especificació OpenAPI d'un mòdul.
    
    Args:
      module_name: Nom del mòdul
      api_components: Components d'API del mòdul
      prefix: Prefix de les rutes
      
    Returns:
      True si s'ha combinat correctament
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
    Elimina l'especificació OpenAPI d'un mòdul.
    
    Args:
      module_name: Nom del mòdul
      
    Returns:
      True si s'ha eliminat correctament
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
    """Extreu especificació OpenAPI dels components del mòdul"""
    return {
      "prefix": prefix,
      "components": list(api_components.keys()),
    }
  
  def _regenerate_unified_openapi(self) -> None:
    """Regenera l'especificació OpenAPI unificada"""
    pass
  
  def get_unified_spec(self) -> Dict[str, Any]:
    """Retorna l'especificació OpenAPI unificada"""
    with self._lock:
      return {
        "modules": list(self._module_specs.keys()),
        "total_modules": len(self._module_specs)
      }