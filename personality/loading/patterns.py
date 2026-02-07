"""
────────────────────────────────────
Server Nexe
Version: 0.8
Author: Jordi Goy 
Location: personality/loading/patterns.py
Description: Search patterns and naming conventions for Module Loader. Defines priorities

www.jgoy.net
────────────────────────────────────
"""

from .messages import get_message

class LoaderPatterns:
  """Manage file search patterns and naming conventions."""

  def __init__(self, i18n=None):
    self.i18n = i18n

  def get_api_file_patterns(self) -> list:
    """Return API file search patterns in priority order."""
    return [
      get_message(self.i18n, 'loader.patterns.api_module'),
      get_message(self.i18n, 'loader.patterns.api_generic'),
      get_message(self.i18n, 'loader.patterns.main'),
      get_message(self.i18n, 'loader.patterns.init'),
      get_message(self.i18n, 'loader.patterns.module_name'),
      get_message(self.i18n, 'loader.patterns.module_generic'),
      get_message(self.i18n, 'loader.patterns.app')
    ]

  def get_init_methods(self) -> list:
    """Return list of possible initialization methods."""
    return [
      get_message(self.i18n, 'loader.init_methods.init'),
      get_message(self.i18n, 'loader.init_methods.initialize'),
      get_message(self.i18n, 'loader.init_methods.setup'),
      get_message(self.i18n, 'loader.init_methods.start_up'),
      get_message(self.i18n, 'loader.init_methods.on_load')
    ]

  def get_cleanup_methods(self) -> list:
    """Return list of possible cleanup methods."""
    return [
      get_message(self.i18n, 'loader.cleanup_methods.cleanup'),
      get_message(self.i18n, 'loader.cleanup_methods.shutdown'),
      get_message(self.i18n, 'loader.cleanup_methods.teardown'),
      get_message(self.i18n, 'loader.cleanup_methods.dispose'),
      get_message(self.i18n, 'loader.cleanup_methods.on_unload')
    ]

  def get_factory_functions(self) -> list:
    """Return list of possible factory functions."""
    return [
      get_message(self.i18n, 'loader.factory_functions.create_module'),
      get_message(self.i18n, 'loader.factory_functions.create_app'),
      get_message(self.i18n, 'loader.factory_functions.create'),
      get_message(self.i18n, 'loader.factory_functions.init')
    ]

  def get_common_attributes(self) -> list:
    """Return list of common attributes to find instances."""
    return [
      get_message(self.i18n, 'loader.common_attributes.app'),
      get_message(self.i18n, 'loader.common_attributes.router'),
      get_message(self.i18n, 'loader.common_attributes.api'),
      get_message(self.i18n, 'loader.common_attributes.module'),
      get_message(self.i18n, 'loader.common_attributes.instance'),
      get_message(self.i18n, 'loader.common_attributes.main')
    ]

  def get_priority_keywords(self) -> list:
    """Return priority keywords to detect main classes."""
    return [
      get_message(self.i18n, 'loader.common_attributes.module'),
      get_message(self.i18n, 'loader.common_attributes.api'),
      get_message(self.i18n, 'loader.common_attributes.app'),
      'service', 'handler', 'manager'
    ]

  def get_ignore_prefixes(self) -> tuple:
    """Return file prefixes to ignore."""
    return (
      get_message(self.i18n, 'loader.ignore_prefixes.test'),
      get_message(self.i18n, 'loader.ignore_prefixes.underscore'),
      get_message(self.i18n, 'loader.ignore_prefixes.dot')
    )

  def get_python_extension(self) -> str:
    """Return Python file extension."""
    return get_message(self.i18n, 'loader.file_extensions.python')

  def get_module_name_prefix(self, module_name: str, file_id: int) -> str:
    """Generate unique prefix for a module name."""
    return get_message(self.i18n, 'loader.module_name_prefix',
             module_name=module_name, id=file_id)
