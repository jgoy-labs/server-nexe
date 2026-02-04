"""
────────────────────────────────────
Server Nexe
Version: 0.8
Author: Jordi Goy 
Location: personality/loading/patterns.py
Description: Patrons de cerca i convencions de noms per Module Loader. Defineix prioritats

www.jgoy.net
────────────────────────────────────
"""

from .messages import get_message

class LoaderPatterns:
  """Gestiona patrons de cerca de fitxers i convencions de noms"""

  def __init__(self, i18n=None):
    self.i18n = i18n

  def get_api_file_patterns(self) -> list:
    """Retorna patrons de cerca de fitxers API en ordre de prioritat"""
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
    """Retorna llista de mètodes d'inicialització possibles"""
    return [
      get_message(self.i18n, 'loader.init_methods.init'),
      get_message(self.i18n, 'loader.init_methods.initialize'),
      get_message(self.i18n, 'loader.init_methods.setup'),
      get_message(self.i18n, 'loader.init_methods.start_up'),
      get_message(self.i18n, 'loader.init_methods.on_load')
    ]

  def get_cleanup_methods(self) -> list:
    """Retorna llista de mètodes de neteja possibles"""
    return [
      get_message(self.i18n, 'loader.cleanup_methods.cleanup'),
      get_message(self.i18n, 'loader.cleanup_methods.shutdown'),
      get_message(self.i18n, 'loader.cleanup_methods.teardown'),
      get_message(self.i18n, 'loader.cleanup_methods.dispose'),
      get_message(self.i18n, 'loader.cleanup_methods.on_unload')
    ]

  def get_factory_functions(self) -> list:
    """Retorna llista de factory functions possibles"""
    return [
      get_message(self.i18n, 'loader.factory_functions.create_module'),
      get_message(self.i18n, 'loader.factory_functions.create_app'),
      get_message(self.i18n, 'loader.factory_functions.create'),
      get_message(self.i18n, 'loader.factory_functions.init')
    ]

  def get_common_attributes(self) -> list:
    """Retorna llista d'atributs comuns per buscar instàncies"""
    return [
      get_message(self.i18n, 'loader.common_attributes.app'),
      get_message(self.i18n, 'loader.common_attributes.router'),
      get_message(self.i18n, 'loader.common_attributes.api'),
      get_message(self.i18n, 'loader.common_attributes.module'),
      get_message(self.i18n, 'loader.common_attributes.instance'),
      get_message(self.i18n, 'loader.common_attributes.main')
    ]

  def get_priority_keywords(self) -> list:
    """Retorna keywords de prioritat per detectar classes principals"""
    return [
      get_message(self.i18n, 'loader.common_attributes.module'),
      get_message(self.i18n, 'loader.common_attributes.api'),
      get_message(self.i18n, 'loader.common_attributes.app'),
      'service', 'handler', 'manager'
    ]

  def get_ignore_prefixes(self) -> tuple:
    """Retorna prefixos de fitxers a ignorar"""
    return (
      get_message(self.i18n, 'loader.ignore_prefixes.test'),
      get_message(self.i18n, 'loader.ignore_prefixes.underscore'),
      get_message(self.i18n, 'loader.ignore_prefixes.dot')
    )

  def get_python_extension(self) -> str:
    """Retorna extensió de fitxers Python"""
    return get_message(self.i18n, 'loader.file_extensions.python')

  def get_module_name_prefix(self, module_name: str, file_id: int) -> str:
    """Genera prefix únic per nom de mòdul"""
    return get_message(self.i18n, 'loader.module_name_prefix',
             module_name=module_name, id=file_id)