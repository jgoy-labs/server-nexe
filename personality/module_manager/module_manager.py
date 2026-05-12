"""
────────────────────────────────────
Server Nexe
Author: Jordi Goy 
Location: personality/module_manager/module_manager.py
Description: Central facade of the Nexe 0.9 module management system.

www.jgoy.net · https://server-nexe.org
────────────────────────────────────
"""

import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Optional, Any

from personality.data.models import ModuleInfo, ModuleState
from personality.i18n.i18n_manager import I18nManager
from personality.events.event_system import EventSystem
from personality.metrics.metrics_collector import MetricsCollector
from personality.loading.loader import ModuleLoader

from .path_discovery import PathDiscovery
from .registry import ModuleRegistry
from .config_manager import ConfigManager
from .module_lifecycle import ModuleLifecycleManager
from .system_lifecycle import SystemLifecycleManager
from .discovery import ModuleDiscovery
from .sync_wrapper import SyncWrapper
from .messages import get_message
from .types import DiscoveryConfig, LifecycleConfig, SystemLifecycleConfig
from .plugin_loader import PluginLoaderMixin

try:
  from plugins.security.core.validators import validate_safe_path
  SECURITY_VALIDATION_AVAILABLE = True
except ImportError:
  SECURITY_VALIDATION_AVAILABLE = False

from personality._logger import get_logger
logger = get_logger(__name__)

if not SECURITY_VALIDATION_AVAILABLE:
  logger.warning("Security validation not available - validate_safe_path not found")

class ModuleManager(PluginLoaderMixin):
  """
  UNIFIED Module Manager for Nexe 0.9 system (SINGLE SOURCE OF TRUTH).

  This is the ONLY module loading system. All module operations go through here:
  - Plugin modules (plugins/*)
  - Memory modules (memory/*)
  - Core modules (core/*)

  Coordinates specialized components:
  - ConfigManager: Configuration and manifest management
  - PathDiscovery: Module path discovery
  - ModuleDiscovery: Discovery logic
  - ModuleLoader: Dynamic module loading
  - ModuleRegistry: Module registry and indexing
  - ModuleLifecycleManager: Individual module lifecycle
  - SystemLifecycleManager: System lifecycle
  - SyncWrapper: Synchronous wrappers for async operations
  - EventSystem: Event management
  - MetricsCollector: Metrics collection
  - I18nManager: Internationalization

  See: docs/NEXE_ARCHITECTURAL_DECISIONS.md (ADR-001)
  """

  def __init__(self, config_path: Optional[Path] = None):
    """
    Initialize module manager with all components.

    Args:
      config_path: Path to the server.toml file
    """
    temp_config_path = self._find_initial_config(config_path)
    self.i18n = I18nManager(temp_config_path, temp_config_path.parent)

    self.config_manager = ConfigManager(config_path, self.i18n)
    self.config_path = self.config_manager.config_path
    self.manifests_path = self.config_manager.manifests_path

    self.events = EventSystem(self.i18n)
    self.metrics = MetricsCollector(self.i18n)
    self.registry = ModuleRegistry(self.i18n)
    # suppress_deprecation=True because ModuleManager is the primary user
    self.loader = ModuleLoader(self.i18n, suppress_deprecation=True)
    self.path_discovery = PathDiscovery(
      self.config_manager.get_config(), self.i18n
    )

    self._configure_base_path()

    self._modules: Dict[str, ModuleInfo] = {}
    self._running = False
    self._lock = threading.RLock()
    self._system_start_time = datetime.now(timezone.utc)

    self.discovery = ModuleDiscovery(DiscoveryConfig(
      path_discovery=self.path_discovery,
      config_manager=self.config_manager,
      events=self.events,
      i18n=self.i18n,
    ))
    self.sync_wrapper = SyncWrapper(self.i18n)

    self.module_lifecycle = ModuleLifecycleManager(LifecycleConfig(
      modules=self._modules,
      loader=self.loader,
      registry=self.registry,
      events=self.events,
      metrics=self.metrics,
      i18n=self.i18n,
    ))
    self.system_lifecycle = SystemLifecycleManager(SystemLifecycleConfig(
      modules=self._modules,
      module_lifecycle=self.module_lifecycle,
      discovery_func=self.discover_modules,
      list_modules_func=self.list_modules,
      i18n=self.i18n,
    ))

    self.api_integrator = None

    self._log_init()

  def _configure_base_path(self) -> None:
    """Configure base_path for PathDiscovery."""
    if self.config_path.parent.name == "personality":
      self.path_discovery.base_path = self.config_path.parent.parent
    else:
      self.path_discovery.base_path = self.config_path.parent

  def _find_initial_config(self, config_path: Optional[Path]) -> Path:
    """
    Initial configuration search with security validation.
    """
    if config_path:
      config_path = Path(config_path)
      if SECURITY_VALIDATION_AVAILABLE:
        try:
          base_path = Path.cwd()
          validated_path = validate_safe_path(config_path, base_path)  # pyright: ignore[reportPossiblyUnboundVariable]  # imported under SECURITY_VALIDATION_AVAILABLE guard above
          if validated_path.exists():
            return validated_path
        except Exception as e:
          logger.warning("Config path rejected (security): %s - %s", config_path, e)
      else:
        if config_path.exists():
          return config_path

    for path in [
      Path("server.toml"),
      Path("personality/server.toml"),
      Path("config/server.toml"),
      Path("../server.toml"),
      Path("../../server.toml")
    ]:
      if path.exists():
        return path.resolve()

    return Path("personality/server.toml")

  def _log_init(self) -> None:
    """Log initialization."""
    logger.info(get_message(self.i18n, 'init.started'), component="module_manager")
    logger.info(get_message(self.i18n, 'init.config_loaded', path=str(self.config_path)))

  async def discover_modules(self, force: bool = False) -> List[str]:
    """Discover available modules."""
    return await self.discovery.discover(self._modules, self._lock, force)

  def get_cycle_warnings(self) -> List[str]:
    """
    Return dependency cycles detected during the last discover call.
    Bug 20 fix — exposed so the lifespan startup summary (and tests)
    can read and display them with a [WARN] prefix.
    """
    return self.discovery.get_cycle_warnings()

  def discover_modules_sync(self, force: bool = False) -> List[str]:
    """Synchronous wrapper for discover_modules()."""
    return self.sync_wrapper.run_sync(
      self.discover_modules(force),
      error_msg_key='sync_wrapper_failed'
    )

  async def load_module(self, module_name: str) -> bool:
    """Load a module."""
    with self._lock:
      if module_name not in self._modules:
        await self.discover_modules()
        if module_name not in self._modules:
          msg = get_message(self.i18n, 'loading.not_found', module=module_name)
          logger.error(msg, component="module_manager")
          return False
    return await self.module_lifecycle.load_module(module_name)

  async def start_module(self, module_name: str) -> bool:
    """Start a loaded module."""
    return await self.module_lifecycle.start_module(module_name)

  async def stop_module(self, module_name: str) -> bool:
    """Stop a running module."""
    return await self.module_lifecycle.stop_module(module_name)

  async def start_system(self) -> bool:
    """Start the full system."""
    original_get_lock = self.system_lifecycle._get_lock
    self.system_lifecycle._get_lock = lambda: self._lock  # type: ignore[method-assign]  # lock injection: shares self._lock with system_lifecycle temporarily
    result = await self.system_lifecycle.start_system()
    self._running = self.system_lifecycle.is_running()
    self.system_lifecycle._get_lock = original_get_lock  # type: ignore[method-assign]  # restore original _get_lock after lock sharing
    return result

  async def shutdown_system(self) -> None:
    """Shut down the system."""
    original_get_lock = self.system_lifecycle._get_lock
    self.system_lifecycle._get_lock = lambda: self._lock  # type: ignore[method-assign]  # lock injection: shares self._lock with system_lifecycle temporarily
    await self.system_lifecycle.shutdown_system()
    self._running = self.system_lifecycle.is_running()
    self.system_lifecycle._get_lock = original_get_lock  # type: ignore[method-assign]  # restore original _get_lock after lock sharing

  def get_module_info(self, module_name: str) -> Optional[ModuleInfo]:
    """Get information about a module."""
    return self._modules.get(module_name)

  def update_module_enabled(self, module_name: str, enabled: bool) -> bool:
    """Update the enabled state of a module and persist to config."""
    module = self._modules.get(module_name)
    if not module:
      return False

    if '/core/' in str(module.path) and not enabled:
      logger.warning(f"Cannot disable core module: {module_name}")
      return False

    success = self.config_manager.update_module_enabled(module_name, enabled, module.path)
    if success:
      module.enabled = enabled
      if not enabled:
        module.state = ModuleState.DISABLED
      elif module.state == ModuleState.DISABLED:
        module.state = ModuleState.LOADED

    return success

  def list_modules(self, state_filter: Optional[ModuleState] = None) -> List[ModuleInfo]:
    """List modules, optionally filtered by state."""
    with self._lock:
      modules = list(self._modules.values())
      if state_filter:
        modules = [m for m in modules if m.state == state_filter]
      return sorted(modules, key=lambda m: m.priority)

  def get_system_status(self) -> Dict[str, Any]:
    """Get system status."""
    return {
      "running": self._running,
      "total_modules": len(self._modules),
      "modules_by_state": {
        state.value: len([m for m in self._modules.values() if m.state == state])
        for state in ModuleState
      },
      "metrics": self.metrics.get_system_metrics(self._modules),
      "paths": self.path_discovery.get_stats(),
      "uptime_seconds": (datetime.now(timezone.utc) - self._system_start_time).total_seconds()
    }

  def add_event_listener(self, callback, event_type: Optional[str] = None) -> None:
    """Add an event listener."""
    self.events.add_event_listener(callback, event_type)

  def get_module_metrics(self, module_name: str) -> Dict[str, Any]:
    """Get metrics for a module."""
    if module_name in self._modules:
      return self.metrics.get_module_metrics(self._modules[module_name])
    return {}

  def get_registry_info(self) -> Dict[str, Any]:
    """Get registry information."""
    return self.registry.get_registry_stats()

  def set_api_integrator(self, api_integrator):
    """Set the API integrator."""
    self.api_integrator = api_integrator
    self.module_lifecycle.set_api_integrator(api_integrator)
    logger.info(get_message(self.i18n, 'api.integrator.set'))

  def _resolve_memory_class_name(self, module_name: str) -> str:
    """Resolve the expected class name for a memory module (e.g. 'rag' -> 'RAGModule')."""
    if module_name == "rag":
      return "RAGModule"
    return f"{module_name.capitalize()}Module"

  async def _load_single_memory_module(
    self,
    module_name: str,
    memory_path,
    config: Optional[Dict[Any, Any]],
  ):
    """Import, instantiate, and initialize a single memory module by name."""
    import importlib
    module_path = memory_path / module_name
    manifest_file = module_path / "manifest.py"
    if not manifest_file.exists():
      logger.debug("Memory module manifest not found: %s", manifest_file)
      return None

    manifest_module = importlib.import_module(f"memory.{module_name}.manifest")
    if not hasattr(manifest_module, "MODULE_ID"):
      logger.error("Memory module %s missing MODULE_ID", module_name)
      return None

    module_id = manifest_module.MODULE_ID
    logger.info("Loading memory module: %s (ID: %s)", module_name, module_id)

    module_py = importlib.import_module(f"memory.{module_name}.module")
    module_class_name = self._resolve_memory_class_name(module_name)
    if not hasattr(module_py, module_class_name):
      logger.error("Memory module class not found: %s", module_class_name)
      return None

    module_class = getattr(module_py, module_class_name)
    instance = module_class.get_instance()

    module_config = config.get(module_name) if config else None
    success = await instance.initialize(config=module_config)
    if not success:
      logger.error("Memory module initialization failed: %s", module_name)
      return None

    health_status = instance.get_health().get("status", "unhealthy") if hasattr(instance, 'get_health') else "healthy"
    logger.info("Memory module loaded: %s (ID: %s, health: %s)", module_name, module_id, health_status)

    self.registry.register_module(
      name=module_name,
      instance=instance,
      manifest={"module_id": module_id, "type": "memory"}
    )

    from personality.events.event_system import create_system_event
    event = await create_system_event(
      source="module_manager",
      event_type="module_loaded",
      module=module_name,
      module_id=module_id,
      type="memory"
    )
    await self.events.emit_event(event)

    return module_id, instance

  async def load_memory_modules(self, config: Optional[Dict[Any, Any]] = None) -> Dict[str, Any]:
    """
    Load and initialize memory subsystem modules.

    This is the UNIFIED method for loading memory modules.
    Handles discovery, initialization order, and health checks.

    Initialization order (respects dependencies):
    1. Embeddings (base - no dependencies)
    2. RAG (depends on Embeddings)
    3. Memory (depends on RAG)

    Args:
      config: Optional configuration dict for modules

    Returns:
      Dict[module_id, module_instance] of loaded modules

    Example:
      modules = await module_manager.load_memory_modules()
      embeddings = modules.get("embeddings")
    """
    loaded_modules: Dict[str, Any] = {}
    memory_path = self.path_discovery.base_path / "memory"

    if not memory_path.exists():
      logger.warning("Memory path not found: %s", memory_path)
      return loaded_modules

    # Initialization order (dependency chain)
    module_order = ["embeddings", "rag", "memory"]

    for module_name in module_order:
      try:
        result = await self._load_single_memory_module(module_name, memory_path, config)
        if result is not None:
          module_id, instance = result
          loaded_modules[module_id] = instance
      except Exception as e:
        logger.error("Memory module load error: %s - %s", module_name, str(e))
        continue

    logger.info("Memory modules loaded: %d (%s)", len(loaded_modules), list(loaded_modules.keys()))
    return loaded_modules

  def load_memory_modules_sync(self, config: Optional[Dict[Any, Any]] = None) -> Dict[str, Any]:
    """Synchronous wrapper for load_memory_modules."""
    return self.sync_wrapper.run_sync(
      self.load_memory_modules(config),
      error_msg_key='sync_wrapper_failed'
    )

  # Plugin loading methods are in PluginLoaderMixin (plugin_loader.py)