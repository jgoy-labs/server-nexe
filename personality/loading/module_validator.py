"""
────────────────────────────────────
Server Nexe
Version: 0.8
Author: Jordi Goy 
Location: personality/loading/module_validator.py
Description: Validador de mòduls carregats. Comprova instància vàlida, existència d'API

www.jgoy.net · https://server-nexe.org
────────────────────────────────────
"""

import importlib
import os
import warnings
from pathlib import Path
from typing import Any, List, Optional
from ..data.models import ModuleInfo
from .messages import get_message

from personality._logger import get_logger
logger = get_logger(__name__)
LOGGER_AVAILABLE = True

try:
  from personality.auto_clean.core.registry import IntegrityChecker
  INTEGRITY_CHECKER_AVAILABLE = True
except ImportError:
  INTEGRITY_CHECKER_AVAILABLE = False
  IntegrityChecker = None

class ModuleValidationError(Exception):
  """Error de validació de mòdul"""
  pass

class ModuleValidator:
  """Valida mòduls carregats"""

  def __init__(self, i18n=None, core_root: Optional[Path] = None):
    self.i18n = i18n
    self._integrity_checker: Optional["IntegrityChecker"] = None

    if INTEGRITY_CHECKER_AVAILABLE:
      if core_root is None:
        core_root_str = os.environ.get("NEXE_ROOT")
        if core_root_str:
          core_root = Path(core_root_str)
        else:
          core_root = Path(__file__).parent.parent.parent.parent

      lock_path = core_root / "storage" / ".auto_clean" / "manifests.lock"
      try:
        self._integrity_checker = IntegrityChecker(lock_path)
        logger.debug("IntegrityChecker initialized for manifest validation")
      except Exception as e:
        logger.warning(f"Failed to initialize IntegrityChecker: {e}")

  def validate_module(self, instance: Any, module_info: ModuleInfo) -> None:
    """
    Valida que un mòdul compleixi els requisits mínims.

    Args:
      instance: Instància del mòdul
      module_info: Informació del mòdul

    Raises:
      ModuleValidationError: Si la validació falla
    """
    validations = []

    self._validate_manifest_integrity(module_info, validations)

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
    """Valida API si està especificat al manifest"""
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
    """Valida UI si està especificat al manifest"""
    ui_section = module_info.manifest.get('ui', {})

    if ui_section.get('enabled', False):
      ui_path = module_info.path / ui_section.get('path', 'ui')
      main_file = ui_path / ui_section.get('main_file', 'index.html')

      if not main_file.exists():
        validations.append(
          get_message(self.i18n, 'validation.ui_file_missing',
               file=str(main_file))
        )

  def _validate_manifest_integrity(
    self, module_info: ModuleInfo, validations: List[str]
  ) -> None:
    """
    SECURITY: Valida integritat del manifest (TOFU - Trust On First Use).

    Si el manifest no està al lock, l'afegeix automàticament (TOFU).
    Si està al lock però el checksum no coincideix, rebutja el mòdul.
    """
    if not self._integrity_checker:
      return

    manifest_path = module_info.path / "manifest.toml"
    if not manifest_path.exists():
      return

    is_valid, message = self._integrity_checker.verify(manifest_path)

    if not is_valid:
      error_msg = f"SECURITY: Manifest integrity check failed for '{module_info.name}': {message}"
      logger.error(error_msg)

      try:
        from plugins.security_logger import (
          get_security_logger,
          SecurityEventType,
          SecuritySeverity,
        )
        security_logger = get_security_logger()
        security_logger.log_event(
          event_type=SecurityEventType.MODULE_REJECTED,
          severity=SecuritySeverity.CRITICAL,
          message=f"Manifest integrity check failed for module '{module_info.name}'",
          details={"module": module_info.name, "reason": message},
        )
      except ImportError:
        pass

      validations.append(error_msg)
    elif "New manifest (TOFU)" in message:
      self._integrity_checker.trust(manifest_path)
      logger.info(f"TOFU: Trusted new manifest for module '{module_info.name}'")

  def _validate_dependencies(self, module_info: ModuleInfo) -> None:
    """Valida dependències externes (només warning)"""
    deps = module_info.manifest.get('dependencies', {})
    external_deps = deps.get('external', [])
    missing_deps = []

    for dep in external_deps:
      dep_name = dep.split('>=')[0].split('==')[0].strip()
      try:
        importlib.import_module(dep_name)
      except ImportError:
        missing_deps.append(dep_name)

    if missing_deps:
      warning_msg = get_message(
        self.i18n, 'validation.dependency_missing',
        dep=', '.join(missing_deps)
      )

      warnings.warn(warning_msg)
      if LOGGER_AVAILABLE:
        logger.warning(warning_msg, component="loader",
               module=module_info.name, missing_deps=missing_deps)