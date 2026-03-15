"""
────────────────────────────────────
Server Nexe
Version: 0.8
Author: Jordi Goy 
Location: core/loader/loader.py
Description: No description available.

www.jgoy.net · https://server-nexe.org
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
  """Error during module loading."""
  pass

class ModuleLoader:
  """
  Loads and initializes Nexe modules.

  Loading process:
  1. Scans the filesystem for manifest.toml files
  2. Registers discovered modules
  3. Loads (imports) Python modules
  4. Validates NexeModule Protocol compliance
  5. Initializes modules with context
  """

  def __init__(
    self,
    base_path: Optional[Path] = None,
    registry: Optional[ModuleRegistry] = None,
    context: Optional[Dict[str, Any]] = None
  ):
    """
    Initialize the loader.

    Args:
      base_path: Project root directory
      registry: Module registry (uses singleton if not provided)
      context: Context passed to modules during initialization
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
    Discover all available modules.

    Returns:
      List of discovered modules
    """
    discoveries = self.scanner.scan()

    for discovery in discoveries:
      await self.registry.register(discovery)

    logger.info("Discovered %d modules", len(discoveries))
    return discoveries

  async def load_module(self, name: str) -> Optional[NexeModule]:
    """
    Load a module by name.

    Args:
      name: Module name to load

    Returns:
      Module instance or None on failure
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
    Initialize a loaded module.

    Args:
      name: Module name

    Returns:
      True if initialization succeeded
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
    Load and initialize a module.

    Args:
      name: Module name

    Returns:
      True if both steps succeeded
    """
    instance = await self.load_module(name)
    if not instance:
      return False

    return await self.initialize_module(name)

  async def load_all(self) -> Dict[str, bool]:
    """
    Load all discovered modules.

    Returns:
      Dict mapping module name -> success
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
    Shut down a module.

    Args:
      name: Module name

    Returns:
      True if shutdown succeeded
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
    Shut down all loaded modules.

    Returns:
      Dict mapping module name -> success
    """
    results = {}

    for registered in reversed(self.registry.get_loaded()):
      name = registered.name
      success = await self.shutdown_module(name)
      results[name] = success

    return results

  async def health_check_module(self, name: str) -> HealthResult:
    """
    Run health check for a module.

    Args:
      name: Module name

    Returns:
      HealthResult with current status
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
    Run health check for all modules.

    Returns:
      Dict mapping module name -> HealthResult
    """
    results = {}

    for registered in self.registry.get_loaded():
      name = registered.name
      result = await self.health_check_module(name)
      results[name] = result

    return results

  def _import_module(self, discovery: ModuleDiscovery) -> Optional[NexeModule]:
    """
    Import a Python module and return an instance.

    Args:
      discovery: Module discovery info

    Returns:
      Module instance or None
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
          attr.__module__ == module.__name__ and
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
    Add a service to the context.

    Args:
      key: Service name
      value: Service value/instance
    """
    self.context[key] = value

_loader: Optional[ModuleLoader] = None

def get_loader() -> ModuleLoader:
  """
  Get the global loader singleton.

  Returns:
    ModuleLoader singleton
  """
  global _loader
  if _loader is None:
    _loader = ModuleLoader()
  return _loader


def reset_loader() -> None:
  """Reset the loader singleton. Use only in tests."""
  global _loader
  _loader = None

async def bootstrap(
  context: Optional[Dict[str, Any]] = None,
  auto_load: bool = True
) -> ModuleLoader:
  """
  Initialize the module system.

  Args:
    context: Initial context for modules
    auto_load: If True, automatically load all discovered modules

  Returns:
    Initialized ModuleLoader
  """
  loader = get_loader()

  if context:
    for key, value in context.items():
      loader.set_context(key, value)

  await loader.discover()

  if auto_load:
    await loader.load_all()

  return loader