"""
────────────────────────────────────
Server Nexe
Version: 0.8
Author: Jordi Goy 
Location: personality/loading/module_importer.py
Description: Importador dinàmic de mòduls Python. Carrega fitxers via importlib.util amb

www.jgoy.net · https://server-nexe.org
────────────────────────────────────
"""

import sys
import importlib.util
from pathlib import Path
from typing import Any
from .patterns import LoaderPatterns
from .messages import get_message

import logging
logger = logging.getLogger(__name__)
LOGGER_AVAILABLE = False

class ModuleImporter:
  """Importa mòduls Python dinàmicament"""

  def __init__(self, i18n=None):
    self.i18n = i18n
    self.patterns = LoaderPatterns(i18n)

  def import_module(self, api_file: Path, module_name: str) -> Any:
    """
    Importa dinàmicament un mòdul Python.

    Args:
      api_file: Path del fitxer a importar
      module_name: Nom del mòdul

    Returns:
      Mòdul importat

    Raises:
      ImportError: Si no es pot importar
    """
    module_full_name = self.patterns.get_module_name_prefix(
      module_name, id(api_file)
    )

    spec = importlib.util.spec_from_file_location(module_full_name, api_file)

    if spec is None or spec.loader is None:
      error_msg = get_message(self.i18n, 'loader.debug.cannot_create_spec',
                  file=str(api_file))
      if LOGGER_AVAILABLE:
        logger.error(error_msg, component="loader", module=module_name)
      raise ImportError(error_msg)

    module = importlib.util.module_from_spec(spec)

    sys.modules[module_full_name] = module

    spec.loader.exec_module(module)

    return module

  def cleanup_module(self, module_name: str) -> int:
    """
    Neteja mòdul de sys.modules.

    Args:
      module_name: Nom del mòdul a netejar

    Returns:
      Nombre de mòduls eliminats
    """
    modules_to_remove = []
    prefix = f"module_{module_name}"

    for key in list(sys.modules.keys()):
      if any([
        key.startswith(prefix),
        f"_{module_name}_" in key
      ]):
        modules_to_remove.append(key)

    for key in modules_to_remove:
      sys.modules.pop(key, None)

    return len(modules_to_remove)