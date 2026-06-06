"""
────────────────────────────────────
Server Nexe
Location: tests/personality/loading/test_patterns.py
Description: Tests for LoaderPatterns (PERS-006). File-name patterns and
            method/attribute names are functional identifiers and must NOT be
            routed through i18n — they must be correct even when the i18n
            manager cannot resolve their keys.
────────────────────────────────────
"""

from personality.loading.patterns import LoaderPatterns


class _BrokenI18n:
  """i18n manager that returns the key itself (as the real i18n does when a
  key is missing). With the old code this leaked keys like
  'loader.patterns.api_module' into the loader."""

  def t(self, key, **kwargs):
    return key


class TestLoaderPatternsAreFunctionalConstants:
  """PERS-006: functional identifiers must not depend on i18n resolution."""

  def test_api_patterns_correct_with_broken_i18n(self):
    patterns = LoaderPatterns(_BrokenI18n())
    result = patterns.get_api_file_patterns()
    assert 'api_{module_name}.py' in result
    assert 'main.py' in result
    assert '__init__.py' in result
    # No i18n keys leaked through.
    assert not any(p.startswith('loader.') for p in result)

  def test_api_patterns_correct_without_i18n(self):
    patterns = LoaderPatterns()
    assert patterns.get_api_file_patterns()[0] == 'api_{module_name}.py'

  def test_init_methods_are_real_names(self):
    patterns = LoaderPatterns(_BrokenI18n())
    assert patterns.get_init_methods() == [
      'init', 'initialize', 'setup', 'start_up', 'on_load'
    ]

  def test_cleanup_methods_are_real_names(self):
    patterns = LoaderPatterns(_BrokenI18n())
    assert patterns.get_cleanup_methods() == [
      'cleanup', 'shutdown', 'teardown', 'dispose', 'on_unload'
    ]

  def test_factory_functions_are_real_names(self):
    patterns = LoaderPatterns(_BrokenI18n())
    assert 'create_module' in patterns.get_factory_functions()
    assert not any(f.startswith('loader.') for f in patterns.get_factory_functions())

  def test_common_attributes_are_real_names(self):
    patterns = LoaderPatterns(_BrokenI18n())
    assert patterns.get_common_attributes() == [
      'app', 'router', 'api', 'module', 'instance', 'main'
    ]

  def test_ignore_prefixes_and_extension(self):
    patterns = LoaderPatterns(_BrokenI18n())
    assert patterns.get_ignore_prefixes() == ('test_', '_', '.')
    assert patterns.get_python_extension() == '.py'

  def test_module_name_prefix_formats(self):
    patterns = LoaderPatterns(_BrokenI18n())
    assert patterns.get_module_name_prefix('mymod', 42) == 'module_mymod_42'

  def test_priority_keywords_include_functional_terms(self):
    patterns = LoaderPatterns(_BrokenI18n())
    kw = patterns.get_priority_keywords()
    assert 'service' in kw and 'handler' in kw and 'manager' in kw
    assert not any(k.startswith('loader.') for k in kw)
