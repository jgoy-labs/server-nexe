"""
────────────────────────────────────
Server Nexe
Author: Jordi Goy 
Location: personality/module_manager/discovery.py
Description: Module discovery component.

www.jgoy.net · https://server-nexe.org
────────────────────────────────────
"""

import os
from datetime import datetime, timezone
from typing import Dict, List, Optional

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
  ) -> None:
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
    # Bug 20 fix — guardem els cicles detectats perque siguin
    # consultables des de fora (startup summary, status endpoints,
    # tests). Sense aixo els modules s'inhabilitaven en silenci.
    self._cycle_warnings: List[str] = []

  def get_cycle_warnings(self) -> List[str]:
    """
    Retorna una copia de la llista de cicles detectats durant el
    descobriment. El consumidor tipic es el startup summary del lifespan,
    que imprimeix cada entry amb prefix [WARN].
    """
    return list(self._cycle_warnings)

  def clear_cycle_warnings(self) -> None:
    """Neteja la llista de cycle warnings (util en re-descobriments)."""
    self._cycle_warnings.clear()

  def _resolve_force_flag(self, force: bool, modules_dict: Dict[str, ModuleInfo]) -> Optional[bool]:
    nexe_env = (os.getenv("NEXE_ENV") or "").lower()
    if nexe_env in ("test", "testing") or os.getenv("PYTEST_CURRENT_TEST"):
      return True
    if not force and modules_dict:
      return None  # sentinel: early-return from caller
    if not force and not self.path_discovery.load_cache():
      return True
    return force

  def _collect_modules_found(self, force: bool) -> dict:
    if force:
      paths = self.path_discovery.discover_all_paths()
      modules_found = self.path_discovery.scan_for_modules(paths)
      self.path_discovery.save_cache()
    else:
      modules_found = self.path_discovery._module_locations
    return modules_found

  def _register_discovered_modules(
    self,
    modules_found: dict,
    modules_dict: Dict[str, ModuleInfo],
    lock,
  ) -> List[str]:
    discovered = []
    with lock:
      for module_name, module_path in modules_found.items():
        manifest_path = self.config_manager.find_manifest(module_name, module_path)
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
    return discovered

  def _handle_dependency_cycles(self, modules_dict: Dict[str, ModuleInfo]) -> None:
    cycles = detect_dependency_cycles(modules_dict)
    if not cycles:
      return
    cycle_str = ' -> '.join(cycles)
    # Bug 20 fix — before there was only a generic logger.error; now we add
    # an explicit message with the full cycle string and store it in
    # `_cycle_warnings` so the startup summary can show it with [WARN].
    logger.error(
      "Module dependency cycle detected: %s (modules disabled: %s)",
      cycle_str, ", ".join(cycles),
      component="module_manager",
    )
    msg = get_message(self.i18n, 'discovery.cycles_detected', cycles=cycle_str)
    logger.error(msg, component="module_manager")
    self._cycle_warnings.append(cycle_str)
    for module_name in cycles:
      if module_name in modules_dict:
        modules_dict[module_name].enabled = False
        modules_dict[module_name].state = ModuleState.ERROR
        modules_dict[module_name].last_error = f"Circular dependency detected: {cycle_str}"
        logger.warning(
          "Module '%s' disabled due to circular dependency",
          module_name, component="module_manager"
        )

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

    # Bug 12 (2026-04-06) — before discover() ran twice at startup.
    # Now if modules are already known and not forced, do an early return.
    # Tests always pass with force=True (via NEXE_ENV/PYTEST_CURRENT_TEST).
    resolved = self._resolve_force_flag(force, modules_dict)
    if resolved is None:
      logger.info(
        "Module discovery skipped: %d modules already known (use force=True to rediscover)",
        len(modules_dict),
        component="module_manager",
      )
      return list(modules_dict.keys())
    force = resolved

    modules_found = self._collect_modules_found(force)
    discovered = self._register_discovered_modules(modules_found, modules_dict, lock)
    self._handle_dependency_cycles(modules_dict)

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
