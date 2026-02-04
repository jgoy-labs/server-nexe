"""
────────────────────────────────────
Server Nexe
Version: 0.8
Author: Jordi Goy 
Location: core/resources.py
Description: Gestió centralitzada de recursos (assets) del projecte Nexe.

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
  Obté path a un recurs (asset) de forma robust.

  Estratègia multi-mode:
  1. Development (__file__ exists): Usa Path relatius (més ràpid)
  2. Pip install (importlib.resources): Usa API estàndard
  3. Fallback: Busca via get_repo_root()

  Args:
    package: Package Python (e.g., "core.security")
    resource: Path relatiu al package (e.g., "ui/index.html")
    use_importlib: Si False, força mode dev (__file__)

  Returns:
    Path absolut al recurs

  Raises:
    FileNotFoundError: Si el recurs no existeix
    RuntimeError: Si cap estratègia funciona

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
      f"No s'ha pogut trobar el recurs {package}/{resource}. "
      f"Proves: importlib.resources, __file__, repo_root. "
      f"Últim error: {e}"
    )

def _get_resource_via_importlib(package: str, resource: str) -> Path:
  """
  Obté recurs via importlib.resources (Python 3.9+).
  Funciona en pip install i wheel distribution.
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
      f"Recurs no trobat via importlib.resources: {package}/{resource}"
    )

  return path

def _get_resource_via_file(package: str, resource: str) -> Path:
  """
  Obté recurs via __file__ (development mode).
  Més ràpid però només funciona en dev i pip install editable.
  """
  import importlib

  try:
    mod = importlib.import_module(package)
  except ImportError as e:
    raise ImportError(f"No s'ha pogut importar package {package}: {e}")

  if not hasattr(mod, '__file__') or mod.__file__ is None:
    raise RuntimeError(
      f"Package {package} no té __file__ "
      f"(pot ser namespace package o builtin)"
    )

  package_dir = Path(mod.__file__).parent

  resource_path = package_dir / resource

  if not resource_path.exists():
    raise FileNotFoundError(
      f"Recurs no trobat via __file__: {package}/{resource} "
      f"(buscat a {resource_path})"
    )

  return resource_path

def _get_resource_via_repo_root(package: str, resource: str) -> Path:
  """
  Obté recurs via get_repo_root() (últim recurs).
  Fallback per casos extrems.
  """
  from core.paths import get_repo_root

  package_path = package.replace('.', '/')

  repo_root = get_repo_root()

  resource_path = repo_root / package_path / resource

  if not resource_path.exists():
    raise FileNotFoundError(
      f"Recurs no trobat via repo_root: {package}/{resource} "
      f"(buscat a {resource_path})"
    )

  return resource_path

def get_ui_path(package: str, filename: str = "index.html") -> Path:
  """
  Shortcut per obtenir path a UI assets.

  Args:
    package: Package Python (e.g., "core.security")
    filename: Fitxer dins de ui/ (default: "index.html")

  Returns:
    Path absolut al fitxer UI

  Examples:
    >>> path = get_ui_path("core.security")
    >>>

    >>> path = get_ui_path("core.security", "js/main.js")
    >>>
  """
  return get_resource_path(package, f"ui/{filename}")

def get_template_path(package: str, template_name: str) -> Path:
  """
  Shortcut per obtenir path a templates.

  Args:
    package: Package Python
    template_name: Nom del template (e.g., "index.html")

  Returns:
    Path absolut al template

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
  Shortcut per obtenir path a traduccions.

  Args:
    package: Package Python
    language: Codi idioma (e.g., "ca-ES", "en-US")
    component: Component de traducció (default: "messages")

  Returns:
    Path absolut al fitxer de traducció

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
  Shortcut per obtenir path a static assets (CSS, JS, images).

  Args:
    package: Package Python
    asset: Path relatiu dins de static/ (e.g., "css/styles.css")

  Returns:
    Path absolut a l'asset

  Examples:
    >>> path = get_static_path("core.security", "css/styles.css")
    >>>

    >>> path = get_static_path("core.security", "img/logo.png")
    >>>
  """
  return get_resource_path(package, f"static/{asset}")

def resource_exists(package: str, resource: str) -> bool:
  """
  Verifica si un recurs existeix.

  Args:
    package: Package Python
    resource: Path relatiu al package

  Returns:
    True si el recurs existeix, False altrament

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
  Llista tots els recursos dins d'un package/subdirectori.

  Args:
    package: Package Python
    subdir: Subdirectori opcional (e.g., "ui", "languages")

  Returns:
    Llista de Paths als recursos

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
  DEPRECATED: Usa get_resource_path() directament.

  Mantingut per backwards compatibility amb codi existent.
  """
  import warnings
  warnings.warn(
    "get_asset_path() està deprecated. Usa get_resource_path().",
    DeprecationWarning,
    stacklevel=2
  )
  return get_resource_path(package, asset)