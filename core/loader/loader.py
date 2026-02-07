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

from personality.i18n.resolve import t_modular

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

def _t(key: str, fallback: str, **kwargs) -> str:
  return t_modular(f"core.loader.{key}", fallback, **kwargs)

class ModuleLoadError(Exception):
  """Error during module loading."""
  pass

class ModuleLoader:
  """
  Load and initialize Nexe modules.

  Loading process:
  1. Scan the system for manifest.toml
  2. Register discovered modules
  3. Load (import) Python modules
  4. Validate they implement the NexeModule Protocol
  5. Initialize modules with the context
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
      context: Context to pass to modules during initialization
    """
    self.base_path = base_path or Path(__file__).parent.parent.parent
    self.registry = registry or get_registry()
    self.context = context or {}

    self.scanner = ModuleScanner(base_path=self.base_path)

    logger.info(_t(
      "initialized",
      "ModuleLoader initialized - base_path={path}",
      path=self.base_path
    ))

  async def discover(self) -> List[ModuleDiscovery]:
    """
    Discover all available modules.

    Returns:
      List of discovered modules
    """
    discoveries = self.scanner.scan()

    for discovery in discoveries:
      await self.registry.register(discovery)

    logger.info(_t("discovered", "Discovered {count} modules", count=len(discoveries)))
    return discoveries

  async def load_module(self, name: str) -> Optional[NexeModule]:
    """
    Load a module by name.

    Args:
      name: Module name to load

    Returns:
      Module instance or None if it fails
    """
    registered = self.registry.get(name)
    if not registered:
      logger.error(_t("module_not_found", "Module {module} not found in registry", module=name))
      return None

    if registered.is_loaded:
      logger.debug(_t("module_already_loaded", "Module {module} already loaded", module=name))
      return registered.instance

    try:
      await self.registry.set_status(name, ModuleStatus.LOADING)

      instance = self._import_module(registered.discovery)

      if instance is None:
        raise ModuleLoadError(
          _t(
            "import_failed",
            "Failed to import module {module}",
            module=name,
          )
        )

      if not validate_module(instance):
        raise ModuleLoadError(
          _t(
            "invalid_protocol",
            "Module {module} does not implement NexeModule Protocol",
            module=name,
          )
        )

      await self.registry.set_instance(name, instance)

      logger.info(_t("module_loaded", "Module {module} loaded successfully", module=name))
      return instance

    except Exception as e:
      error_msg = str(e)
      await self.registry.set_status(name, ModuleStatus.FAILED, error_msg)
      logger.error(_t(
        "module_load_failed",
        "Failed to load module {module}: {error}",
        module=name,
        error=error_msg
      ))
      return None

  async def initialize_module(self, name: str) -> bool:
    """
    Initialize a loaded module.

    Args:
      name: Module name

    Returns:
      True if initialization succeeds
    """
    registered = self.registry.get(name)
    if not registered or not registered.instance:
      logger.error(_t(
        "module_not_loaded",
        "Module {module} not loaded, cannot initialize",
        module=name
      ))
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
        logger.info(_t("module_initialized", "Module {module} initialized", module=name))
      else:
        await self.registry.set_status(
          name,
          ModuleStatus.FAILED,
          "Initialization returned False"
        )

      return success

    except Exception as e:
      await self.registry.set_status(name, ModuleStatus.FAILED, str(e))
      logger.error(_t(
        "module_init_failed",
        "Failed to initialize module {module}: {error}",
        module=name,
        error=str(e)
      ))
      return False

  async def load_and_initialize(self, name: str) -> bool:
    """
    Load and initialize a module.

    Args:
      name: Module name

    Returns:
      True if everything succeeded
    """
    instance = await self.load_module(name)
    if not instance:
      return False

    return await self.initialize_module(name)

  async def load_all(self) -> Dict[str, bool]:
    """
    Load all discovered modules.

    Returns:
      Dict of name -> success for each module
    """
    results = {}

    for registered in self.registry.get_all():
      name = registered.name
      success = await self.load_and_initialize(name)
      results[name] = success

    loaded = sum(1 for v in results.values() if v)
    logger.info(_t(
      "modules_loaded_summary",
      "Loaded {loaded}/{total} modules",
      loaded=loaded,
      total=len(results)
    ))

    return results

  async def shutdown_module(self, name: str) -> bool:
    """
    Stop a module.

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
      logger.info(_t("module_shutdown_complete", "Module {module} shutdown complete", module=name))
      return True

    except Exception as e:
      logger.error(_t(
        "module_shutdown_error",
        "Error shutting down module {module}: {error}",
        module=name,
        error=str(e)
      ))
      return False

  async def shutdown_all(self) -> Dict[str, bool]:
    """
    Stop all loaded modules.

    Returns:
      Dict of name -> success for each module
    """
    results = {}

    for registered in reversed(self.registry.get_loaded()):
      name = registered.name
      success = await self.shutdown_module(name)
      results[name] = success

    return results

  async def health_check_module(self, name: str) -> HealthResult:
    """
    Run a health check for a module.

    Args:
      name: Module name

    Returns:
      HealthResult with the status
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
    Run health checks for all modules.

    Returns:
      Dict of name -> HealthResult
    """
    results = {}

    for registered in self.registry.get_loaded():
      name = registered.name
      result = await self.health_check_module(name)
      results[name] = result

    return results

  def _import_module(self, discovery: ModuleDiscovery) -> Optional[NexeModule]:
    """
    Import a Python module and return the instance.

    Args:
      discovery: Module information

    Returns:
      Module instance or None
    """
    entry_module = discovery.entry_module
    entry_class = discovery.entry_class

    if not entry_module:
      logger.error(
        _t(
          "entry_module_missing",
          "No entry_module specified for {module}",
          module=discovery.metadata.name,
        )
      )
      return None

    try:
      module = importlib.import_module(entry_module)

      if entry_class:
        if not hasattr(module, entry_class):
          logger.error(
            _t(
              "entry_class_missing",
              "Class {class_name} not found in {module}",
              class_name=entry_class,
              module=entry_module,
            )
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
        _t(
          "no_valid_module",
          "No valid NexeModule found in {module}",
          module=entry_module,
        )
      )
      return None

    except ImportError as e:
      logger.error(_t(
        "cannot_import",
        "Cannot import {module}: {error}",
        module=entry_module,
        error=str(e)
      ))
      return None
    except Exception as e:
      logger.error(_t(
        "error_loading",
        "Error loading {module}: {error}",
        module=entry_module,
        error=str(e)
      ))
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
  Get the global loader.

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
  Initialize the module system.

  Args:
    context: Initial context for modules
    auto_load: If True, automatically load all modules

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
