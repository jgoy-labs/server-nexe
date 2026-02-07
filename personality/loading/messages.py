"""
────────────────────────────────────
Server Nexe
Version: 0.8
Author: Jordi Goy 
Location: personality/loading/messages.py
Description: Centralized fallback message dictionary for loading system. Defines

www.jgoy.net
────────────────────────────────────
"""

FALLBACK_MESSAGES = {
  'loading.starting': 'Loading module {module}...',
  'loading.success': 'Module {module} loaded successfully',
  'loading.error': 'Error loading module {module}: {error}',
  'loading.api_file_not_found': 'API file not found for {module}. Patterns tried: {patterns}',
  'loading.api_file_found': 'API file found: {file}',
  'loading.extracting_instance': 'Extracting main instance from module {module}',
  'loading.factory_found': 'Factory function found: {factory}',
  'loading.factory_failed': 'Factory function {factory} failed: {error}',
  'loading.validating': 'Validating module {module}',
  'loading.initializing': 'Initializing module {module}',
  'loading.cleanup': 'Cleaning up resources for {module}',

  'unloading.starting': 'Unloading module {module}...',
  'unloading.success': 'Module {module} unloaded successfully',
  'unloading.error': 'Error unloading module {module}: {error}',
  'unloading.cleanup_method': 'Running cleanup method: {method}',

  'validation.instance_missing': 'Invalid module instance',
  'validation.api_router_missing': 'Required API router/app not found',
  'validation.ui_file_missing': 'Required UI file: {file}',
  'validation.dependency_missing': 'External dependency not available: {dep}',
  'validation.validation_failed': 'Validation failed for {module}:\n{errors}',

  'initialization.method_found': 'Initialization method found: {method}',
  'initialization.method_called': 'Method {method} executed for {module}',
  'initialization.method_error': 'Error executing {method}: {error}',

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

  'loader.debug.tried_patterns': 'Tried: {patterns}',
  'loader.debug.found_api_file': 'API file found: {file}',
  'loader.debug.fallback_api_file': 'Using fallback API file: {file}',
  'loader.debug.using_module_as_instance': 'Using module itself as instance for {module}',
  'loader.debug.cannot_create_spec': 'Cannot create specification for {file}',
  'loader.debug.called_method': 'Method {method} called for {module}',
  'loader.debug.cleanup_completed': 'Cleanup completed for {module}',
  'loader.debug.error_calling_method': 'Error calling {method}: {error}',
  'loader.debug.error_calling_method_unload': 'Error calling {method} during unload: {error}',
  'loader.debug.reloading_module': 'Reloading module {module}',

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
  Get translated message or fallback.

  Args:
    i18n: i18n manager (can be None)
    key: Message key
    **kwargs: Formatting arguments

  Returns:
    Formatted message
  """
  if i18n:
    return i18n.t(key, **kwargs)

  return FALLBACK_MESSAGES.get(key, key)
