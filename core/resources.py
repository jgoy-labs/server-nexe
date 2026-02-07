"""
────────────────────────────────────
Server Nexe
Version: 0.8
Author: Jordi Goy 
Location: core/resources.py
Description: Centralized resource management (assets) for the Nexe project.

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
  Get a resource (asset) path robustly.

  Multi-mode strategy:
  1. Development (__file__ exists): Use relative Path (faster)
  2. Pip install (importlib.resources): Use the standard API
  3. Fallback: Search via get_repo_root()

  Args:
    package: Python package (e.g., "core.security")
    resource: Path relative to the package (e.g., "ui/index.html")
    use_importlib: If False, force dev mode (__file__)

  Returns:
    Absolute path to the resource

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
        i18n.t("resources.importlib_failed_fallback",
           "importlib.resources failed for {package}/{resource}: {error}. Trying fallback...",
           package=package, resource=resource, error=str(e))
      )

  try:
    return _get_resource_via_file(package, resource)
  except Exception as e:
    i18n = get_i18n()
    logger.warning(
      i18n.t(
        "resources.file_fallback_failed",
        "__file__ fallback failed for {package}/{resource}: {error}. Trying repo_root fallback...",
        package=package, resource=resource, error=str(e)
      )
    )

  try:
    return _get_resource_via_repo_root(package, resource)
  except Exception as e:
    i18n = get_i18n()
    raise RuntimeError(
      i18n.t(
        "resources.resource_not_found",
        "Could not find resource {package}/{resource}. Tried: importlib.resources, __file__, repo_root. Last error: {error}",
        package=package, resource=resource, error=str(e)
      )
    )

def _get_resource_via_importlib(package: str, resource: str) -> Path:
  """
  Get resource via importlib.resources (Python 3.9+).
  Works with pip install and wheel distribution.
  """
  if files is None:
    i18n = get_i18n()
    raise ImportError(
      i18n.t(
        "resources.importlib_resources_not_available",
        "importlib.resources.files not available"
      )
    )

  package_files = files(package)

  resource_path = package_files / resource

  if hasattr(resource_path, '__fspath__'):
    path = Path(resource_path)
  else:
    path = Path(str(resource_path))

  if not path.exists():
    i18n = get_i18n()
    raise FileNotFoundError(
      i18n.t(
        "resources.resource_not_found_importlib",
        "Resource not found via importlib.resources: {package}/{resource}",
        package=package, resource=resource
      )
    )

  return path

def _get_resource_via_file(package: str, resource: str) -> Path:
  """
  Get resource via __file__ (development mode).
  Faster but only works in dev and editable installs.
  """
  import importlib

  try:
    mod = importlib.import_module(package)
  except ImportError as e:
    i18n = get_i18n()
    raise ImportError(
      i18n.t(
        "resources.import_package_failed",
        "Could not import package {package}: {error}",
        package=package, error=str(e)
      )
    )

  if not hasattr(mod, '__file__') or mod.__file__ is None:
    i18n = get_i18n()
    raise RuntimeError(
      i18n.t(
        "resources.package_no_file",
        "Package {package} has no __file__ (may be namespace package or builtin)",
        package=package
      )
    )

  package_dir = Path(mod.__file__).parent

  resource_path = package_dir / resource

  if not resource_path.exists():
    i18n = get_i18n()
    raise FileNotFoundError(
      i18n.t(
        "resources.resource_not_found_file",
        "Resource not found via __file__: {package}/{resource} (searched at {path})",
        package=package, resource=resource, path=str(resource_path)
      )
    )

  return resource_path

def _get_resource_via_repo_root(package: str, resource: str) -> Path:
  """
  Get resource via get_repo_root() (last resort).
  Fallback for edge cases.
  """
  from core.paths import get_repo_root

  package_path = package.replace('.', '/')

  repo_root = get_repo_root()

  resource_path = repo_root / package_path / resource

  if not resource_path.exists():
    i18n = get_i18n()
    raise FileNotFoundError(
      i18n.t(
        "resources.resource_not_found_repo_root",
        "Resource not found via repo_root: {package}/{resource} (searched at {path})",
        package=package, resource=resource, path=str(resource_path)
      )
    )

  return resource_path

def get_ui_path(package: str, filename: str = "index.html") -> Path:
  """
  Shortcut to get a path to UI assets.

  Args:
    package: Python package (e.g., "core.security")
    filename: File inside ui/ (default: "index.html")

  Returns:
    Absolute path to the UI file

  Examples:
    >>> path = get_ui_path("core.security")
    >>>

    >>> path = get_ui_path("core.security", "js/main.js")
    >>>
  """
  return get_resource_path(package, f"ui/{filename}")

def get_template_path(package: str, template_name: str) -> Path:
  """
  Shortcut to get a path to templates.

  Args:
    package: Python package
    template_name: Template name (e.g., "index.html")

  Returns:
    Absolute path to the template

  Examples:
    >>> path = get_template_path("core.security", "report.html")
    >>>
  """
  return get_resource_path(package, f"templates/{template_name}")

def get_translation_path(
  package: str,
  language: str,
  component: str = "messages"
) -> Path:
  """
  Shortcut to get a path to translations.

  Args:
    package: Python package
    language: Language code (e.g., "ca-ES", "en-US")
    component: Translation component (default: "messages")

  Returns:
    Absolute path to the translation file

  Examples:
    >>> path = get_translation_path("core.security", "ca-ES")
    >>>

    >>> path = get_translation_path("core.security", "ca-ES", "ui")
    >>>
  """
  return get_resource_path(
    package,
    f"languages/{language}/{component}.json"
  )

def get_static_path(package: str, asset: str) -> Path:
  """
  Shortcut to get a path to static assets (CSS, JS, images).

  Args:
    package: Python package
    asset: Path relative inside static/ (e.g., "css/styles.css")

  Returns:
    Absolute path to the asset

  Examples:
    >>> path = get_static_path("core.security", "css/styles.css")
    >>>

    >>> path = get_static_path("core.security", "img/logo.png")
    >>>
  """
  return get_resource_path(package, f"static/{asset}")

def resource_exists(package: str, resource: str) -> bool:
  """
  Check whether a resource exists.

  Args:
    package: Python package
    resource: Path relative to the package

  Returns:
    True if the resource exists, False otherwise

  Examples:
    >>> if resource_exists("core.security", "ui/index.html"):
    ...   path = get_resource_path("core.security", "ui/index.html")
  """
  try:
    get_resource_path(package, resource)
    return True
  except (FileNotFoundError, RuntimeError):
    return False

def list_resources(package: str, subdir: str = "") -> list[Path]:
  """
  List all resources inside a package/subdirectory.

  Args:
    package: Python package
    subdir: Optional subdirectory (e.g., "ui", "languages")

  Returns:
    List of Paths to resources

  Examples:
    >>> ui_files = list_resources("core.security", "ui")
    >>>
  """
  try:
    import importlib
    mod = importlib.import_module(package)
    package_dir = Path(mod.__file__).parent
    resource_dir = package_dir / subdir if subdir else package_dir

    if resource_dir.exists() and resource_dir.is_dir():
      return list(resource_dir.rglob("*"))
  except Exception as e:
    logging.debug("Direct package path access failed, using importlib.resources: %s", e)
    pass

  if files is not None:
    try:
      package_files = files(package)
      if subdir:
        package_files = package_files / subdir

      resources = []
      for item in package_files.iterdir():
        if item.is_file():
          resources.append(Path(str(item)))

      return resources
    except Exception as e:
      logging.debug("Resource loading failed for package %s: %s", package, e)
      pass

  return []

def get_asset_path(package: str, asset: str) -> Path:
  """
  DEPRECATED: Use get_resource_path() directly.

  Kept for backwards compatibility with existing code.
  """
  import warnings
  i18n = get_i18n()
  warnings.warn(
    i18n.t(
      "resources.get_asset_deprecated",
      "get_asset_path() is deprecated. Use get_resource_path()."
    ),
    DeprecationWarning,
    stacklevel=2
  )
  return get_resource_path(package, asset)
