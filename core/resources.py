"""
────────────────────────────────────
Server Nexe
Version: 0.8
Author: Jordi Goy 
Location: core/resources.py
Description: Centralized resource (asset) path management for Nexe.

www.jgoy.net
────────────────────────────────────
"""

import sys
import logging
from pathlib import Path

if sys.version_info >= (3, 9):
  from importlib.resources import files
else:
  try:
    from importlib_resources import files
  except ImportError:
    files = None

from personality.i18n import get_i18n

logger = logging.getLogger(__name__)

def get_resource_path(
  package: str,
  resource: str,
  use_importlib: bool = True
) -> Path:
  """
  Get path to a resource (asset) robustly.

  Multi-mode strategy:
  1. Development (__file__ exists): Uses relative Paths (fastest)
  2. Pip install (importlib.resources): Uses standard API
  3. Fallback: Searches via get_repo_root()

  Args:
    package: Python package (e.g., "core.security")
    resource: Relative path within package (e.g., "ui/index.html")
    use_importlib: If False, forces dev mode (__file__)

  Returns:
    Absolute Path to the resource

  Raises:
    FileNotFoundError: If the resource does not exist
    RuntimeError: If no strategy works

  Examples:
    >>>
    >>> path = get_resource_path("core.security", "ui/index.html")
    >>>

    >>>
    >>> path = get_resource_path("core.security", "ui/index.html")
    >>>
  """

  if not use_importlib:
    return _get_resource_via_file(package, resource)

  if files is not None:
    try:
      return _get_resource_via_importlib(package, resource)
    except Exception as e:
      i18n = get_i18n()
      logger.warning(
        i18n.t("core.resources.importlib_failed_fallback",
           "importlib.resources failed for {package}/{resource}: {error}. Trying fallback...",
           package=package, resource=resource, error=str(e))
      )

  try:
    return _get_resource_via_file(package, resource)
  except Exception as e:
    logger.warning(
      f"__file__ fallback failed for {package}/{resource}: {e}. "
      f"Trying repo_root fallback..."
    )

  try:
    return _get_resource_via_repo_root(package, resource)
  except Exception as e:
    raise RuntimeError(
      f"Could not find resource {package}/{resource}. "
      f"Tried: importlib.resources, __file__, repo_root. "
      f"Last error: {e}"
    )

def _get_resource_via_importlib(package: str, resource: str) -> Path:
  """
  Get resource via importlib.resources (Python 3.9+).
  Works with pip install and wheel distribution.
  """
  if files is None:
    i18n = get_i18n()
    raise ImportError(
      i18n.t("core.resources.importlib_resources_not_available", "importlib.resources.files not available")
    )

  package_files = files(package)

  resource_path = package_files / resource

  if hasattr(resource_path, '__fspath__'):
    path = Path(resource_path)
  else:
    path = Path(str(resource_path))

  if not path.exists():
    raise FileNotFoundError(
      f"Resource not found via importlib.resources: {package}/{resource}"
    )

  return path

def _get_resource_via_file(package: str, resource: str) -> Path:
  """
  Get resource via __file__ (development mode).
  Faster but only works in dev and pip install editable.
  """
  import importlib

  try:
    mod = importlib.import_module(package)
  except ImportError as e:
    raise ImportError(f"Could not import package {package}: {e}")

  if not hasattr(mod, '__file__') or mod.__file__ is None:
    raise RuntimeError(
      f"Package {package} has no __file__ "
      f"(may be namespace package or builtin)"
    )

  package_dir = Path(mod.__file__).parent

  resource_path = package_dir / resource

  if not resource_path.exists():
    raise FileNotFoundError(
      f"Resource not found via __file__: {package}/{resource} "
      f"(searched at {resource_path})"
    )

  return resource_path

def _get_resource_via_repo_root(package: str, resource: str) -> Path:
  """
  Get resource via get_repo_root() (last resort).
  Fallback for extreme cases.
  """
  from core.paths import get_repo_root

  package_path = package.replace('.', '/')

  repo_root = get_repo_root()

  resource_path = repo_root / package_path / resource

  if not resource_path.exists():
    raise FileNotFoundError(
      f"Resource not found via repo_root: {package}/{resource} "
      f"(searched at {resource_path})"
    )

  return resource_path