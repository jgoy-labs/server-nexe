"""
────────────────────────────────────
Server Nexe
Version: 0.8
Author: Jordi Goy 
Location: personality/integration/messages.py
Description: Centralized fallback message dictionary for integration system. Defines

www.jgoy.net
────────────────────────────────────
"""

FALLBACK_MESSAGES = {
  'route_manager.debug.routes_registered': 'Registered {count} routes for {module}',

  'route_manager.errors.failed_to_register': 'Error registering routes for {module}: {error}',
  'route_manager.errors.error_registering_router': 'Error registering router for {module}: {error}',
  'route_manager.errors.error_mounting_app': 'Error mounting app for {module}: {error}',
  'route_manager.errors.error_removing_routes': 'Error removing routes for {module}: {error}',

  'route_manager.warnings.route_conflict': 'Route conflict: {path} already registered by {existing_module}, skipping for {module}',

  'route_manager.info.routes_removed': 'Removed {count} routes for {module}',

  'api_integrator.info.integration_success': 'Module {module} API integrated successfully',
  'api_integrator.info.removal_success': 'Module {module} API removed successfully',

  'api_integrator.debug.no_api_components': 'Module {module} has no API components',

  'api_integrator.errors.integration_failed': 'Error integrating API for {module}: {error}',
  'api_integrator.errors.removal_failed': 'Error removing API for {module}: {error}',

  'openapi_merger.debug.spec_merged': 'OpenAPI specification merged for {module}',
  'openapi_merger.debug.spec_removed': 'OpenAPI specification removed for {module}',

  'openapi_merger.errors.merge_failed': 'Error merging OpenAPI for {module}: {error}',
  'openapi_merger.errors.removal_failed': 'Error removing OpenAPI for {module}: {error}',
}

def get_message(i18n, key: str, **kwargs) -> str:
  """
  Get translated message or fallback.

  Args:
    i18n: i18n manager (can be None)
    key: Message key
    **kwargs: Formatting arguments

  Returns:
    Formatted message
  """
  if i18n:
    return i18n.t(f"personality.{key}", **kwargs)

  template = FALLBACK_MESSAGES.get(key, key)
  try:
    return template.format(**kwargs)
  except KeyError:
    return template
