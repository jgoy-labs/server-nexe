"""
────────────────────────────────────
Server Nexe
Version: 0.8
Author: Jordi Goy 
Location: personality/integration/route_manager.py
Description: Dynamic FastAPI route manager for modules. Registers and removes routers/apps

www.jgoy.net
────────────────────────────────────
"""

import threading
from typing import Dict, List, Any
from fastapi import FastAPI, APIRouter
from fastapi.routing import APIRoute

from .messages import get_message

import logging
logger = logging.getLogger(__name__)
LOGGER_AVAILABLE = False

class RouteManager:
  """
  Manage dynamic registration of module routes.
  
  Features:
  - Register routes without restarting the server
  - Avoid route collisions
  - Maintain a route registry per module
  - Allow dynamic route removal
  """
  
  def __init__(self, main_app: FastAPI, i18n_manager=None):
    """
    Initialize the route manager.
    
    Args:
      main_app: Main FastAPI application
      i18n_manager: I18n manager
    """
    self.main_app = main_app
    self.i18n = i18n_manager
    
    self._module_routes: Dict[str, List[Dict[str, Any]]] = {}
    self._route_conflicts: Dict[str, str] = {}
    self._lock = threading.RLock()
  
  def register_module_routes(self, module_name: str, api_component: Any, 
               prefix: str, component_type: str) -> List[Dict[str, Any]]:
    """
    Register routes for an API component.
    
    Args:
      module_name: Module name
      api_component: API component (router, app, etc.)
      prefix: Routes prefix
      component_type: Component type ('router', 'app', 'endpoints')
      
    Returns:
      List of registered routes
    """
    with self._lock:
      registered_routes = []
      
      try:
        if component_type == 'router' and isinstance(api_component, APIRouter):
          registered_routes = self._register_router_routes(
            module_name, api_component, prefix
          )
        elif component_type == 'app' and isinstance(api_component, FastAPI):
          registered_routes = self._register_app_routes(
            module_name, api_component, prefix
          )
        elif component_type == 'endpoints':
          registered_routes = self._register_endpoint_routes(
            module_name, api_component, prefix
          )
        
        if module_name not in self._module_routes:
          self._module_routes[module_name] = []
        self._module_routes[module_name].extend(registered_routes)

        if LOGGER_AVAILABLE:
          msg = get_message(
            self.i18n,
            'route_manager.debug.routes_registered',
            count=len(registered_routes),
            module=module_name
          )
          logger.debug(msg, component="route_manager")
        
      except Exception as e:
        if LOGGER_AVAILABLE:
          msg = get_message(
            self.i18n,
            'route_manager.errors.failed_to_register',
            module=module_name,
            error=str(e)
          )
          logger.error(msg, component="route_manager", exc_info=True)
      
      return registered_routes
  
  def _register_router_routes(self, module_name: str, router: APIRouter, 
               prefix: str) -> List[Dict[str, Any]]:
    """Register routes from an APIRouter."""
    registered_routes = []
    
    try:
      prefixed_router = APIRouter(prefix=prefix)
      
      for route in router.routes:
        if isinstance(route, APIRoute):
          full_path = f"{prefix}{route.path}"
          if self._check_route_conflict(full_path, module_name):
            continue
          
          prefixed_router.routes.append(route)
          
          route_info = {
            'path': full_path,
            'methods': list(route.methods),
            'name': route.name,
            'module': module_name
          }
          registered_routes.append(route_info)
          
          self._route_conflicts[full_path] = module_name
      
      self.main_app.include_router(prefixed_router)

    except Exception as e:
      if LOGGER_AVAILABLE:
        msg = get_message(
          self.i18n,
          'route_manager.errors.error_registering_router',
          module=module_name,
          error=str(e)
        )
        logger.error(msg, component="route_manager")
    
    return registered_routes
  
  def _register_app_routes(self, module_name: str, app: FastAPI, 
              prefix: str) -> List[Dict[str, Any]]:
    """Register routes from a FastAPI app."""
    registered_routes = []
    
    try:
      self.main_app.mount(prefix, app)
      
      for route in app.routes:
        if isinstance(route, APIRoute):
          full_path = f"{prefix}{route.path}"
          route_info = {
            'path': full_path,
            'methods': list(route.methods),
            'name': route.name,
            'module': module_name,
            'mounted': True
          }
          registered_routes.append(route_info)
          self._route_conflicts[full_path] = module_name

    except Exception as e:
      if LOGGER_AVAILABLE:
        msg = get_message(
          self.i18n,
          'route_manager.errors.error_mounting_app',
          module=module_name,
          error=str(e)
        )
        logger.error(msg, component="route_manager")
    
    return registered_routes
  
  def _register_endpoint_routes(self, module_name: str, endpoints: List[Any], 
                prefix: str) -> List[Dict[str, Any]]:
    """Register individual endpoints."""
    registered_routes = []
    
    return registered_routes
  
  def _check_route_conflict(self, path: str, module_name: str) -> bool:
    """
    Check for route conflicts.
    
    Args:
      path: Route path
      module_name: Module name
      
    Returns:
      True if there is a conflict
    """
    if path in self._route_conflicts:
      existing_module = self._route_conflicts[path]
      if LOGGER_AVAILABLE:
        msg = get_message(
          self.i18n,
          'route_manager.warnings.route_conflict',
          path=path,
          existing_module=existing_module,
          module=module_name
        )
        logger.warning(msg, component="route_manager")
      return True
    return False
  
  def remove_module_routes(self, module_name: str) -> int:
    """
    Remove all routes for a module.
    
    Args:
      module_name: Module name
      
    Returns:
      Number of routes removed
    """
    with self._lock:
      if module_name not in self._module_routes:
        return 0
      
      routes_to_remove = self._module_routes[module_name]
      removed_count = 0
      
      try:
        for route_info in routes_to_remove:
          path = route_info['path']
          if path in self._route_conflicts:
            del self._route_conflicts[path]
            removed_count += 1
        
        del self._module_routes[module_name]
        
        if LOGGER_AVAILABLE:
          msg = get_message(
            self.i18n,
            'route_manager.info.routes_removed',
            count=removed_count,
            module=module_name
          )
          logger.info(msg, component="route_manager")
        
      except Exception as e:
        if LOGGER_AVAILABLE:
          msg = get_message(
            self.i18n,
            'route_manager.errors.error_removing_routes',
            module=module_name,
            error=str(e)
          )
          logger.error(msg, component="route_manager")
      
      return removed_count
  
  def get_all_registered_routes(self) -> Dict[str, List[Dict[str, Any]]]:
    """Return all registered routes by module."""
    with self._lock:
      return self._module_routes.copy()
  
  def get_route_conflicts(self) -> Dict[str, str]:
    """Return route conflict map."""
    with self._lock:
      return self._route_conflicts.copy()
