"""
────────────────────────────────────
Server Nexe
Author: Jordi Goy
Location: core/loader/registry.py
Description: Central module registry (singleton, thread-safe).

www.jgoy.net · https://server-nexe.org
────────────────────────────────────
"""

import asyncio
import logging
from typing import Dict, Any, List, Optional, TYPE_CHECKING
from dataclasses import dataclass, field
from datetime import datetime, timezone
import threading

from .protocol import (
  ModuleStatus,
  HealthStatus,
  HealthResult,
  ModuleMetadata,
  NexeModule,
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
  Information about a registered module in the system.

  Combines discovery info with runtime state.
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
    """Convert to dictionary for API responses."""
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
  Central registry for all system modules.

  Thread-safe singleton that stores:
  - Discovered modules (to be loaded)
  - Loaded modules (active instances)
  - Modules with routers (to register in FastAPI)
  - Modules with specialists (for routing)
  """

  _instance: Optional["ModuleRegistry"] = None
  _lock = threading.Lock()

  def __new__(cls) -> "ModuleRegistry":
    """Singleton pattern (thread-safe)."""
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
    Reset the registry. Use only in tests.

    WARNING: This removes all registered modules!
    """
    self._modules.clear()
    self._by_quadrant.clear()
    self._by_type.clear()
    self._with_router.clear()
    self._with_specialists.clear()
    logger.warning("ModuleRegistry reset - all modules cleared")

  async def register(self, discovery: ModuleDiscovery) -> RegisteredModule:
    """
    Register a discovered module.

    Args:
      discovery: Discovered module info

    Returns:
      Created RegisteredModule
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
    Assign an instance to a registered module.

    Args:
      name: Module name
      instance: Module instance
      status: Status to assign

    Returns:
      True if assigned successfully
    """
    async with self._registry_lock:
      if name not in self._modules:
        logger.error("Cannot set instance: module %s not registered", name)
        return False

      registered = self._modules[name]
      registered.instance = instance
      registered.status = status
      registered.load_time = datetime.now(timezone.utc)

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
    Update a module's status.

    Args:
      name: Module name
      status: New status
      error: Error message (optional)

    Returns:
      True if updated
    """
    if name not in self._modules:
      return False

    self._modules[name].status = status
    self._modules[name].error_message = error
    return True

  async def set_health(self, name: str, result: HealthResult) -> bool:
    """
    Update a module's health check result.

    Args:
      name: Module name
      result: Health check result

    Returns:
      True if updated
    """
    if name not in self._modules:
      return False

    self._modules[name].last_health_check = datetime.now(timezone.utc)
    self._modules[name].last_health_result = result
    return True

  def get(self, name: str) -> Optional[RegisteredModule]:
    """Get a module by name."""
    return self._modules.get(name)

  def get_instance(self, name: str) -> Optional[NexeModule]:
    """Get a module's instance."""
    registered = self._modules.get(name)
    if registered:
      return registered.instance
    return None

  def get_all(self) -> List[RegisteredModule]:
    """Return all registered modules."""
    return list(self._modules.values())

  def get_loaded(self) -> List[RegisteredModule]:
    """Return only loaded modules (with instance)."""
    return [m for m in self._modules.values() if m.is_loaded]

  def get_by_quadrant(self, quadrant: str) -> List[RegisteredModule]:
    """Return modules from a specific quadrant."""
    names = self._by_quadrant.get(quadrant, [])
    return [self._modules[n] for n in names if n in self._modules]

  def get_by_type(self, mod_type: str) -> List[RegisteredModule]:
    """Return modules of a specific type."""
    names = self._by_type.get(mod_type, [])
    return [self._modules[n] for n in names if n in self._modules]

  def get_with_router(self) -> List[RegisteredModule]:
    """Return modules that have an HTTP router."""
    return [self._modules[n] for n in self._with_router if n in self._modules]

  def get_with_specialists(self) -> List[RegisteredModule]:
    """Return modules that manage specialists."""
    return [self._modules[n] for n in self._with_specialists if n in self._modules]

  def get_routers(self) -> List[tuple]:
    """
    Return all routers to register in FastAPI.

    Returns:
      List of (router, prefix) tuples
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
    """Return registry statistics."""
    return {
      "total": len(self._modules),
      "loaded": len(self.get_loaded()),
      "with_router": len(self._with_router),
      "with_specialists": len(self._with_specialists),
      "by_quadrant": {q: len(names) for q, names in self._by_quadrant.items()},
      "by_type": {t: len(names) for t, names in self._by_type.items()},
    }

  def to_dict(self) -> Dict[str, Any]:
    """Return registry as dictionary for API responses."""
    return {
      "modules": [m.to_dict() for m in self._modules.values()],
      "stats": self.count()
    }

_registry: Optional[ModuleRegistry] = None

def get_registry() -> ModuleRegistry:
  """
  Get the global module registry singleton.

  Returns:
    ModuleRegistry singleton
  """
  global _registry
  if _registry is None:
    _registry = ModuleRegistry()
  return _registry
