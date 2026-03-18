"""
────────────────────────────────────
Server Nexe
Version: 0.8
Author: Jordi Goy 
Location: personality/loading/messages.py
Description: Diccionari centralitzat de missatges fallback per sistema loading. Defineix

www.jgoy.net · https://server-nexe.org
────────────────────────────────────
"""

FALLBACK_MESSAGES = {
  'loading.starting': 'Carregant mòdul {module}...',
  'loading.success': 'Mòdul {module} carregat correctament',
  'loading.error': 'Error carregant mòdul {module}: {error}',
  'loading.api_file_not_found': 'Fitxer d\'API no trobat per {module}. Patrons provats: {patterns}',
  'loading.api_file_found': 'Fitxer d\'API trobat: {file}',
  'loading.extracting_instance': 'Extraient instància principal del mòdul {module}',
  'loading.factory_found': 'Factory function trobada: {factory}',
  'loading.factory_failed': 'Factory function {factory} ha fallat: {error}',
  'loading.validating': 'Validant mòdul {module}',
  'loading.initializing': 'Inicialitzant mòdul {module}',
  'loading.cleanup': 'Netejant recursos per {module}',

  'unloading.starting': 'Descarregant mòdul {module}...',
  'unloading.success': 'Mòdul {module} descarregat correctament',
  'unloading.error': 'Error descarregant mòdul {module}: {error}',
  'unloading.cleanup_method': 'Executant mètode de neteja: {method}',

  'validation.instance_missing': 'Instància del mòdul no vàlida',
  'validation.api_router_missing': 'Router/app d\'API requerit però no trobat',
  'validation.ui_file_missing': 'Fitxer d\'UI requerit: {file}',
  'validation.dependency_missing': 'Dependència externa no disponible: {dep}',
  'validation.validation_failed': 'Validació fallida per {module}:\n{errors}',

  'initialization.method_found': 'Mètode d\'inicialització trobat: {method}',
  'initialization.method_called': 'Mètode {method} executat per {module}',
  'initialization.method_error': 'Error executant {method}: {error}',

  'loader.patterns.api_module': 'api_{module_name}.py',
  'loader.patterns.api_generic': 'api.py',
  'loader.patterns.main': 'main.py',
  'loader.patterns.init': '__init__.py',
  'loader.patterns.module_name': '{module_name}.py',
  'loader.patterns.module_generic': 'module.py',
  'loader.patterns.app': 'app.py',

  'loader.file_extensions.python': '.py',
  'loader.ignore_prefixes.test': 'test_',
  'loader.ignore_prefixes.underscore': '_',
  'loader.ignore_prefixes.dot': '.',
  'loader.ignore_files.setup': 'setup',

  'loader.debug.tried_patterns': 'Provats: {patterns}',
  'loader.debug.found_api_file': 'Fitxer d\'API trobat: {file}',
  'loader.debug.fallback_api_file': 'Usant fitxer d\'API alternatiu: {file}',
  'loader.debug.using_module_as_instance': 'Usant el mòdul mateix com a instància per {module}',
  'loader.debug.cannot_create_spec': 'No es pot crear especificació per {file}',
  'loader.debug.called_method': 'Mètode {method} cridat per {module}',
  'loader.debug.cleanup_completed': 'Neteja de recursos completada per {module}',
  'loader.debug.error_calling_method': 'Error cridant {method}: {error}',
  'loader.debug.error_calling_method_unload': 'Error cridant {method} durant la descàrrega: {error}',
  'loader.debug.reloading_module': 'Recarregant mòdul {module}',

  'loader.module_name_prefix': 'module_{module_name}_{id}',

  'loader.init_methods.init': 'init',
  'loader.init_methods.initialize': 'initialize',
  'loader.init_methods.setup': 'setup',
  'loader.init_methods.start_up': 'start_up',
  'loader.init_methods.on_load': 'on_load',

  'loader.cleanup_methods.cleanup': 'cleanup',
  'loader.cleanup_methods.shutdown': 'shutdown',
  'loader.cleanup_methods.teardown': 'teardown',
  'loader.cleanup_methods.dispose': 'dispose',
  'loader.cleanup_methods.on_unload': 'on_unload',

  'loader.common_attributes.app': 'app',
  'loader.common_attributes.router': 'router',
  'loader.common_attributes.api': 'api',
  'loader.common_attributes.module': 'module',
  'loader.common_attributes.instance': 'instance',
  'loader.common_attributes.main': 'main',

  'loader.factory_functions.create_module': 'create_module',
  'loader.factory_functions.create_app': 'create_app',
  'loader.factory_functions.create': 'create',
  'loader.factory_functions.init': 'init'
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
    return i18n.t(key, **kwargs)

  return FALLBACK_MESSAGES.get(key, key)