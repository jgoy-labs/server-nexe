"""
────────────────────────────────────
Server Nexe
Version: 0.8
Author: Jordi Goy 
Location: personality/integration/messages.py
Description: Diccionari centralitzat de missatges fallback per sistema integration. Defineix

www.jgoy.net
────────────────────────────────────
"""

FALLBACK_MESSAGES = {
  'route_manager.debug.routes_registered': 'Registrades {count} rutes per {module}',

  'route_manager.errors.failed_to_register': 'Error registrant rutes per {module}: {error}',
  'route_manager.errors.error_registering_router': 'Error registrant router per {module}: {error}',
  'route_manager.errors.error_mounting_app': 'Error muntant app per {module}: {error}',
  'route_manager.errors.error_removing_routes': 'Error eliminant rutes per {module}: {error}',

  'route_manager.warnings.route_conflict': 'Conflicte de ruta: {path} ja registrat per {existing_module}, s\'omet per {module}',

  'route_manager.info.routes_removed': 'Eliminades {count} rutes per {module}',

  'api_integrator.info.integration_success': 'Mòdul {module} API integrat correctament',
  'api_integrator.info.removal_success': 'Mòdul {module} API eliminat correctament',

  'api_integrator.debug.no_api_components': 'Mòdul {module} no té components d\'API',

  'api_integrator.errors.integration_failed': 'Error integrant API de {module}: {error}',
  'api_integrator.errors.removal_failed': 'Error eliminant API de {module}: {error}',

  'openapi_merger.debug.spec_merged': 'Especificació OpenAPI combinada per {module}',
  'openapi_merger.debug.spec_removed': 'Especificació OpenAPI eliminada per {module}',

  'openapi_merger.errors.merge_failed': 'Error combinant OpenAPI per {module}: {error}',
  'openapi_merger.errors.removal_failed': 'Error eliminant OpenAPI per {module}: {error}',
}

def get_message(i18n, key: str, **kwargs) -> str:
  """
  Obté missatge traduït o fallback.

  Args:
    i18n: Gestor i18n (pot ser None)
    key: Clau del missatge
    **kwargs: Arguments per format

  Returns:
    Missatge formatat
  """
  if i18n:
    return i18n.t(f"personality.{key}", **kwargs)

  template = FALLBACK_MESSAGES.get(key, key)
  try:
    return template.format(**kwargs)
  except KeyError:
    return template