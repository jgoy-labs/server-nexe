"""
────────────────────────────────────
Server Nexe
Author: Jordi Goy 
Location: personality/loading/module_finder.py
Description: API file finder for Nexe modules. Searches files by priority patterns

www.jgoy.net · https://server-nexe.org
────────────────────────────────────
"""

from pathlib import Path
from typing import Optional
from .patterns import LoaderPatterns
from .messages import get_message

from personality._logger import get_logger
logger = get_logger(__name__)

class ModuleFinder:
  """Find API files for modules."""

  def __init__(self, i18n=None):
    self.i18n = i18n
    self.patterns = LoaderPatterns(i18n)

  def find_api_file(self, module_path: Path, module_name: str) -> Optional[Path]:
    """
    Find the API file for a module following different patterns.

    Args:
      module_path: Path to the module directory
      module_name: Module name

    Returns:
      Path to the found file or None
    """
    api_file = self._find_by_patterns(module_path, module_name)
    if api_file:
      return api_file

    return self._find_fallback_py_file(module_path, module_name)

  def _find_by_patterns(self, module_path: Path, module_name: str) -> Optional[Path]:
    """Search using defined patterns."""
    api_file_patterns = self.patterns.get_api_file_patterns()
    python_ext = self.patterns.get_python_extension()

    for pattern in api_file_patterns:
      filename = pattern.format(module_name=module_name)
      candidate = module_path / filename

      if candidate.exists() and candidate.is_file():
        if candidate.suffix == python_ext:
          msg = get_message(self.i18n, 'loader.debug.found_api_file',
                  file=str(candidate))
          logger.debug(msg, component="loader", module=module_name)
          return candidate

    return None

  def _find_fallback_py_file(self, module_path: Path, module_name: str) -> Optional[Path]:
    """Search for any .py file as a fallback."""
    python_ext = self.patterns.get_python_extension()
    py_files = list(module_path.glob(f"*{python_ext}"))

    ignore_prefixes = self.patterns.get_ignore_prefixes()
    ignore_setup = get_message(self.i18n, 'loader.ignore_files.setup')

    for py_file in py_files:
      name = py_file.stem
      if not name.startswith(ignore_prefixes) and name != ignore_setup:
        msg = get_message(self.i18n, 'loader.debug.fallback_api_file',
                file=str(py_file))
        logger.debug(msg, component="loader", module=module_name)
        return py_file

    return None