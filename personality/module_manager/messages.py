"""
────────────────────────────────────
Server Nexe
Author: Jordi Goy 
Location: personality/module_manager/messages.py
Description: Diccionari centralitzat de missatges fallback per module_manager. Defineix

www.jgoy.net · https://server-nexe.org
────────────────────────────────────
"""

FALLBACK_MESSAGES = {
  'paths.manifests_dir': 'manifests',
  'files.manifest_toml': 'manifest.toml',
  'files.module_manifest_format': '{module_name}.toml',

  'manifest.default.version': '1.0.0',
  'manifest.default.enabled': True,
  'manifest.keys.module': 'module',
  'manifest.keys.version': 'version',
  'manifest.keys.enabled': 'enabled',

  'api.integration.failed': 'Failed to integrate API for {module}: {error}',
  'api.removal.failed': 'Failed to remove API for {module}: {error}',
  'api.integrator.set': 'API integrator set for module manager',

  'init.started': 'ModuleManager initialized',
  'init.config_loaded': 'Config: {path}',
  'init.config_error': 'Error loading config: {error}',

  'discovery.starting': 'Discovering modules...',
  'discovery.completed': 'Discovery completed: {new_count} new, {total_count} total',
  'discovery.cycles_detected': 'Dependency cycles: {cycles}',

  'loading.not_found': 'Module {module} not found',
  'loading.disabled': 'Module {module} is disabled',
  'loading.dependency_failed': 'Failed to load dependency {dep} for {module}',
  'loading.loading': 'Loading module {module}...',
  'loading.loaded': 'Module {module} loaded successfully',
  'loading.error': 'Error loading {module}: {error}',

  'starting.starting': 'Starting module {module}...',
  'starting.started': 'Module {module} started successfully',
  'starting.error': 'Error starting {module}: {error}',

  'stopping.stopping': 'Stopping module {module}...',
  'stopping.stopped': 'Module {module} stopped successfully',
  'stopping.error': 'Error stopping {module}: {error}',

  'system.startup.initializing': 'Initializing system...',
  'system.startup.ready': 'System ready and operational',
  'system.shutdown.initiated': 'System shutdown initiated...',
  'system.shutdown.completed': 'System shutdown completed',
  'system.errors.critical': 'Critical system error: {error}'
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
    try:
      translated = i18n.t(key, **kwargs)
      if isinstance(translated, str) and translated != key:
        return translated
    except Exception as e:
      logging.debug("Translation failed for key '%s': %s", key, e)
      pass

  message = FALLBACK_MESSAGES.get(key, key)
  try:
    if isinstance(message, str):
      return message.format(**kwargs)
    return str(message)
  except (KeyError, ValueError):
    return str(message)