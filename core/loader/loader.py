"""
────────────────────────────────────
Server Nexe
Version: 0.8
Author: Jordi Goy 
Location: core/loader/loader.py
Description: No description available.

www.jgoy.net
────────────────────────────────────
"""

import asyncio
import importlib
import logging
from pathlib import Path
from typing import Dict, Any, List, Optional, Type

from .protocol import (
  NexeModule,
  ModuleStatus,
  HealthStatus,
  HealthResult,
  validate_module
)
from .scanner import ModuleScanner, ModuleDiscovery
from .registry import ModuleRegistry, RegisteredModule, get_registry

logger = logging.getLogger(__name__)

class ModuleLoadError(Exception):
  """Error durant la càrrega d'un mòdul"""
  pass

class ModuleLoader:
  """
  Carrega i inicialitza mòduls Nexe.

  Procés de càrrega:
  1. Escaneja el sistema cercant manifest.toml
  2. Registra els mòduls descoberts
  3. Carrega (importa) els mòduls Python
  4. Valida que compleixen el NexeModule Protocol
  5. Inicialitza els mòduls amb el context
  """

  def __init__(
    self,
    base_path: Optional[Path] = None,
    registry: Optional[ModuleRegistry] = None,
    context: Optional[Dict[str, Any]] = None
  ):
    """
    Inicialitza el loader.

    Args:
      base_path: Directori arrel del projecte
      registry: Registre de mòduls (usa singleton si no es proporciona)
      context: Context per passar als mòduls durant inicialització
    """
    self.base_path = base_path or Path(__file__).parent.parent.parent
    self.registry = registry or get_registry()
    self.context = context or {}

    self.scanner = ModuleScanner(base_path=self.base_path)

    logger.info(
      "ModuleLoader initialized - base_path=%s",
      self.base_path
    )

  async def discover(self) -> List[ModuleDiscovery]:
    """
    Descobreix tots els mòduls disponibles.

    Returns:
      Llista de mòduls descoberts
    """
    discoveries = self.scanner.scan()

    for discovery in discoveries:
      await self.registry.register(discovery)

    logger.info("Discovered %d modules", len(discoveries))
    return discoveries

  async def load_module(self, name: str) -> Optional[NexeModule]:
    """
    Carrega un mòdul pel seu nom.

    Args:
      name: Nom del mòdul a carregar

    Returns:
      Instància del mòdul o None si falla
    """
    registered = self.registry.get(name)
    if not registered:
      logger.error("Module %s not found in registry", name)
      return None

    if registered.is_loaded:
      logger.debug("Module %s already loaded", name)
      return registered.instance

    try:
      await self.registry.set_status(name, ModuleStatus.LOADING)

      instance = self._import_module(registered.discovery)

      if instance is None:
        raise ModuleLoadError(f"Failed to import module {name}")

      if not validate_module(instance):
        raise ModuleLoadError(
          f"Module {name} does not implement NexeModule Protocol"
        )

      await self.registry.set_instance(name, instance)

      logger.info("Module %s loaded successfully", name)
      return instance

    except Exception as e:
      error_msg = str(e)
      await self.registry.set_status(name, ModuleStatus.FAILED, error_msg)
      logger.error("Failed to load module %s: %s", name, error_msg)
      return None

  async def initialize_module(self, name: str) -> bool:
    """
    Inicialitza un mòdul carregat.

    Args:
      name: Nom del mòdul

    Returns:
      True si la inicialització és correcta
    """
    registered = self.registry.get(name)
    if not registered or not registered.instance:
      logger.error("Module %s not loaded, cannot initialize", name)
      return False

    try:
      module_context = {
        **self.context,
        "modules": self.registry,
        "module_name": name,
      }

      success = await registered.instance.initialize(module_context)

      if success:
        await self.registry.set_status(name, ModuleStatus.RUNNING)
        logger.info("Module %s initialized", name)
      else:
        await self.registry.set_status(
          name,
          ModuleStatus.FAILED,
          "Initialization returned False"
        )

      return success

    except Exception as e:
      await self.registry.set_status(name, ModuleStatus.FAILED, str(e))
      logger.error("Failed to initialize module %s: %s", name, str(e))
      return False

  async def load_and_initialize(self, name: str) -> bool:
    """
    Carrega i inicialitza un mòdul.

    Args:
      name: Nom del mòdul

    Returns:
      True si tot ha anat bé
    """
    instance = await self.load_module(name)
    if not instance:
      return False

    return await self.initialize_module(name)

  async def load_all(self) -> Dict[str, bool]:
    """
    Carrega tots els mòduls descoberts.

    Returns:
      Dict amb nom -> èxit de cada mòdul
    """
    results = {}

    for registered in self.registry.get_all():
      name = registered.name
      success = await self.load_and_initialize(name)
      results[name] = success

    loaded = sum(1 for v in results.values() if v)
    logger.info("Loaded %d/%d modules", loaded, len(results))

    return results

  async def shutdown_module(self, name: str) -> bool:
    """
    Atura un mòdul.

    Args:
      name: Nom del mòdul

    Returns:
      True si s'ha aturat correctament
    """
    registered = self.registry.get(name)
    if not registered or not registered.instance:
      return True

    try:
      await registered.instance.shutdown()
      await self.registry.set_status(name, ModuleStatus.STOPPED)
      logger.info("Module %s shutdown complete", name)
      return True

    except Exception as e:
      logger.error("Error shutting down module %s: %s", name, str(e))
      return False

  async def shutdown_all(self) -> Dict[str, bool]:
    """
    Atura tots els mòduls carregats.

    Returns:
      Dict amb nom -> èxit de cada mòdul
    """
    results = {}

    for registered in reversed(self.registry.get_loaded()):
      name = registered.name
      success = await self.shutdown_module(name)
      results[name] = success

    return results

  async def health_check_module(self, name: str) -> HealthResult:
    """
    Executa health check d'un mòdul.

    Args:
      name: Nom del mòdul

    Returns:
      HealthResult amb l'estat
    """
    registered = self.registry.get(name)

    if not registered:
      return HealthResult(
        status=HealthStatus.UNKNOWN,
        message=f"Module {name} not found"
      )

    if not registered.instance:
      return HealthResult(
        status=HealthStatus.UNKNOWN,
        message=f"Module {name} not loaded"
      )

    try:
      result = await registered.instance.health_check()
      await self.registry.set_health(name, result)
      return result

    except Exception as e:
      result = HealthResult(
        status=HealthStatus.UNHEALTHY,
        message=f"Health check failed: {str(e)}"
      )
      await self.registry.set_health(name, result)
      return result

  async def health_check_all(self) -> Dict[str, HealthResult]:
    """
    Executa health check de tots els mòduls.

    Returns:
      Dict amb nom -> HealthResult
    """
    results = {}

    for registered in self.registry.get_loaded():
      name = registered.name
      result = await self.health_check_module(name)
      results[name] = result

    return results

  def _import_module(self, discovery: ModuleDiscovery) -> Optional[NexeModule]:
    """
    Importa un mòdul Python i retorna la instància.

    Args:
      discovery: Informació del mòdul

    Returns:
      Instància del mòdul o None
    """
    entry_module = discovery.entry_module
    entry_class = discovery.entry_class

    if not entry_module:
      logger.error(
        "No entry_module specified for %s",
        discovery.metadata.name
      )
      return None

    try:
      module = importlib.import_module(entry_module)

      if entry_class:
        if not hasattr(module, entry_class):
          logger.error(
            "Class %s not found in %s",
            entry_class,
            entry_module
          )
          return None

        cls = getattr(module, entry_class)
        return cls()

      for attr_name in dir(module):
        attr = getattr(module, attr_name)
        if (
          isinstance(attr, type) and
          attr_name != "NexeModule" and
          validate_module
        ):
          try:
            instance = attr()
            if validate_module(instance):
              return instance
          except Exception:
            continue

      logger.error(
        "No valid NexeModule found in %s",
        entry_module
      )
      return None

    except ImportError as e:
      logger.error("Cannot import %s: %s", entry_module, str(e))
      return None
    except Exception as e:
      logger.error("Error loading %s: %s", entry_module, str(e))
      return None

  def set_context(self, key: str, value: Any) -> None:
    """
    Afegeix un servei al context.

    Args:
      key: Nom del servei
      value: Valor/instància del servei
    """
    self.context[key] = value

_loader: Optional[ModuleLoader] = None

def get_loader() -> ModuleLoader:
  """
  Obté el loader global.

  Returns:
    ModuleLoader singleton
  """
  global _loader
  if _loader is None:
    _loader = ModuleLoader()
  return _loader

async def bootstrap(
  context: Optional[Dict[str, Any]] = None,
  auto_load: bool = True
) -> ModuleLoader:
  """
  Inicialitza el sistema de mòduls.

  Args:
    context: Context inicial per als mòduls
    auto_load: Si True, carrega automàticament tots els mòduls

  Returns:
    ModuleLoader inicialitzat
  """
  loader = get_loader()

  if context:
    for key, value in context.items():
      loader.set_context(key, value)

  await loader.discover()

  if auto_load:
    await loader.load_all()

  return loader