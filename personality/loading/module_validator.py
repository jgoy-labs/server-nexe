"""
────────────────────────────────────
Server Nexe
Author: Jordi Goy 
Location: personality/loading/module_validator.py
Description: Loaded module validator. Checks valid instance, presence of API

www.jgoy.net · https://server-nexe.org
────────────────────────────────────
"""

import importlib
import warnings
from typing import Any, List, Optional
from pathlib import Path
from ..data.models import ModuleInfo
from .messages import get_message

from personality._logger import get_logger
logger = get_logger(__name__)

class ModuleValidationError(Exception):
  """Module validation error."""
  pass

class ModuleValidator:
  """Validate loaded modules."""

  def __init__(self, i18n=None, core_root: Optional[Path] = None):
    self.i18n = i18n

  def validate_module(self, instance: Any, module_info: ModuleInfo) -> None:
    """
    Validate that a module meets minimum requirements.

    Args:
      instance: Module instance
      module_info: Module information

    Raises:
      ModuleValidationError: If validation fails
    """
    validations: list[str] = []

    # TODO(security): manifest integrity validation (TOFU + checksum lock) is
    # not implemented. A previous IntegrityChecker hook was always a no-op
    # (the backing module never existed) and has been removed to avoid the
    # false impression that manifest signatures are verified here. Out of
    # scope for now; if added, wire it in before the checks below.

    if instance is None:
      validations.append(get_message(self.i18n, 'validation.instance_missing'))

    self._validate_api(instance, module_info.manifest, validations)

    self._validate_ui(instance, module_info, validations)

    self._validate_dependencies(module_info)

    if validations:
      error_msg = get_message(
        self.i18n, 'validation.validation_failed',
        module=module_info.name,
        errors="\n".join(f" - {error}" for error in validations)
      )
      raise ModuleValidationError(error_msg)

  def _validate_api(self, instance: Any, manifest: dict,
           validations: List[str]) -> None:
    """Validate the API if specified in the manifest."""
    api_section = manifest.get('api', {})

    if api_section.get('endpoints_auto_discovery', False):
      has_api = any([
        hasattr(instance, attr) for attr in
        ['router', 'app', 'blueprint', 'routes', 'endpoints']
      ])

      if not has_api:
        validations.append(
          get_message(self.i18n, 'validation.api_router_missing')
        )

  def _validate_ui(self, instance: Any, module_info: ModuleInfo,
          validations: List[str]) -> None:
    """Validate the UI if specified in the manifest."""
    ui_section = module_info.manifest.get('ui', {})

    if ui_section.get('enabled', False):
      ui_path = module_info.path / ui_section.get('path', 'ui')
      main_file = ui_path / ui_section.get('main_file', 'index.html')

      if not main_file.exists():
        validations.append(
          get_message(self.i18n, 'validation.ui_file_missing',
               file=str(main_file))
        )

  def _validate_dependencies(self, module_info: ModuleInfo) -> None:
    """Validate external dependencies (warning only)."""
    deps = module_info.manifest.get('dependencies', {})
    external_deps = deps.get('external', [])
    missing_deps = []

    for dep in external_deps:
      dep_name = dep.split('>=')[0].split('==')[0].strip()
      try:
        importlib.import_module(dep_name)  # nosemgrep: non-literal-import — dep_name from manifest dependencies list, validated by manifest schema
      except ImportError:
        missing_deps.append(dep_name)

    if missing_deps:
      warning_msg = get_message(
        self.i18n, 'validation.dependency_missing',
        dep=', '.join(missing_deps)
      )

      warnings.warn(warning_msg)
      logger.warning(warning_msg, component="loader",
             module=module_info.name, missing_deps=missing_deps)