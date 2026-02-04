"""
────────────────────────────────────
Server Nexe
Version: 0.8
Author: Jordi Goy 
Location: core/loader/registry.py
Description: No description available.

www.jgoy.net
────────────────────────────────────
"""

import asyncio
import logging
from typing import Dict, Any, List, Optional, TYPE_CHECKING
from dataclasses import dataclass, field
from datetime import datetime
import threading

from .protocol import (
  ModuleStatus,
  HealthStatus,
  HealthResult,
  ModuleMetadata,
  NexeModule,
  NexeModuleWithRouter,
  NexeModuleWithSpecialists,
  module_has_router,
  module_has_specialists
)
from .scanner import ModuleDiscovery

if TYPE_CHECKING:
  from fastapi import APIRouter

logger = logging.getLogger(__name__)

@dataclass
class RegisteredModule:
  """
  Informació d'un mòdul registrat al sistema.

  Combina la informació de descobriment amb l'estat runtime.
  """
  discovery: ModuleDiscovery
  instance: Optional[NexeModule] = None
  status: ModuleStatus = ModuleStatus.DISCOVERED
  last_health_check: Optional[datetime] = None
  last_health_result: Optional[HealthResult] = None
  error_message: Optional[str] = None
  load_time: Optional[datetime] = None

  @property
  def name(self) -> str:
    return self.discovery.metadata.name

  @property
  def metadata(self) -> ModuleMetadata:
    return self.discovery.metadata

  @property
  def is_loaded(self) -> bool:
    return self.instance is not None

  @property
  def is_healthy(self) -> bool:
    if self.last_health_result is None:
      return False
    return self.last_health_result.status == HealthStatus.HEALTHY

  def to_dict(self) -> Dict[str, Any]:
    """Converteix a diccionari per API"""
    return {
      "name": self.name,
      "version": self.metadata.version,
      "status": self.status.value,
      "is_loaded": self.is_loaded,
      "is_healthy": self.is_healthy,
      "load_time": self.load_time.isoformat() if self.load_time else None,
      "last_health_check": self.last_health_check.isoformat() if self.last_health_check else None,
      "error": self.error_message,
      "discovery": self.discovery.to_dict()
    }

class ModuleRegistry:
  """
  Registre central de tots els mòduls del sistema.

  Singleton thread-safe que emmagatzema:
  - Mòduls descoberts (per carregar)
  - Mòduls carregats (instàncies actives)
  - Mòduls amb routers (per registrar a FastAPI)
  - Mòduls amb specialists (per routing)
  """

  _instance: Optional["ModuleRegistry"] = None
  _lock = threading.Lock()

  def __new__(cls) -> "ModuleRegistry":
    """Singleton pattern thread-safe"""
    with cls._lock:
      if cls._instance is None:
        cls._instance = super().__new__(cls)
        cls._instance._initialized = False
      return cls._instance

  def __init__(self):
    if self._initialized:
      return

    self._modules: Dict[str, RegisteredModule] = {}

    self._by_quadrant: Dict[str, List[str]] = {}
    self._by_type: Dict[str, List[str]] = {}
    self._with_router: List[str] = []
    self._with_specialists: List[str] = []

    self._registry_lock = asyncio.Lock()

    self._initialized = True
    logger.info("ModuleRegistry initialized")

  def reset(self) -> None:
    """
    Reseteja el registre (útil per tests).

    PERILL: Això elimina tots els mòduls registrats!
    """
    self._modules.clear()
    self._by_quadrant.clear()
    self._by_type.clear()
    self._with_router.clear()
    self._with_specialists.clear()
    logger.warning("ModuleRegistry reset - all modules cleared")

  async def register(self, discovery: ModuleDiscovery) -> RegisteredModule:
    """
    Registra un mòdul descobert.

    Args:
      discovery: Informació del mòdul descobert

    Returns:
      RegisteredModule creat
    """
    async with self._registry_lock:
      name = discovery.metadata.name

      if name in self._modules:
        logger.warning("Module %s already registered, skipping", name)
        return self._modules[name]

      registered = RegisteredModule(
        discovery=discovery,
        status=ModuleStatus.DISCOVERED
      )

      self._modules[name] = registered

      quadrant = discovery.metadata.quadrant
      if quadrant not in self._by_quadrant:
        self._by_quadrant[quadrant] = []
      self._by_quadrant[quadrant].append(name)

      mod_type = discovery.metadata.module_type
      if mod_type not in self._by_type:
        self._by_type[mod_type] = []
      self._by_type[mod_type].append(name)

      logger.info(
        "Registered module: %s v%s (%s/%s)",
        name,
        discovery.metadata.version,
        quadrant,
        mod_type
      )

      return registered

  async def set_instance(
    self,
    name: str,
    instance: NexeModule,
    status: ModuleStatus = ModuleStatus.INITIALIZED
  ) -> bool:
    """
    Assigna una instància a un mòdul registrat.

    Args:
      name: Nom del mòdul
      instance: Instància del mòdul
      status: Estat a assignar

    Returns:
      True si s'ha assignat correctament
    """
    async with self._registry_lock:
      if name not in self._modules:
        logger.error("Cannot set instance: module %s not registered", name)
        return False

      registered = self._modules[name]
      registered.instance = instance
      registered.status = status
      registered.load_time = datetime.now()

      if module_has_router(instance):
        if name not in self._with_router:
          self._with_router.append(name)

      if module_has_specialists(instance):
        if name not in self._with_specialists:
          self._with_specialists.append(name)

      logger.info("Module %s instance set, status=%s", name, status.value)
      return True

  async def set_status(self, name: str, status: ModuleStatus, error: Optional[str] = None) -> bool:
    """
    Actualitza l'estat d'un mòdul.

    Args:
      name: Nom del mòdul
      status: Nou estat
      error: Missatge d'error (opcional)

    Returns:
      True si s'ha actualitzat
    """
    if name not in self._modules:
      return False

    self._modules[name].status = status
    self._modules[name].error_message = error
    return True

  async def set_health(self, name: str, result: HealthResult) -> bool:
    """
    Actualitza el resultat de health check d'un mòdul.

    Args:
      name: Nom del mòdul
      result: Resultat del health check

    Returns:
      True si s'ha actualitzat
    """
    if name not in self._modules:
      return False

    self._modules[name].last_health_check = datetime.now()
    self._modules[name].last_health_result = result
    return True

  def get(self, name: str) -> Optional[RegisteredModule]:
    """
    Obté un mòdul pel seu nom.

    Args:
      name: Nom del mòdul

    Returns:
      RegisteredModule o None
    """
    return self._modules.get(name)

  def get_instance(self, name: str) -> Optional[NexeModule]:
    """
    Obté la instància d'un mòdul.

    Args:
      name: Nom del mòdul

    Returns:
      Instància o None
    """
    registered = self._modules.get(name)
    if registered:
      return registered.instance
    return None

  def get_all(self) -> List[RegisteredModule]:
    """Retorna tots els mòduls registrats"""
    return list(self._modules.values())

  def get_loaded(self) -> List[RegisteredModule]:
    """Retorna només els mòduls carregats (amb instància)"""
    return [m for m in self._modules.values() if m.is_loaded]

  def get_by_quadrant(self, quadrant: str) -> List[RegisteredModule]:
    """Retorna mòduls d'un quadrant específic"""
    names = self._by_quadrant.get(quadrant, [])
    return [self._modules[n] for n in names if n in self._modules]

  def get_by_type(self, mod_type: str) -> List[RegisteredModule]:
    """Retorna mòduls d'un tipus específic"""
    names = self._by_type.get(mod_type, [])
    return [self._modules[n] for n in names if n in self._modules]

  def get_with_router(self) -> List[RegisteredModule]:
    """Retorna mòduls que tenen router HTTP"""
    return [self._modules[n] for n in self._with_router if n in self._modules]

  def get_with_specialists(self) -> List[RegisteredModule]:
    """Retorna mòduls que gestionen specialists"""
    return [self._modules[n] for n in self._with_specialists if n in self._modules]

  def get_routers(self) -> List[tuple]:
    """
    Retorna tots els routers per registrar a FastAPI.

    Returns:
      Llista de tuples (router, prefix)
    """
    routers = []

    for registered in self.get_with_router():
      if registered.instance and module_has_router(registered.instance):
        try:
          router = registered.instance.get_router()
          prefix = registered.instance.get_router_prefix()
          routers.append((router, prefix))
        except Exception as e:
          logger.error(
            "Failed to get router from %s: %s",
            registered.name,
            str(e)
          )

    return routers

  def count(self) -> Dict[str, int]:
    """Retorna estadístiques del registre"""
    return {
      "total": len(self._modules),
      "loaded": len(self.get_loaded()),
      "with_router": len(self._with_router),
      "with_specialists": len(self._with_specialists),
      "by_quadrant": {q: len(names) for q, names in self._by_quadrant.items()},
      "by_type": {t: len(names) for t, names in self._by_type.items()},
    }

  def to_dict(self) -> Dict[str, Any]:
    """Retorna el registre com a diccionari per API"""
    return {
      "modules": [m.to_dict() for m in self._modules.values()],
      "stats": self.count()
    }

_registry: Optional[ModuleRegistry] = None

def get_registry() -> ModuleRegistry:
  """
  Obté el registre global de mòduls.

  Returns:
    ModuleRegistry singleton
  """
  global _registry
  if _registry is None:
    _registry = ModuleRegistry()
  return _registry