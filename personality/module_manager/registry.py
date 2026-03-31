"""
────────────────────────────────────
Server Nexe
Author: Jordi Goy 
Location: personality/module_manager/registry.py
Description: Central registry of loaded modules. Indexes modules, endpoints, metadata and

www.jgoy.net · https://server-nexe.org
────────────────────────────────────
"""

import threading
from datetime import datetime, timezone
from typing import Dict, List, Optional, Any

from personality.data.models import EndpointInfo, ModuleRegistration

from personality._logger import get_logger
logger = get_logger(__name__)

class ModuleRegistry:
  """
  Central registry for loaded modules.
  
  Maintains an updated index of all modules, their endpoints
  and metadata to facilitate discovery and coordination.
  """
  
  def __init__(self, i18n_manager=None):
    """
    Initialize module registry.
    
    Args:
      i18n_manager: Optional I18nManager for translations
    """
    self.i18n = i18n_manager
    self._modules: Dict[str, ModuleRegistration] = {}
    self._endpoints: Dict[str, EndpointInfo] = {}
    self._lock = threading.RLock()
  
  def _get_message(self, key: str, **kwargs) -> str:
    """Get translated message or fallback"""
    if self.i18n:
      return self.i18n.t(key, **kwargs)
    
    fallbacks = {
      'registry.module_registered': f"Module '{kwargs.get('name', 'unknown')}' registered in system",
      'registry.module_unregistered': f"Module '{kwargs.get('name', 'unknown')}' unregistered from system",
      'registry.endpoint_discovered': f"Endpoint discovered: {kwargs.get('method', 'unknown')} {kwargs.get('path', 'unknown')} ({kwargs.get('module', 'unknown')})",
      'registry.endpoints_indexed': f"{kwargs.get('count', 0)} endpoints indexed for {kwargs.get('module', 'unknown')}",
      'registry.metadata_extracted': f"Metadata extracted from manifest for {kwargs.get('module', 'unknown')}",
      'registry.dependencies_resolved': f"Dependencies resolved for {kwargs.get('module', 'unknown')}: {kwargs.get('deps', 'none')}",
      'registry.openapi_exported': f"OpenAPI specification exported with {kwargs.get('endpoints', 0)} endpoints"
    }
    
    return fallbacks.get(key, key)
  
  def register_module(self, name: str, instance: Any, manifest: Dict[str, Any]) -> bool:
    """
    Register a module in the system.
    
    Args:
      name: Unique module name
      instance: Loaded module instance
      manifest: Module TOML manifest
      
    Returns:
      True if registered successfully
    """
    with self._lock:
      if name in self._modules:
        logger.debug("Module '%s' already registered, skipping", name)
        return False
      
      registration = ModuleRegistration(
        name=name,
        instance=instance,
        manifest=manifest,
        registration_time=datetime.now(timezone.utc)
      )
      
      self._extract_manifest_data(registration)
      
      self._discover_endpoints(registration)
      
      self._modules[name] = registration
      
      for endpoint in registration.endpoints:
        endpoint_key = f"{endpoint.method}:{endpoint.path}"
        self._endpoints[endpoint_key] = endpoint
      
      msg = self._get_message('registry.module_registered', name=name)
      logger.info(msg, component="registry", module=name)
        
      if registration.endpoints:
        msg = self._get_message('registry.endpoints_indexed', 
                   count=len(registration.endpoints), module=name)
        logger.debug(msg, component="registry")
      
      return True
  
  def unregister_module(self, name: str) -> bool:
    """
    Unregister a module from the system.
    
    Args:
      name: Module name to unregister
      
    Returns:
      True if unregistered successfully
    """
    with self._lock:
      if name not in self._modules:
        return False
      
      registration = self._modules[name]
      
      for endpoint in registration.endpoints:
        endpoint_key = f"{endpoint.method}:{endpoint.path}"
        self._endpoints.pop(endpoint_key, None)
      
      del self._modules[name]
      
      msg = self._get_message('registry.module_unregistered', name=name)
      logger.info(msg, component="registry", module=name)
      
      return True
  
  def _extract_manifest_data(self, registration: ModuleRegistration) -> None:
    """Extract data from TOML manifest"""
    manifest = registration.manifest
    
    module_section = manifest.get('module', {})
    registration.metadata = {
      'version': module_section.get('version', '1.0.0'),
      'description': module_section.get('description', ''),
      'category': module_section.get('category', 'general'),
      'enabled': module_section.get('enabled', True)
    }
    
    api_section = manifest.get('api', {})
    registration.api_prefix = api_section.get('prefix', f'/api/{registration.name}')

    module_endpoints = module_section.get('endpoints', {})
    ui_path = module_endpoints.get('ui_path')

    if ui_path:
      registration.ui_route = ui_path
    else:
      ui_section = manifest.get('ui', {})
      if ui_section.get('enabled', False):
        registration.ui_route = ui_section.get('route', f'/moduls/{registration.name}')
      else:
        module_capabilities = module_section.get('capabilities', {})
        if module_capabilities.get('has_ui', False):
          registration.ui_route = f'/ui-control/{registration.name}'
    
    deps_section = manifest.get('dependencies', {})
    registration.dependencies = set(deps_section.get('internal', []))
    registration.provides = set(deps_section.get('provides', []))
    
    msg = self._get_message('registry.metadata_extracted', module=registration.name)
    logger.debug(msg, component="registry")
  
  def _discover_endpoints(self, registration: ModuleRegistration) -> None:
    """Discover API endpoints from module"""
    instance = registration.instance

    routers_to_scan = []

    if hasattr(instance, 'router'):
      routers_to_scan.append(('router', instance.router))

    if hasattr(instance, 'router_public'):
      routers_to_scan.append(('router_public', instance.router_public))
    if hasattr(instance, 'router_admin'):
      routers_to_scan.append(('router_admin', instance.router_admin))
    if hasattr(instance, 'router_ui'):
      routers_to_scan.append(('router_ui', instance.router_ui))

    for router_name, router in routers_to_scan:
      for route in router.routes:
        if hasattr(route, 'methods') and hasattr(route, 'path'):
          for method in route.methods:
            if method in ['GET', 'POST', 'PUT', 'DELETE', 'PATCH']:
              endpoint = EndpointInfo(
                path=route.path,
                method=method,
                function=route.endpoint.__name__ if route.endpoint else 'unknown',
                module_name=registration.name,
                summary=getattr(route, 'summary', None),
                tags=getattr(route, 'tags', [])
              )
              registration.endpoints.append(endpoint)

              msg = self._get_message('registry.endpoint_discovered',
                         method=method, path=endpoint.path,
                         module=registration.name)
              logger.debug(msg, component="registry")
  
  def get_module(self, name: str) -> Optional[ModuleRegistration]:
    """Get module registration"""
    with self._lock:
      return self._modules.get(name)
  
  def list_modules(self) -> List[ModuleRegistration]:
    """List all registered modules"""
    with self._lock:
      return list(self._modules.values())
  
  def find_endpoint(self, method: str, path: str) -> Optional[EndpointInfo]:
    """Find a specific endpoint"""
    with self._lock:
      key = f"{method.upper()}:{path}"
      return self._endpoints.get(key)
  
  def list_endpoints(self, module_name: Optional[str] = None) -> List[EndpointInfo]:
    """List endpoints, optionally filtered by module"""
    with self._lock:
      endpoints = list(self._endpoints.values())
      
      if module_name:
        endpoints = [e for e in endpoints if e.module_name == module_name]
      
      return sorted(endpoints, key=lambda e: (e.module_name, e.path))
  
  def get_modules_by_category(self, category: str) -> List[ModuleRegistration]:
    """Get modules of a specific category"""
    with self._lock:
      return [
        reg for reg in self._modules.values()
        if reg.metadata.get('category') == category
      ]
  
  def get_modules_providing(self, capability: str) -> List[ModuleRegistration]:
    """Get modules that provide a specific capability"""
    with self._lock:
      return [
        reg for reg in self._modules.values()
        if capability in reg.provides
      ]
  
  def check_dependencies(self, module_name: str) -> Dict[str, bool]:
    """Check if all dependencies of a module are available"""
    with self._lock:
      if module_name not in self._modules:
        return {}
      
      registration = self._modules[module_name]
      dependency_status = {}
      
      for dep in registration.dependencies:
        dependency_status[dep] = dep in self._modules
      
      return dependency_status
  
  def get_registry_stats(self) -> Dict[str, Any]:
    """Get registry statistics"""
    with self._lock:
      categories = {}
      total_endpoints = len(self._endpoints)
      
      for registration in self._modules.values():
        category = registration.metadata.get('category', 'unknown')
        categories[category] = categories.get(category, 0) + 1
      
      return {
        'total_modules': len(self._modules),
        'total_endpoints': total_endpoints,
        'categories': categories,
        'modules_with_ui': len([r for r in self._modules.values() if r.ui_route]),
        'modules_with_api': len([r for r in self._modules.values() if r.endpoints])
      }
  
  def export_openapi_spec(self) -> Dict[str, Any]:
    """Export OpenAPI specification of all endpoints"""
    spec = {
      'openapi': '3.0.0',
      'info': {
        'title': 'Nexe 0.9 Modular API',
        'version': '0.9.0',
        'description': 'Auto-generated API from Nexe modular system'
      },
      'paths': {}
    }
    
    with self._lock:
      for endpoint in self._endpoints.values():
        if endpoint.path not in spec['paths']:
          spec['paths'][endpoint.path] = {}
        
        spec['paths'][endpoint.path][endpoint.method.lower()] = {
          'summary': endpoint.summary or f'{endpoint.function} ({endpoint.module_name})',
          'tags': endpoint.tags or [endpoint.module_name],
          'operationId': f'{endpoint.module_name}_{endpoint.function}',
          'responses': endpoint.responses or {'200': {'description': 'Success'}}
        }
      
      msg = self._get_message('registry.openapi_exported', endpoints=len(self._endpoints))
      logger.info(msg, component="registry")
    
    return spec
  
  def get_module_dependencies_tree(self) -> Dict[str, Dict[str, Any]]:
    """Get dependency tree for all modules"""
    with self._lock:
      tree = {}
      
      for name, registration in self._modules.items():
        tree[name] = {
          'dependencies': list(registration.dependencies),
          'provides': list(registration.provides),
          'dependents': [
            other_name for other_name, other_reg in self._modules.items()
            if name in other_reg.dependencies
          ]
        }
      
      return tree
  
  def find_modules_with_tag(self, tag: str) -> List[ModuleRegistration]:
    """Find modules that have endpoints with specific tag"""
    with self._lock:
      matching_modules = set()
      
      for endpoint in self._endpoints.values():
        if tag in endpoint.tags:
          if endpoint.module_name in self._modules:
            matching_modules.add(self._modules[endpoint.module_name])
      
      return list(matching_modules)