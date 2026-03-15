"""
────────────────────────────────────
Server Nexe
Version: 0.8
Author: Jordi Goy
Location: personality/module_manager/config_manager.py
Description: Gestor de configuració i manifests Nexe.
             Uses core/config.py for unified config loading.

www.jgoy.net · https://server-nexe.org
────────────────────────────────────
"""

from pathlib import Path
from typing import Dict, Any, Optional
import toml

from core.config import (
    load_config as core_load_config,
    find_config_path as core_find_config_path,
    save_config as core_save_config,
    is_production,
    is_development,
)
from .messages import get_message

import logging
logger = logging.getLogger(__name__)
LOGGER_AVAILABLE = False


class ConfigManager:
  """
  Gestiona configuració i manifests del sistema.

  Uses core/config.py for unified config loading.
  Adds module-specific functionality (manifests, enabled state).
  """

  def __init__(self, config_path: Optional[Path], i18n=None):
    """
    Inicialitza gestor de configuració.

    Args:
      config_path: Path al fitxer server.toml
      i18n: Gestor i18n opcional
    """
    self.i18n = i18n
    self.config_path = self._find_config_path(config_path)
    self.manifests_path = self.config_path.parent / get_message(
      self.i18n, 'paths.manifests_dir'
    )
    self._config = {}
    self._load_config()

    # Environment helpers
    self.is_production = is_production(self._config)
    self.is_development = is_development(self._config)

  def _t(self, key: str, fallback: str, **kwargs) -> str:
    """
    Helper per traduir amb fallback.

    Args:
      key: Clau de traducció
      fallback: Text per defecte
      **kwargs: Paràmetres de format

    Returns:
      Text traduït o fallback
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
    """Cerca fitxer de configuració"""
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
    """Carrega configuració des del fitxer TOML usant core/config."""
    try:
      # Use unified config loading from core/config.py
      self._config = core_load_config(
        config_path=self.config_path,
        i18n=self.i18n
      )
    except Exception as e:
      if LOGGER_AVAILABLE:
        msg = get_message(self.i18n, 'init.config_error', error=str(e))
        logger.error(msg, component="config_manager")
      self._config = {}

  def get_config(self) -> Dict[str, Any]:
    """Retorna la configuració completa"""
    return self._config

  def find_manifest(self, module_name: str, module_path: Path) -> Path:
    """
    Cerca fitxer manifest per un mòdul.

    Args:
      module_name: Nom del mòdul
      module_path: Path del mòdul

    Returns:
      Path al manifest
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
    Carrega fitxer manifest.

    Args:
      manifest_path: Path al manifest

    Returns:
      Diccionari amb dades del manifest
    """
    try:
      with open(manifest_path, 'r', encoding='utf-8') as f:
        return toml.load(f)
    except FileNotFoundError as e:
      logger.debug("Manifest file not found: %s - %s", manifest_path, e)
      pass
    except (IOError, KeyError) as e:
      logger.debug("Error reading manifest: %s - %s", manifest_path, e)
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

  def apply_config_to_module(self, module_info) -> None:
    """
    Aplica configuració a un ModuleInfo.

    Suporta dos formats de configuració:
    - FORMAT 1 (list): [plugins.modules] enabled = ["security", "security"]
    - FORMAT 2 (dict): [plugins.modules.security] enabled = true

    Prioritat: dict > list (més específic guanya)

    Args:
      module_info: ModuleInfo a configurar
    """
    from personality.data.models import ModuleState

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
        pass

    modules_config = self._config.get(layer, {}).get('modules', {})

    def _is_plugins_module() -> bool:
      """
      Determina si el mòdul forma part de l'espai plugins/*.
      Serveix per aplicar l'allowlist [plugins.modules].enabled només a aquests mòduls.
      """
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

    module_config = modules_config.get(module_info.name, {})

    module_path = getattr(module_info, "path", None)
    if module_path and '/core/' in str(module_path):
      module_info.enabled = True
      msg = self._t("module_manager.core_module_always_enabled",
             "Mòdul {name} és CORE, sempre habilitat",
             name=module_info.name)
      logger.info(msg)
    elif isinstance(module_config, dict) and 'enabled' in module_config:
      module_info.enabled = module_config.get('enabled', True)
      logger.debug("Module %s enabled=%s (from dict config)", module_info.name, module_info.enabled)
    else:
      enabled_list = modules_config.get('enabled', None)
      if isinstance(enabled_list, list) and _is_plugins_module():
        if module_info.name in enabled_list:
          module_info.enabled = True
          logger.debug("Module %s enabled (from list)", module_info.name)
        else:
          module_info.enabled = False
          logger.info("Module %s not in enabled list, disabling", module_info.name)
          module_info.state = ModuleState.DISABLED
          return
      elif isinstance(enabled_list, list):
        logger.debug(
          "Module %s skipping plugins allowlist (module outside plugins/*)", module_info.name
        )
        module_info.enabled = module_info.manifest.get('module', {}).get('enabled', True)
        logger.debug("Module %s enabled=%s (from manifest default)", module_info.name, module_info.enabled)
      else:
        module_info.enabled = module_info.manifest.get('module', {}).get('enabled', True)
        logger.debug("Module %s enabled=%s (from manifest default)", module_info.name, module_info.enabled)

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
    Actualitza l'estat enabled d'un mòdul i guarda al server.toml.

    Args:
      module_name: Nom del mòdul
      enabled: True per activar, False per desactivar
      module_path: Path del mòdul

    Returns:
      True si s'ha guardat correctament
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