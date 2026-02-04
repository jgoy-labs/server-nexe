"""
────────────────────────────────────
Server Nexe
Version: 0.8
Author: Jordi Goy 
Location: personality/loading/module_lifecycle.py
Description: Gestor de cicle de vida de mòduls. Controla inicialització (init, setup,

www.jgoy.net
────────────────────────────────────
"""

import inspect
import warnings
from typing import Any
from .patterns import LoaderPatterns
from .messages import get_message

import logging
logger = logging.getLogger(__name__)
LOGGER_AVAILABLE = False

class ModuleLifecycle:
  """Gestiona cicle de vida dels mòduls"""

  def __init__(self, i18n=None):
    self.i18n = i18n
    self.patterns = LoaderPatterns(i18n)

  async def initialize_module(self, instance: Any, module_name: str) -> None:
    """
    Inicialitza mòdul si té mètodes d'inicialització.

    Args:
      instance: Instància del mòdul
      module_name: Nom del mòdul
    """
    init_methods = self.patterns.get_init_methods()

    for method_name in init_methods:
      if hasattr(instance, method_name):
        method = getattr(instance, method_name)
        if callable(method):
          try:
            if inspect.iscoroutinefunction(method):
              await method()
            else:
              method()

            if LOGGER_AVAILABLE:
              msg = get_message(self.i18n, 'loader.debug.called_method',
                      method=method_name, module=module_name)
              logger.debug(msg, component="loader")
            break

          except Exception as e:
            warning_msg = get_message(
              self.i18n, 'loader.debug.error_calling_method',
              method=method_name, error=str(e)
            )
            warnings.warn(warning_msg)
            if LOGGER_AVAILABLE:
              logger.warning(warning_msg, component="loader",
                     module=module_name, method=method_name)
            continue

  async def cleanup_module(self, instance: Any, module_name: str) -> None:
    """
    Neteja recursos del mòdul abans de descarregar-lo.

    Args:
      instance: Instància del mòdul
      module_name: Nom del mòdul
    """
    cleanup_methods = self.patterns.get_cleanup_methods()

    for method_name in cleanup_methods:
      if hasattr(instance, method_name):
        method = getattr(instance, method_name)
        if callable(method):
          try:
            if inspect.iscoroutinefunction(method):
              await method()
            else:
              method()

            if LOGGER_AVAILABLE:
              msg = get_message(self.i18n, 'loader.debug.called_method',
                      method=method_name, module=module_name)
              logger.debug(msg, component="loader")
            break

          except Exception as e:
            warning_msg = get_message(
              self.i18n, 'loader.debug.error_calling_method_unload',
              method=method_name, error=str(e)
            )
            warnings.warn(warning_msg)
            if LOGGER_AVAILABLE:
              logger.warning(warning_msg, component="loader",
                     module=module_name)