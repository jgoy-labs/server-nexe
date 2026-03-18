"""
────────────────────────────────────
Server Nexe
Version: 0.8
Author: Jordi Goy
Location: personality/loading/loader.py
Description: Façade global per càrrega dinàmica de mòduls Nexe.

DEPRECATION NOTICE:
  This loader is maintained for backwards compatibility.
  For new code, prefer using core/loader which provides:
  - Protocol-based module validation (NexeModule)
  - manifest.toml support
  - Cleaner API

  Migration: from core.loader import ModuleLoader, bootstrap

www.jgoy.net · https://server-nexe.org
────────────────────────────────────
"""

import warnings
import traceback
from typing import Any, Optional, Dict, List

from ..data.models import ModuleInfo

from .messages import get_message
from .module_finder import ModuleFinder
from .module_importer import ModuleImporter
from .module_extractor import ModuleExtractor
from .module_validator import ModuleValidator, ModuleValidationError
from .module_lifecycle import ModuleLifecycle

from personality._logger import get_logger
logger = get_logger(__name__)
LOGGER_AVAILABLE = True


class ModuleLoader:
  """
  Global dynamic module loader for Nexe 0.8 (FAÇADE).

  Coordina tots els components especialitzats:
  - ModuleFinder: Cerca fitxers API
  - ModuleImporter: Import dinàmic
  - ModuleExtractor: Extreu instància principal
  - ModuleValidator: Valida mòduls
  - ModuleLifecycle: Gestiona init/cleanup/unload
  """

  def __init__(self, i18n_manager=None, suppress_deprecation: bool = False):
    """
    Inicialitza module loader.

    Args:
      i18n_manager: Gestor I18nManager opcional per traduccions
      suppress_deprecation: Set True to suppress deprecation warning

    Note:
      For new code, consider using core.loader.ModuleLoader instead.
    """
    if not suppress_deprecation:
      warnings.warn(
        "personality.loading.ModuleLoader is deprecated. "
        "Use core.loader.ModuleLoader for new code.",
        DeprecationWarning,
        stacklevel=2
      )

    self._loaded_modules: Dict[str, Any] = {}
    self.i18n = i18n_manager

    self.finder = ModuleFinder(i18n_manager)
    self.importer = ModuleImporter(i18n_manager)
    self.extractor = ModuleExtractor(i18n_manager)
    self.validator = ModuleValidator(i18n_manager)
    self.lifecycle = ModuleLifecycle(i18n_manager)

  async def load_module(self, module_info: ModuleInfo) -> Any:
    """
    Carrega un mòdul específic.

    Args:
      module_info: Informació del mòdul (ModuleInfo)

    Returns:
      Instància del mòdul carregat

    Raises:
      ModuleValidationError: Si el mòdul no és vàlid
      ImportError: Si hi ha errors d'import
    """
    module_name = module_info.name
    module_path = module_info.path

    if LOGGER_AVAILABLE:
      msg = get_message(self.i18n, 'loading.starting', module=module_name)
      logger.info(msg, component="loader", module=module_name)

    api_file = self.finder.find_api_file(module_path, module_name)

    if not api_file:
      tried_patterns = [
        p.format(module_name=module_name)
        for p in self.finder.patterns.get_api_file_patterns()
      ]
      error_details = get_message(
        self.i18n, 'loader.debug.tried_patterns',
        patterns=', '.join(tried_patterns)
      )

      error_msg = get_message(
        self.i18n, 'loading.api_file_not_found',
        module=module_name, patterns=error_details
      )

      if LOGGER_AVAILABLE:
        logger.error(error_msg, component="loader", module=module_name,
              patterns=tried_patterns)

      raise ImportError(error_msg)

    try:
      module = self.importer.import_module(api_file, module_name)

      module_instance = self.extractor.extract_module_instance(
        module, module_name, module_info
      )

      self.validator.validate_module(module_instance, module_info)

      await self.lifecycle.initialize_module(module_instance, module_name)

      self._loaded_modules[module_name] = module_instance

      if LOGGER_AVAILABLE:
        msg = get_message(self.i18n, 'loading.success', module=module_name)
        logger.info(msg, component="loader", module=module_name)

      return module_instance

    except (ImportError, AttributeError, ValueError, TypeError,
        IOError, ModuleValidationError) as e:
      self._cleanup_failed_load(module_name)

      error_msg = get_message(self.i18n, 'loading.error',
                  module=module_name, error=str(e))

      if LOGGER_AVAILABLE:
        logger.error(error_msg, component="loader", module=module_name,
              exc_info=True, stack_trace=traceback.format_exc())

      raise ImportError(error_msg) from e

  def _cleanup_failed_load(self, module_name: str) -> None:
    """
    Neteja recursos després d'una càrrega fallida.

    Args:
      module_name: Nom del mòdul que ha fallat
    """
    self._loaded_modules.pop(module_name, None)

    modules_removed = self.importer.cleanup_module(module_name)

    if LOGGER_AVAILABLE:
      msg = get_message(self.i18n, 'loader.debug.cleanup_completed',
              module=module_name)
      logger.debug(msg, component="loader", modules_removed=modules_removed)

  async def unload_module(self, module_name: str) -> bool:
    """
    Descarrega un mòdul del sistema.

    Args:
      module_name: Nom del mòdul a descarregar

    Returns:
      True si s'ha descarregat correctament
    """
    try:
      if module_name in self._loaded_modules:
        instance = self._loaded_modules[module_name]
        await self.lifecycle.cleanup_module(instance, module_name)

      self._loaded_modules.pop(module_name, None)

      modules_removed = self.importer.cleanup_module(module_name)

      if LOGGER_AVAILABLE:
        msg = get_message(self.i18n, 'unloading.success', module=module_name)
        logger.info(msg, component="loader", module=module_name,
             sys_modules_removed=modules_removed)

      return True

    except (ImportError, AttributeError, ValueError, TypeError, IOError) as e:
      if LOGGER_AVAILABLE:
        msg = get_message(self.i18n, 'unloading.error',
                module=module_name, error=str(e))
        logger.error(msg, component="loader", module=module_name, exc_info=True)
      return False

  def get_loaded_modules(self) -> List[str]:
    """Retorna llista de mòduls carregats"""
    return list(self._loaded_modules.keys())

  def is_module_loaded(self, module_name: str) -> bool:
    """Comprova si un mòdul està carregat"""
    return module_name in self._loaded_modules

  def get_module_instance(self, module_name: str) -> Optional[Any]:
    """Obté instància d'un mòdul carregat"""
    return self._loaded_modules.get(module_name)

  async def reload_module(self, module_info: ModuleInfo) -> Any:
    """
    Recarrega un mòdul (descarrega i carrega de nou).

    Args:
      module_info: Informació del mòdul

    Returns:
      Nova instància del mòdul carregat
    """
    module_name = module_info.name

    if LOGGER_AVAILABLE:
      msg = get_message(self.i18n, 'loader.debug.reloading_module',
              module=module_name)
      logger.info(msg, component="loader", module=module_name)

    if self.is_module_loaded(module_name):
      await self.unload_module(module_name)

    return await self.load_module(module_info)

  def get_loader_stats(self) -> Dict[str, Any]:
    """Obté estadístiques del loader"""
    import sys

    return {
      'modules_loaded': len(self._loaded_modules),
      'loaded_modules': list(self._loaded_modules.keys()),
      'memory_modules': len([
        name for name in sys.modules.keys()
        if name.startswith('module_')
      ])
    }

__all__ = ['ModuleLoader', 'ModuleValidationError']