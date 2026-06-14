"""
────────────────────────────────────
Server Nexe
Author: Jordi Goy
Location: personality/module_manager/config_manager.py
Description: Nexe configuration and manifest manager.
             Uses core/config.py for unified config loading.

www.jgoy.net · https://server-nexe.org
────────────────────────────────────
"""

from pathlib import Path
from typing import Dict, Any, Optional
import toml  # type: ignore[import-untyped]  # FP: types-toml available but not installed

from core.config import (
    load_config as core_load_config,
    save_config as core_save_config,
    is_production,
    is_development,
)
from .messages import get_message

from personality._logger import get_logger
logger = get_logger(__name__)


class ConfigManager:
  """
  Manages system configuration and manifests.

  Uses core/config.py for unified config loading.
  Adds module-specific functionality (manifests, enabled state).
  """

  def __init__(self, config_path: Optional[Path], i18n=None):
    """
    Initialize configuration manager.

    Args:
      config_path: Path to the server.toml file
      i18n: Optional i18n manager
    """
    self.i18n = i18n
    self.config_path = self._find_config_path(config_path)
    self.manifests_path = self.config_path.parent / get_message(
      self.i18n, 'paths.manifests_dir'
    )
    self._config: Dict[str, Any] = {}
    self._load_config()

    # Environment helpers
    self.is_production = is_production(self._config)
    self.is_development = is_development(self._config)

  def _t(self, key: str, fallback: str, **kwargs) -> str:
    """
    Translation helper with fallback.

    Args:
      key: Translation key
      fallback: Default text
      **kwargs: Format parameters

    Returns:
      Translated text or fallback
    """
    if not self.i18n:
      return fallback.format(**kwargs) if kwargs else fallback
    try:
      value = self.i18n.t(key, **kwargs)
      if value == key:
        return fallback.format(**kwargs) if kwargs else fallback
      return value
    except Exception:
      return fallback.format(**kwargs) if kwargs else fallback

  def _find_config_path(self, config_path: Optional[Path]) -> Path:
    """Search for the configuration file."""
    if config_path:
      try:
        return Path(config_path).resolve(strict=True)
      except (FileNotFoundError, OSError) as e:
        logger.debug("Config path not found or inaccessible: %s - %s", config_path, e)
        pass

    search_paths = [
      Path("server.toml"),
      Path("personality/server.toml"),
      Path("config/server.toml"),
      Path("../server.toml"),
      Path("../../server.toml")
    ]

    for path in search_paths:
      try:
        return path.resolve(strict=True)
      except (FileNotFoundError, OSError):
        continue

    return Path("personality/server.toml")

  def _load_config(self) -> None:
    """Load configuration from the TOML file using core/config."""
    try:
      # Use unified config loading from core/config.py
      self._config = core_load_config(
        config_path=self.config_path,
        i18n=self.i18n
      )
    except Exception as e:
      msg = get_message(self.i18n, 'init.config_error', error=str(e))
      logger.error(msg, component="config_manager")
      self._config = {}

  def get_config(self) -> Dict[str, Any]:
    """Return the full configuration."""
    return self._config

  def find_manifest(self, module_name: str, module_path: Path) -> Path:
    """
    Find manifest file for a module.

    Args:
      module_name: Module name
      module_path: Module path

    Returns:
      Path to the manifest
    """
    manifest_filename = get_message(
      self.i18n, 'files.module_manifest_format',
      module_name=module_name
    )
    central = self.manifests_path / manifest_filename
    try:
      central.resolve(strict=True)
      return central
    except (FileNotFoundError, OSError) as e:
      logger.debug("Central manifest not found: %s - %s", central, e)
      pass

    local_manifest_name = get_message(self.i18n, 'files.manifest_toml')
    local = module_path / local_manifest_name
    try:
      local.resolve(strict=True)
      return local
    except (FileNotFoundError, OSError) as e:
      logger.debug("Local manifest not found: %s - %s", local, e)
      pass

    return central

  def load_manifest(self, manifest_path: Path) -> Dict[str, Any]:
    """
    Load manifest file.

    Args:
      manifest_path: Path to the manifest

    Returns:
      Dictionary with manifest data
    """
    try:
      with open(manifest_path, 'r', encoding='utf-8') as f:
        return toml.load(f)
    except FileNotFoundError as e:
      logger.debug("Manifest file not found: %s - %s", manifest_path, e)
      pass
    except (IOError, KeyError, toml.TomlDecodeError) as e:
      # B106: a corrupt/unparseable manifest must not crash the boot — fall
      # back to the default dict below. TomlDecodeError is a ValueError subclass;
      # we catch it explicitly rather than bare ValueError so genuine
      # programming errors inside the try still surface.
      logger.warning("Error reading manifest: %s - %s", manifest_path, e)
      pass

    module_key = get_message(self.i18n, 'manifest.keys.module')
    version_key = get_message(self.i18n, 'manifest.keys.version')
    enabled_key = get_message(self.i18n, 'manifest.keys.enabled')
    default_version = get_message(self.i18n, 'manifest.default.version')
    default_enabled = get_message(self.i18n, 'manifest.default.enabled')

    return {
      module_key: {
        version_key: default_version,
        enabled_key: default_enabled
      }
    }

  def _resolve_module_layer(self, module_info) -> str:
    module_path = getattr(module_info, "path", None)
    layer = "plugins"
    if module_path:
      try:
        project_root = self.config_path.parent
        if project_root.name == "personality":
          project_root = project_root.parent
        relative = module_path.resolve().relative_to(project_root.resolve())
        if len(relative.parts) > 0:
          layer = relative.parts[0]
      except Exception as e:
        logger.debug("Could not determine module layer for %s: %s", module_path, e)
    return layer

  def _is_plugins_module(self, module_info) -> bool:
    module_path = getattr(module_info, "path", None)
    if module_path is None:
      return True
    try:
      resolved_module = module_path.resolve()
    except Exception:
      resolved_module = module_path
    project_root = self.config_path.parent
    if project_root.name == "personality":
      project_root = project_root.parent
    try:
      relative = resolved_module.relative_to(project_root.resolve())
    except Exception:
      return True
    return len(relative.parts) > 0 and relative.parts[0] == "plugins"

  def _apply_enabled_from_core(self, module_info) -> None:
    module_info.enabled = True
    msg = self._t("module_manager.core_module_always_enabled",
           "Module {name} is CORE, always enabled",
           name=module_info.name)
    logger.info(msg)

  def _apply_enabled_from_dict(self, module_info, module_config: dict) -> None:
    module_info.enabled = module_config.get('enabled', True)
    logger.debug("Module %s enabled=%s (from dict config)", module_info.name, module_info.enabled)

  def _apply_enabled_from_list_or_manifest(self, module_info, modules_config: dict) -> bool:
    from personality.data.models import ModuleState
    enabled_list = modules_config.get('enabled', None)
    if isinstance(enabled_list, list) and self._is_plugins_module(module_info):
      if module_info.name in enabled_list:
        module_info.enabled = True
        logger.debug("Module %s enabled (from list)", module_info.name)
      else:
        module_info.enabled = False
        logger.info("Module %s not in enabled list, disabling", module_info.name)
        module_info.state = ModuleState.DISABLED
        return False  # signals early return
    elif isinstance(enabled_list, list):
      logger.debug("Module %s skipping plugins allowlist (module outside plugins/*)", module_info.name)
      module_info.enabled = module_info.manifest.get('module', {}).get('enabled', True)
      logger.debug("Module %s enabled=%s (from manifest default)", module_info.name, module_info.enabled)
    else:
      module_info.enabled = module_info.manifest.get('module', {}).get('enabled', True)
      logger.debug("Module %s enabled=%s (from manifest default)", module_info.name, module_info.enabled)
    return True

  def apply_config_to_module(self, module_info) -> None:
    """
    Apply configuration to a ModuleInfo.

    Supports two configuration formats:
    - FORMAT 1 (list): [plugins.modules] enabled = ["security", "security"]
    - FORMAT 2 (dict): [plugins.modules.security] enabled = true

    Priority: dict > list (more specific wins)

    Args:
      module_info: ModuleInfo to configure
    """
    from personality.data.models import ModuleState

    layer = self._resolve_module_layer(module_info)
    modules_config = self._config.get(layer, {}).get('modules', {})
    module_config = modules_config.get(module_info.name, {})

    module_path = getattr(module_info, "path", None)
    if module_path and '/core/' in str(module_path):
      self._apply_enabled_from_core(module_info)
    elif isinstance(module_config, dict) and 'enabled' in module_config:
      self._apply_enabled_from_dict(module_info, module_config)
    else:
      if not self._apply_enabled_from_list_or_manifest(module_info, modules_config):
        return

    module_info.priority = module_config.get(
      'priority',
      module_info.manifest.get('module', {}).get('priority', 10)
    )
    module_info.auto_start = module_config.get(
      'auto_start',
      module_info.manifest.get('module', {}).get('auto_start', False)
    )

    deps = module_info.manifest.get('dependencies', {})
    module_info.dependencies = deps.get('internal', [])

    if not module_info.enabled:
      logger.info("Module %s disabled via config", module_info.name)
      module_info.state = ModuleState.DISABLED

  def update_module_enabled(self, module_name: str, enabled: bool, module_path: Path) -> bool:
    """
    Update the enabled state of a module and persist to server.toml.

    Args:
      module_name: Module name
      enabled: True to enable, False to disable
      module_path: Module path

    Returns:
      True if saved successfully
    """
    try:
      project_root = self.config_path.parent
      if project_root.name == "personality":
        project_root = project_root.parent

      relative = module_path.resolve().relative_to(project_root.resolve())
      layer = relative.parts[0] if len(relative.parts) > 0 else "plugins"
    except Exception:
      layer = "plugins"

    if layer not in self._config:
      self._config[layer] = {}
    if 'modules' not in self._config[layer]:
      self._config[layer]['modules'] = {}

    if module_name not in self._config[layer]['modules']:
      self._config[layer]['modules'][module_name] = {}

    self._config[layer]['modules'][module_name]['enabled'] = enabled

    # Use unified save from core/config.py
    success = core_save_config(self._config, self.config_path)
    if success:
      logger.info("Saved module %s enabled=%s to config", module_name, enabled)
    else:
      msg = self._t("module_manager.error_saving_config",
             "Error guardant configuració",
             error="save failed")
      logger.error(msg)
    return success