"""
────────────────────────────────────
Server Nexe
Version: 0.8
Author: Jordi Goy 
Location: personality/integration/api_integrator.py
Description: Automatic module API integrator into the FastAPI server. Detects routers,

www.jgoy.net · https://server-nexe.org
────────────────────────────────────
"""

import inspect
import threading
from typing import Dict, Any, Optional, List
from fastapi import FastAPI, APIRouter

from ..data.models import ModuleInfo
from .route_manager import RouteManager
from .openapi_merger import OpenAPIMerger
from .messages import get_message

from personality._logger import get_logger
logger = get_logger(__name__)

class APIIntegrator:
  """
  Integra automàticament les APIs dels mòduls al servidor principal.
  
  Funcionalitats:
  - Detecta routers FastAPI en mòduls carregats
  - Registra rutes dinàmicament
  - Gestiona prefixos per evitar col·lisions
  - Unifica especificacions OpenAPI
  """
  
  def __init__(self, main_app: FastAPI, i18n_manager=None):
    """
    Inicialitza l'integrador d'APIs.
    
    Args:
      main_app: Aplicació FastAPI principal
      i18n_manager: Gestor d'internacionalització
    """
    self.main_app = main_app
    self.i18n = i18n_manager
    self.route_manager = RouteManager(main_app, i18n_manager)
    self.openapi_merger = OpenAPIMerger(main_app, i18n_manager)
    
    self._integrated_modules: Dict[str, Dict[str, Any]] = {}
    self._lock = threading.RLock()
    
    self._total_routes_registered = 0
    self._total_modules_integrated = 0
  
  def integrate_module_api(self, module_name: str, module_instance: Any,
              module_info: Optional[ModuleInfo] = None) -> bool:
    """
    Integra l'API d'un mòdul al servidor principal.

    Args:
      module_name: Nom del mòdul
      module_instance: Instància del mòdul carregat
      module_info: Informació del mòdul (opcional)

    Returns:
      True si s'ha integrat correctament
    """
    with self._lock:
      try:
        api_components = self._detect_and_validate_api(module_name, module_instance)
        if not api_components:
          return False

        api_prefix = self._determine_api_prefix(module_name, module_info)
        registered_routes = self._register_module_routes(
          module_name, api_components, api_prefix
        )

        self.openapi_merger.merge_module_openapi(
          module_name, api_components, api_prefix
        )

        self._save_integration_info(
          module_name, module_instance, api_components,
          api_prefix, registered_routes
        )

        msg = get_message(
          self.i18n,
          'api_integrator.info.integration_success',
          module=module_name
        )
        logger.info(msg, component="api_integrator",
             routes_count=len(registered_routes),
             prefix=api_prefix)

        return True

      except Exception as e:
        return self._handle_integration_error(module_name, e)

  def _detect_and_validate_api(self, module_name: str, module_instance: Any) -> Optional[Dict[str, Any]]:
    """Detecta i valida components d'API."""
    api_components = self._detect_api_components(module_instance)

    if not api_components:
      msg = get_message(
        self.i18n,
        'api_integrator.debug.no_api_components',
        module=module_name
      )
      logger.debug(msg, component="api_integrator")
      return None

    return api_components

  def _register_module_routes(self, module_name: str, api_components: Dict[str, Any],
                api_prefix: str) -> List[Dict[str, Any]]:
    """Registra rutes de tots els components d'API."""
    registered_routes = []
    for component_type, component in api_components.items():
      routes = self.route_manager.register_module_routes(
        module_name, component, api_prefix, component_type
      )
      registered_routes.extend(routes)

    return registered_routes

  def _save_integration_info(self, module_name: str, module_instance: Any,
               api_components: Dict[str, Any], api_prefix: str,
               registered_routes: List[Dict[str, Any]]) -> None:
    """Save integration info and update statistics."""
    self._integrated_modules[module_name] = {
      'instance': module_instance,
      'api_components': api_components,
      'api_prefix': api_prefix,
      'registered_routes': registered_routes,
      'route_count': len(registered_routes)
    }

    self._total_routes_registered += len(registered_routes)
    self._total_modules_integrated += 1

  def _handle_integration_error(self, module_name: str, error: Exception) -> bool:
    """Handle integration errors."""
    msg = get_message(
      self.i18n,
      'api_integrator.errors.integration_failed',
      module=module_name,
      error=str(error)
    )
    logger.error(msg, component="api_integrator", exc_info=True)
    return False

  def remove_module_api(self, module_name: str) -> bool:
    """
    Elimina l'API d'un mòdul del servidor.
    
    Args:
      module_name: Nom del mòdul
      
    Returns:
      True si s'ha eliminat correctament
    """
    with self._lock:
      try:
        if module_name not in self._integrated_modules:
          return True
        
        module_info = self._integrated_modules[module_name]
        
        removed_count = self.route_manager.remove_module_routes(module_name)
        
        self.openapi_merger.remove_module_openapi(module_name)
        
        del self._integrated_modules[module_name]
        
        self._total_routes_registered -= removed_count
        self._total_modules_integrated -= 1
        
        msg = get_message(
          self.i18n,
          'api_integrator.info.removal_success',
          module=module_name
        )
        logger.info(msg, component="api_integrator",
             routes_removed=removed_count)
        
        return True
        
      except Exception as e:
        msg = get_message(
          self.i18n,
          'api_integrator.errors.removal_failed',
          module=module_name,
          error=str(e)
        )
        logger.error(msg, component="api_integrator", exc_info=True)
        return False
  
  def _detect_api_components(self, module_instance: Any) -> Dict[str, Any]:
    """
    Detecta components d'API en un mòdul.
    
    Args:
      module_instance: Instància del mòdul
      
    Returns:
      Diccionari amb components d'API detectats
    """
    components = {}
    
    for attr_name in ['router', 'api_router', 'routes', 'app']:
      if hasattr(module_instance, attr_name):
        attr = getattr(module_instance, attr_name)
        if isinstance(attr, APIRouter):
          components['router'] = attr
          break
        elif isinstance(attr, FastAPI):
          components['app'] = attr
          break
    
    for attr_name in dir(module_instance):
      if attr_name.startswith('_'):
        continue
        
      attr = getattr(module_instance, attr_name)
      if inspect.ismethod(attr) or inspect.isfunction(attr):
        if hasattr(attr, '__annotations__') and hasattr(attr, '_fastapi_route'):
          if 'endpoints' not in components:
            components['endpoints'] = []
          components['endpoints'].append(attr)
    
    return components
  
  def _determine_api_prefix(self, module_name: str, 
              module_info: Optional[ModuleInfo] = None) -> str:
    """
    Determina el prefix d'API per un mòdul.
    
    Args:
      module_name: Nom del mòdul
      module_info: Informació del mòdul
      
    Returns:
      Prefix d'API
    """
    if module_info and module_info.manifest:
      api_config = module_info.manifest.get('api', {})
      if 'prefix' in api_config:
        return api_config['prefix']
    
    if module_info and hasattr(module_info.instance, 'api_prefix'):
      return module_info.instance.api_prefix
    
    return f"/api/{module_name}"
  
  def get_integration_stats(self) -> Dict[str, Any]:
    """Return integration statistics."""
    with self._lock:
      return {
        'total_modules_integrated': self._total_modules_integrated,
        'total_routes_registered': self._total_routes_registered,
        'integrated_modules': list(self._integrated_modules.keys()),
        'modules_details': {
          name: {
            'route_count': info['route_count'],
            'api_prefix': info['api_prefix'],
            'components': list(info['api_components'].keys())
          }
          for name, info in self._integrated_modules.items()
        }
      }
  
  def is_module_integrated(self, module_name: str) -> bool:
    """Check if a module is integrated."""
    with self._lock:
      return module_name in self._integrated_modules
  
  def get_module_routes(self, module_name: str) -> List[str]:
    """Return the routes of an integrated module."""
    with self._lock:
      if module_name in self._integrated_modules:
        return [route['path'] for route in 
            self._integrated_modules[module_name]['registered_routes']]
      return []