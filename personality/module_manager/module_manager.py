"""
────────────────────────────────────
Server Nexe
Version: 0.8
Author: Jordi Goy 
Location: personality/module_manager/module_manager.py
Description: Façade central del sistema de gestió de mòduls Nexe 0.8.

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

try:
  from plugins.security.core.validators import validate_safe_path
  SECURITY_VALIDATION_AVAILABLE = True
except ImportError:
  SECURITY_VALIDATION_AVAILABLE = False

from personality._logger import get_logger
logger = get_logger(__name__)

if not SECURITY_VALIDATION_AVAILABLE:
  logger.warning("Security validation not available - validate_safe_path not found")

class ModuleManager:
  """
  UNIFIED Module Manager for Nexe 0.8 system (SINGLE SOURCE OF TRUTH).

  This is the ONLY module loading system. All module operations go through here:
  - Plugin modules (plugins/*)
  - Memory modules (memory/*)
  - Core modules (core/*)

  Coordina components especialitzats:
  - ConfigManager: Gestió de configuració i manifests
  - PathDiscovery: Descobriment de paths de mòduls
  - ModuleDiscovery: Lògica de descobriment
  - ModuleLoader: Càrrega dinàmica de mòduls
  - ModuleRegistry: Registre i indexació de mòduls
  - ModuleLifecycleManager: Cicle de vida de mòduls individuals
  - SystemLifecycleManager: Cicle de vida del sistema
  - SyncWrapper: Wrappers síncrons per operacions async
  - EventSystem: Gestió d'events
  - MetricsCollector: Col·lecció de mètriques
  - I18nManager: Internacionalització

  See: docs/NEXE_ARCHITECTURAL_DECISIONS.md (ADR-001)
  """

  def __init__(self, config_path: Path = None):
    """
    Inicialitza module manager amb tots els components.

    Args:
      config_path: Path al fitxer server.toml
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

    self.discovery = ModuleDiscovery(
      self.path_discovery, self.config_manager, self.events, self.i18n
    )
    self.sync_wrapper = SyncWrapper(self.i18n)

    self.module_lifecycle = ModuleLifecycleManager(
      self._modules, self.loader, self.registry,
      self.events, self.metrics, self.i18n
    )
    self.system_lifecycle = SystemLifecycleManager(
      self._modules, self.module_lifecycle,
      self.discover_modules, self.list_modules, self.i18n
    )

    self.api_integrator = None

    self._log_init()

  def _configure_base_path(self) -> None:
    """Configura base_path per PathDiscovery."""
    if self.config_path.parent.name == "personality":
      self.path_discovery.base_path = self.config_path.parent.parent
    else:
      self.path_discovery.base_path = self.config_path.parent

  def _find_initial_config(self, config_path: Optional[Path]) -> Path:
    """
    Cerca inicial de configuració amb validació de seguretat.
    """
    if config_path:
      config_path = Path(config_path)
      if SECURITY_VALIDATION_AVAILABLE:
        try:
          base_path = Path.cwd()
          validated_path = validate_safe_path(config_path, base_path)
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
    """Log d'inicialització."""
    logger.info(get_message(self.i18n, 'init.started'), component="module_manager")
    logger.info(get_message(self.i18n, 'init.config_loaded', path=str(self.config_path)))

  async def discover_modules(self, force: bool = False) -> List[str]:
    """Descobreix mòduls disponibles."""
    return await self.discovery.discover(self._modules, self._lock, force)

  def discover_modules_sync(self, force: bool = False) -> List[str]:
    """Wrapper síncron per a discover_modules()."""
    return self.sync_wrapper.run_sync(
      self.discover_modules(force),
      error_msg_key='sync_wrapper_failed'
    )

  async def load_module(self, module_name: str) -> bool:
    """Carrega un mòdul."""
    with self._lock:
      if module_name not in self._modules:
        await self.discover_modules()
        if module_name not in self._modules:
          msg = get_message(self.i18n, 'loading.not_found', module=module_name)
          logger.error(msg, component="module_manager")
          return False
    return await self.module_lifecycle.load_module(module_name)

  async def start_module(self, module_name: str) -> bool:
    """Inicia un mòdul carregat."""
    return await self.module_lifecycle.start_module(module_name)

  async def stop_module(self, module_name: str) -> bool:
    """Atura un mòdul en execució."""
    return await self.module_lifecycle.stop_module(module_name)

  async def start_system(self) -> bool:
    """Inicia el sistema complet."""
    original_get_lock = self.system_lifecycle._get_lock
    self.system_lifecycle._get_lock = lambda: self._lock
    result = await self.system_lifecycle.start_system()
    self._running = self.system_lifecycle.is_running()
    self.system_lifecycle._get_lock = original_get_lock
    return result

  async def shutdown_system(self) -> None:
    """Atura el sistema."""
    original_get_lock = self.system_lifecycle._get_lock
    self.system_lifecycle._get_lock = lambda: self._lock
    await self.system_lifecycle.shutdown_system()
    self._running = self.system_lifecycle.is_running()
    self.system_lifecycle._get_lock = original_get_lock

  def get_module_info(self, module_name: str) -> Optional[ModuleInfo]:
    """Obté informació sobre un mòdul."""
    return self._modules.get(module_name)

  def update_module_enabled(self, module_name: str, enabled: bool) -> bool:
    """Actualitza l'estat enabled d'un mòdul i persisteix al config."""
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
    """Llista mòduls, opcionalment filtrats per estat."""
    with self._lock:
      modules = list(self._modules.values())
      if state_filter:
        modules = [m for m in modules if m.state == state_filter]
      return sorted(modules, key=lambda m: m.priority)

  def get_system_status(self) -> Dict[str, Any]:
    """Obté estat del sistema."""
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

  def add_event_listener(self, callback, event_type: str = None) -> None:
    """Afegeix listener d'events."""
    self.events.add_event_listener(callback, event_type)

  def get_module_metrics(self, module_name: str) -> Dict[str, Any]:
    """Obté mètriques per un mòdul."""
    if module_name in self._modules:
      return self.metrics.get_module_metrics(self._modules[module_name])
    return {}

  def get_registry_info(self) -> Dict[str, Any]:
    """Obté informació del registre."""
    return self.registry.get_registry_stats()

  def set_api_integrator(self, api_integrator):
    """Estableix l'API integrator."""
    self.api_integrator = api_integrator
    self.module_lifecycle.set_api_integrator(api_integrator)
    logger.info(get_message(self.i18n, 'api.integrator.set'))

  async def load_memory_modules(self, config: dict = None) -> Dict[str, Any]:
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
    import importlib

    loaded_modules = {}
    memory_path = self.path_discovery.base_path / "memory"

    if not memory_path.exists():
      logger.warning("Memory path not found: %s", memory_path)
      return loaded_modules

    # Initialization order (dependency chain)
    module_order = ["embeddings", "rag", "memory"]

    for module_name in module_order:
      module_path = memory_path / module_name
      manifest_file = module_path / "manifest.py"

      if not manifest_file.exists():
        logger.debug("Memory module manifest not found: %s", manifest_file)
        continue

      try:
        # Import manifest
        manifest_module = importlib.import_module(f"memory.{module_name}.manifest")

        if not hasattr(manifest_module, "MODULE_ID"):
          logger.error("Memory module %s missing MODULE_ID", module_name)
          continue

        module_id = manifest_module.MODULE_ID
        logger.info("Loading memory module: %s (ID: %s)", module_name, module_id)

        # Import module class
        module_py = importlib.import_module(f"memory.{module_name}.module")

        # Determine class name
        if module_name == "rag":
          module_class_name = "RAGModule"
        else:
          module_class_name = f"{module_name.capitalize()}Module"

        if not hasattr(module_py, module_class_name):
          logger.error("Memory module class not found: %s", module_class_name)
          continue

        module_class = getattr(module_py, module_class_name)

        # Get singleton instance
        instance = module_class.get_instance()

        # Initialize with config
        module_config = config.get(module_name) if config else None
        success = await instance.initialize(config=module_config)

        if not success:
          logger.error("Memory module initialization failed: %s", module_name)
          continue

        # Health check
        health = instance.get_health()
        health_status = health.get("status", "unhealthy")

        logger.info(
          "Memory module loaded: %s (ID: %s, health: %s)",
          module_name, module_id, health_status
        )

        # Register in our registry
        self.registry.register_module(
          name=module_name,
          instance=instance,
          manifest={"module_id": module_id, "type": "memory"}
        )

        loaded_modules[module_id] = instance

        # Emit event
        from personality.events.event_system import create_system_event
        event = await create_system_event(
          source="module_manager",
          event_type="module_loaded",
          module=module_name,
          module_id=module_id,
          type="memory"
        )
        await self.events.emit_event(event)

      except Exception as e:
        logger.error("Memory module load error: %s - %s", module_name, str(e))
        continue

    logger.info("Memory modules loaded: %d (%s)", len(loaded_modules), list(loaded_modules.keys()))
    return loaded_modules

  def load_memory_modules_sync(self, config: dict = None) -> Dict[str, Any]:
    """Synchronous wrapper for load_memory_modules."""
    return self.sync_wrapper.run_sync(
      self.load_memory_modules(config),
      error_msg_key='sync_wrapper_failed'
    )

  def load_plugin_routers(
    self,
    app,
    project_root: Path,
    discovered: List[str] = None
  ) -> Dict[str, Any]:
    """
    Load plugin routers into FastAPI application with security checks.

    This is the UNIFIED method for loading plugin routers.
    Handles security allowlist, manifest import, and router registration.

    Args:
      app: FastAPI application instance
      project_root: Project root directory path
      discovered: Optional list of discovered modules (auto-discovers if None)

    Returns:
      Dict with loaded modules info and statistics

    Example:
      result = module_manager.load_plugin_routers(app, Path.cwd())
      print(f"Loaded {result['loaded_count']} routers")
    """
    import importlib
    import os
    import traceback
    from personality.module_manager.core_modules import get_core_modules
    from personality.data.models import SystemEvent, ModuleState

    result = {
      'loaded': [],
      'skipped': [],
      'failed': [],
      'loaded_count': 0
    }

    # Auto-discover if not provided
    if discovered is None:
      discovered = self.discover_modules_sync()

    i18n = self.i18n

    # Configure security allowlist
    allowlist_config = self._configure_plugin_allowlist(i18n)

    for module_name in discovered:
      try:
        module_info = self.get_module_info(module_name)
        if not module_info:
          logger.warning(f"Module {module_name} discovered but no info available")
          result['skipped'].append({'module': module_name, 'reason': 'no_info'})
          continue

        # Security check
        if not self._check_plugin_security(app, module_name, module_info, allowlist_config, i18n):
          result['skipped'].append({'module': module_name, 'reason': 'security'})
          continue

        # Import manifest
        manifest_module = self._import_plugin_manifest(module_info, project_root)

        # Load routers
        routers_loaded = self._load_plugin_routers_from_manifest(app, manifest_module, module_name, i18n)

        # Register instance in app.state (ALWAYS, even without routers)
        self._register_plugin_instance(app, module_name, manifest_module)

        # Register in our registry (SINGLE SOURCE OF TRUTH)
        self.registry.register_module(
          name=module_name,
          instance=manifest_module,
          manifest=module_info.manifest
        )

        result['loaded'].append(module_name)
        result['loaded_count'] += 1

        # Emit event (for both router and non-router modules)
        self.events.emit_event_sync(SystemEvent(
          timestamp=datetime.now(timezone.utc),
          source="module_manager",
          event_type="plugin_router_loaded",
          level="info",
          details={"module": module_name}
        ))

      except Exception as e:
        error_detail = traceback.format_exc()
        logger.error(f"Failed to load routers from {module_name}: {e}")
        logger.debug(f"Traceback:\n{error_detail}")

        if module_info:
          module_info.state = ModuleState.ERROR
          module_info.last_error = str(e)
          module_info.error_count += 1

        result['failed'].append({'module': module_name, 'error': str(e)})

    logger.info(f"Plugin routers loaded: {result['loaded_count']} ({result['loaded']})")
    return result

  def _configure_plugin_allowlist(self, i18n) -> dict:
    """Configure plugin security allowlist based on environment.

    Uses core.config.get_module_allowlist() as single source of truth.
    """
    import os
    from core.config import get_module_allowlist
    from personality.module_manager.core_modules import get_core_modules

    core_env = os.getenv("NEXE_ENV", "development")
    internal_modules = get_core_modules()

    approved_modules = get_module_allowlist(self.config_manager.get_config())

    if approved_modules is not None:
      logger.info(f"Module allowlist enabled: {sorted(approved_modules)}")
    else:
      logger.warning(f"NEXE_ENV={core_env}: No module allowlist. All discovered modules will be loaded.")

    effective_allowlist = None
    if approved_modules is not None:
      effective_allowlist = set(approved_modules) | internal_modules

    return {
      'approved_modules': approved_modules,
      'internal_modules': internal_modules,
      'effective_allowlist': effective_allowlist,
      'core_env': core_env
    }

  def _check_plugin_security(self, app, module_name: str, module_info, allowlist_config: dict, i18n) -> bool:
    """Check if plugin passes security allowlist validation."""
    from personality.data.models import ModuleState

    effective_allowlist = allowlist_config['effective_allowlist']

    if effective_allowlist is not None and module_name not in effective_allowlist:
      module_info.enabled = False
      module_info.state = ModuleState.DISABLED
      logger.warning(f"Module {module_name} not in allowlist, skipping")

      if hasattr(app.state, 'security_logger'):
        app.state.security_logger.log_module_rejected(
          module_name=module_name,
          reason=f"Not in NEXE_APPROVED_MODULES allowlist"
        )
      return False

    if hasattr(module_info, 'enabled') and not module_info.enabled:
      logger.info(f"Module {module_name} disabled, skipping")
      return False

    return True

  def _import_plugin_manifest(self, module_info, project_root: Path):
    """Import manifest module from plugin path."""
    import importlib

    module_path = module_info.path
    relative_path = Path(module_path).resolve().relative_to(project_root.resolve())
    base_import_path = str(relative_path).replace('/', '.')

    manifest_module = None
    tried_paths = []

    for import_path in [f'{base_import_path}.manifest', f'{base_import_path}.readme.manifest']:
      try:
        manifest_module = importlib.import_module(import_path)
        break
      except ModuleNotFoundError:
        tried_paths.append(import_path)
        continue

    if manifest_module is None:
      raise ModuleNotFoundError(f"Could not find manifest in any of: {tried_paths}")

    return manifest_module

  def _load_plugin_routers_from_manifest(self, app, manifest_module, module_name: str, i18n) -> bool:
    """Load routers from manifest module into FastAPI app."""
    routers_loaded = False

    if hasattr(manifest_module, 'router_public'):
      app.include_router(manifest_module.router_public)
      logger.info(f"Loaded router_public from {module_name}")
      routers_loaded = True

    if hasattr(manifest_module, 'router_admin'):
      app.include_router(manifest_module.router_admin)
      logger.info(f"Loaded router_admin from {module_name}")
      routers_loaded = True

    if hasattr(manifest_module, 'router_ui'):
      app.include_router(manifest_module.router_ui)
      logger.info(f"Loaded router_ui from {module_name}")
      routers_loaded = True

    if not routers_loaded and hasattr(manifest_module, 'get_router'):
      try:
        router = manifest_module.get_router()
        if router:
          app.include_router(router)
          logger.info(f"Loaded router via get_router() from {module_name}")
          routers_loaded = True
      except Exception as e:
        logger.warning(f"Failed to get router from {module_name} via get_router(): {e}")

    if not routers_loaded:
      logger.info(f"{module_name} has no routers")

    return routers_loaded

  def _register_plugin_instance(self, app, module_name: str, manifest_module) -> None:
    """Register plugin instance in app.state.modules."""
    if not hasattr(app.state, 'modules'):
      app.state.modules = {}

    instance = None
    for attr in ['get_module_instance', 'module_instance', '_module', '_ollama_module']:
      if attr == 'get_module_instance' and hasattr(manifest_module, attr):
        try:
          logger.info(f"Calling {module_name}.{attr}()...")
          instance = getattr(manifest_module, attr)()
          logger.info(f"{module_name}.{attr}() returned: {instance}")
        except Exception as e:
          logger.error(f"Error calling {module_name}.{attr}(): {e}", exc_info=True)
      elif hasattr(manifest_module, attr):
        logger.info(f"Getting {module_name}.{attr} (attribute)...")
        instance = getattr(manifest_module, attr)
        logger.info(f"{module_name}.{attr} = {instance}")

      if instance is not None:
        break

    if instance is None:
      return

    app.state.modules.setdefault(module_name, instance)
    if getattr(instance, "name", None):
      app.state.modules.setdefault(instance.name, instance)