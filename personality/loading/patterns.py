"""
────────────────────────────────────
Server Nexe
Author: Jordi Goy
Location: personality/loading/patterns.py
Description: Search patterns and naming conventions for Module Loader. Defines priorities
             and conventions (file patterns, method/attribute names) as plain Python
             constants.

NOTE (PERS-006):
  File-name patterns ("api_{module_name}.py", "main.py", "__init__.py"…) and
  method/attribute names ("init", "cleanup", "router"…) are FUNCTIONAL
  identifiers, not user-facing strings. They must NOT be routed through i18n:
  if the i18n manager failed to resolve a key it would return the key itself
  (e.g. "loader.patterns.api_module"), and the loader would then look for files
  / methods named after the i18n key. They are therefore defined as module-level
  constants. The constructor still accepts an ``i18n`` argument for backwards
  compatibility (callers construct LoaderPatterns(i18n)), but it is unused.

www.jgoy.net · https://server-nexe.org
────────────────────────────────────
"""

# Functional constants — never translated.
API_FILE_PATTERNS = [
  'api_{module_name}.py',
  'api.py',
  'main.py',
  '__init__.py',
  '{module_name}.py',
  'module.py',
  'app.py',
]

INIT_METHODS = ['init', 'initialize', 'setup', 'start_up', 'on_load']

CLEANUP_METHODS = ['cleanup', 'shutdown', 'teardown', 'dispose', 'on_unload']

FACTORY_FUNCTIONS = ['create_module', 'create_app', 'create', 'init']

COMMON_ATTRIBUTES = ['app', 'router', 'api', 'module', 'instance', 'main']

PRIORITY_KEYWORDS = ['module', 'api', 'app', 'service', 'handler', 'manager']

IGNORE_PREFIXES = ('test_', '_', '.')

PYTHON_EXTENSION = '.py'

MODULE_NAME_PREFIX = 'module_{module_name}_{id}'


class LoaderPatterns:
  """Manages file search patterns and naming conventions."""

  def __init__(self, i18n=None):
    # i18n kept for backwards-compatible construction; intentionally unused —
    # these are functional identifiers, not translatable messages (PERS-006).
    self.i18n = i18n

  def get_api_file_patterns(self) -> list:
    """Return API file search patterns in priority order."""
    return list(API_FILE_PATTERNS)

  def get_init_methods(self) -> list:
    """Return list of possible initialization method names."""
    return list(INIT_METHODS)

  def get_cleanup_methods(self) -> list:
    """Return list of possible cleanup method names."""
    return list(CLEANUP_METHODS)

  def get_factory_functions(self) -> list:
    """Return list of possible factory functions."""
    return list(FACTORY_FUNCTIONS)

  def get_common_attributes(self) -> list:
    """Return list of common attributes to search for instances."""
    return list(COMMON_ATTRIBUTES)

  def get_priority_keywords(self) -> list:
    """Return priority keywords for detecting main classes."""
    return list(PRIORITY_KEYWORDS)

  def get_ignore_prefixes(self) -> tuple:
    """Return file prefixes to ignore."""
    return IGNORE_PREFIXES

  def get_python_extension(self) -> str:
    """Return the Python file extension."""
    return PYTHON_EXTENSION

  def get_module_name_prefix(self, module_name: str, file_id: int) -> str:
    """Generate a unique prefix for a module name."""
    return MODULE_NAME_PREFIX.format(module_name=module_name, id=file_id)
