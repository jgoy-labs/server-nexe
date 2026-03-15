"""
────────────────────────────────────
Server Nexe
Version: 0.8
Author: Jordi Goy 
Location: personality/loading/module_extractor.py
Description: Extractor d'instàncies principals de mòduls. Cerca en ordre: factory functions

www.jgoy.net · https://server-nexe.org
────────────────────────────────────
"""

import inspect
from typing import Any
from ..data.models import ModuleInfo
from .patterns import LoaderPatterns
from .messages import get_message

import logging
logger = logging.getLogger(__name__)
LOGGER_AVAILABLE = False

class ModuleExtractor:
  """Extreu instància principal d'un mòdul"""

  def __init__(self, i18n=None):
    self.i18n = i18n
    self.patterns = LoaderPatterns(i18n)

  def extract_module_instance(self, module: Any, module_name: str,
                module_info: ModuleInfo) -> Any:
    """
    Extreu instància principal d'un mòdul carregat.

    Cerca en aquest ordre:
    1. Factory functions (create_module, create_app, etc.)
    2. Atribut amb nom del mòdul
    3. Atributs comuns (app, router, api, module)
    4. Classe principal
    5. El mòdul mateix com a fallback

    Args:
      module: Mòdul carregat
      module_name: Nom del mòdul
      module_info: Informació del mòdul

    Returns:
      Instància del mòdul
    """
    instance = self._try_factory_functions(module, module_name, module_info)
    if instance is not None:
      return instance

    instance = self._try_module_name_attribute(module, module_name)
    if instance is not None:
      return instance

    instance = self._try_common_attributes(module)
    if instance is not None:
      return instance

    instance = self._try_main_class(module, module_name)
    if instance is not None:
      return instance

    if LOGGER_AVAILABLE:
      msg = get_message(self.i18n, 'loader.debug.using_module_as_instance',
              module=module_name)
      logger.debug(msg, component="loader")
    return module

  def _try_factory_functions(self, module: Any, module_name: str,
                module_info: ModuleInfo) -> Any:
    """Cerca factory functions"""
    factory_names = self.patterns.get_factory_functions()

    for factory_name in factory_names:
      if hasattr(module, factory_name):
        factory = getattr(module, factory_name)
        if callable(factory):
          try:
            sig = inspect.signature(factory)
            if 'module_info' in sig.parameters:
              return factory(module_info)
            else:
              return factory()
          except Exception as e:
            if LOGGER_AVAILABLE:
              msg = get_message(self.i18n, 'loading.factory_failed',
                      factory=factory_name, error=str(e))
              logger.debug(msg, component="loader", module=module_name)
            continue

    return None

  def _try_module_name_attribute(self, module: Any, module_name: str) -> Any:
    """Cerca atribut amb nom del mòdul"""
    if hasattr(module, module_name):
      attr = getattr(module, module_name)
      if attr is not None:
        if inspect.isclass(attr):
          try:
            return attr()
          except (TypeError, AttributeError):
            pass
        return attr

    return None

  def _try_common_attributes(self, module: Any) -> Any:
    """Cerca atributs comuns"""
    common_attrs = self.patterns.get_common_attributes()

    for attr_name in common_attrs:
      if hasattr(module, attr_name):
        attr = getattr(module, attr_name)
        if attr is not None:
          if inspect.isclass(attr):
            try:
              return attr()
            except (TypeError, AttributeError):
              continue
          return attr

    return None

  def _try_main_class(self, module: Any, module_name: str) -> Any:
    """Cerca classe principal del mòdul"""
    module_classes = []
    for name in dir(module):
      if name.startswith('_'):
        continue

      attr = getattr(module, name)
      if inspect.isclass(attr):
        module_classes.append((name, attr))

    if not module_classes:
      return None

    priority_keywords = self.patterns.get_priority_keywords()

    for keyword in priority_keywords:
      for name, cls in module_classes:
        if keyword in name.lower():
          try:
            return cls()
          except (TypeError, AttributeError):
            continue

    try:
      return module_classes[0][1]()
    except (TypeError, AttributeError):
      pass

    return None