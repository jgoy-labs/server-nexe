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

    # Bug 12 (2026-04-06) — abans s'executava discover() dos cops al startup:
    # un cop sync des de core/server/factory_modules.py (pel routing) i un
    # altre cop async des de core/lifespan.py (pel bootstrap). Ara, si els
    # mòduls ja estan descoberts i no es força, fem un early return curt.
    # Els tests sempre passen per aquesta funció amb force=True (via la
    # branca anterior), així que no queden afectats.
    if not force and modules_dict:
      logger.info(
        "Module discovery skipped: %d modules already known (use force=True to rediscover)",
        len(modules_dict),
        component="module_manager",
      )
      return list(modules_dict.keys())

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
      # Bug 20 fix — abans nomes hi havia un logger.error generic;
      # ara afegim un missatge explicit i visible amb la cadena
      # completa del cicle, i el guardem a `_cycle_warnings` perque
      # qui imprimeixi el startup summary el pugui mostrar amb prefix
      # [WARN] (els modules afectats queden enabled=False com abans).
      logger.error(
        "Module dependency cycle detected: %s "
        "(modules disabled: %s)",
        cycle_str, ", ".join(cycles),
        component="module_manager",
      )
      msg = get_message(self.i18n, 'discovery.cycles_detected',
              cycles=cycle_str)
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
