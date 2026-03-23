"""
────────────────────────────────────
Server Nexe
Version: 0.8
Author: Jordi Goy 
Location: personality/module_manager/discovery.py
Description: Component de descobriment de mòduls.

www.jgoy.net · https://server-nexe.org
────────────────────────────────────
"""

import os
from datetime import datetime, timezone
from typing import Dict, List

from personality.data.models import (
  ModuleInfo, ModuleState, SystemEvent, detect_dependency_cycles
)

from .messages import get_message

from personality._logger import get_logger
logger = get_logger(__name__)

class ModuleDiscovery:
  """
  Component especialitzat en descobriment de mòduls.

  Responsabilitats:
  - Descobriment de paths de mòduls
  - Creació/actualització de ModuleInfo
  - Detecció de cicles de dependències
  - Emissió d'events de descobriment
  """

  def __init__(
    self,
    path_discovery,
    config_manager,
    events,
    i18n
  ):
    """
    Inicialitza el component de descobriment.

    Args:
      path_discovery: Component PathDiscovery
      config_manager: Component ConfigManager
      events: EventSystem
      i18n: I18nManager
    """
    self.path_discovery = path_discovery
    self.config_manager = config_manager
    self.events = events
    self.i18n = i18n

  async def discover(
    self,
    modules_dict: Dict[str, ModuleInfo],
    lock,
    force: bool = False
  ) -> List[str]:
    """
    Descobreix mòduls disponibles.

    Args:
      modules_dict: Diccionari de mòduls (es modifica in-place)
      lock: Lock per sincronització
      force: Força redescobriment encara que hi hagi cache

    Returns:
      Llista de noms de mòduls descoberts
    """
    msg = get_message(self.i18n, 'discovery.starting')
    logger.info(msg, component="module_manager")

    nexe_env = (os.getenv("NEXE_ENV") or "").lower()
    if nexe_env in ("test", "testing") or os.getenv("PYTEST_CURRENT_TEST"):
      force = True

    if not force and not self.path_discovery.load_cache():
      force = True

    if force:
      paths = self.path_discovery.discover_all_paths()
      modules_found = self.path_discovery.scan_for_modules(paths)
      self.path_discovery.save_cache()
    else:
      modules_found = self.path_discovery._module_locations

    discovered = []
    with lock:
      for module_name, module_path in modules_found.items():
        manifest_path = self.config_manager.find_manifest(
          module_name, module_path
        )
        manifest = self.config_manager.load_manifest(manifest_path)

        module_info = modules_dict.get(module_name)
        if module_info is None:
          module_info = ModuleInfo(
            name=module_name,
            path=module_path,
            manifest_path=manifest_path,
            manifest=manifest,
            state=ModuleState.DISCOVERED
          )
          modules_dict[module_name] = module_info
          discovered.append(module_name)
        else:
          module_info.manifest = manifest
          module_info.manifest_path = manifest_path
          module_info.path = module_path

        self.config_manager.apply_config_to_module(module_info)

    cycles = detect_dependency_cycles(modules_dict)
    if cycles:
      cycle_str = ' -> '.join(cycles)
      msg = get_message(self.i18n, 'discovery.cycles_detected',
              cycles=cycle_str)
      logger.error(msg, component="module_manager")
      for module_name in cycles:
        if module_name in modules_dict:
          modules_dict[module_name].enabled = False
          modules_dict[module_name].state = ModuleState.ERROR
          modules_dict[module_name].last_error = f"Circular dependency detected: {cycle_str}"
          logger.warning(
            "Module '%s' disabled due to circular dependency",
            module_name, component="module_manager"
          )

    await self.events.emit_event(SystemEvent(
      timestamp=datetime.now(timezone.utc),
      source="module_manager",
      event_type="discovery_completed",
      details={"discovered": len(discovered), "total": len(modules_dict)}
    ))

    msg = get_message(self.i18n, 'discovery.completed',
             new_count=len(discovered),
             total_count=len(modules_dict))
    logger.info(msg, component="module_manager")

    return discovered
