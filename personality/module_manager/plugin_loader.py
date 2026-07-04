"""
────────────────────────────────────
Server Nexe
Author: Jordi Goy
Location: personality/module_manager/plugin_loader.py
Description: PluginLoaderMixin — plugin router loading methods extracted from
ModuleManager to keep module_manager.py under 500 NLOC.

www.jgoy.net · https://server-nexe.org
────────────────────────────────────
"""

import traceback
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Optional, Any

from personality._logger import get_logger
from .types import RouterContext, SecurityCheckContext

logger = get_logger(__name__)


class PluginLoaderMixin:
    """Mixin that provides plugin router loading to ModuleManager."""

    def load_plugin_routers(
        self,
        app,
        project_root: Path,
        discovered: Optional[List[str]] = None,
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
        from personality.data.models import SystemEvent, ModuleState

        result: Dict[str, Any] = {
            'loaded': [],
            'skipped': [],
            'failed': [],
            'loaded_count': 0,
        }

        # Auto-discover if not provided
        if discovered is None:
            discovered = self.discover_modules_sync()  # type: ignore[attr-defined]

        # Configure security allowlist
        allowlist_config = self._configure_plugin_allowlist()

        for module_name in discovered:  # pyright: ignore[reportOptionalIterable]  # discovered is set just above if None
            module_info = None
            try:
                module_info = self.get_module_info(module_name)  # type: ignore[attr-defined]
                if not module_info:
                    logger.warning(f"Module {module_name} discovered but no info available")
                    result['skipped'].append({'module': module_name, 'reason': 'no_info'})
                    continue

                # Security check
                sec_ctx = SecurityCheckContext(
                    app=app,
                    module_name=module_name,
                    module_info=module_info,
                    allowlist_config=allowlist_config,
                )
                if not self._check_plugin_security(sec_ctx):
                    result['skipped'].append({'module': module_name, 'reason': 'security'})
                    continue

                # Import manifest
                manifest_module = self._import_plugin_manifest(module_info, project_root)

                # Load routers (return value intentionally discarded — registration
                # happens via side effects on `app`)
                self._load_plugin_routers_from_manifest(app, manifest_module, module_name)

                # Register instance in app.state (ALWAYS, even without routers)
                self._register_plugin_instance(app, module_name, manifest_module)

                # Register in our registry (SINGLE SOURCE OF TRUTH)
                self.registry.register_module(  # type: ignore[attr-defined]
                    name=module_name,
                    instance=manifest_module,
                    manifest=module_info.manifest,
                )

                result['loaded'].append(module_name)
                result['loaded_count'] += 1

                # Emit event (for both router and non-router modules)
                self.events.emit_event_sync(SystemEvent(  # type: ignore[attr-defined]
                    timestamp=datetime.now(timezone.utc),
                    source="module_manager",
                    event_type="plugin_router_loaded",
                    level="info",
                    details={"module": module_name},
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

    def _configure_plugin_allowlist(self) -> dict:
        """Configure plugin security allowlist based on environment.

        Uses core.config.get_module_allowlist() as single source of truth.
        """
        import os
        from core.config import get_module_allowlist
        from personality.module_manager.core_modules import get_core_modules

        core_env = os.getenv("NEXE_ENV", "production")
        internal_modules = get_core_modules()

        approved_modules = get_module_allowlist(self.config_manager.get_config())  # type: ignore[attr-defined]

        if approved_modules is not None:
            logger.info(f"Module allowlist enabled: {sorted(approved_modules)}")
        else:
            logger.warning(
                f"NEXE_ENV={core_env}: No module allowlist. All discovered modules will be loaded."
            )

        effective_allowlist = None
        if approved_modules is not None:
            effective_allowlist = set(approved_modules) | internal_modules

        return {
            'approved_modules': approved_modules,
            'internal_modules': internal_modules,
            'effective_allowlist': effective_allowlist,
            'core_env': core_env,
        }

    def _check_plugin_security(self, ctx: SecurityCheckContext) -> bool:
        """Check if plugin passes security allowlist validation."""
        from personality.data.models import ModuleState

        effective_allowlist = ctx.allowlist_config['effective_allowlist']

        if effective_allowlist is not None and ctx.module_name not in effective_allowlist:
            ctx.module_info.enabled = False
            ctx.module_info.state = ModuleState.DISABLED
            logger.warning(f"Module {ctx.module_name} not in allowlist, skipping")

            if hasattr(ctx.app.state, 'security_logger'):
                ctx.app.state.security_logger.log_module_rejected(
                    module_name=ctx.module_name,
                    reason="Not in NEXE_APPROVED_MODULES allowlist",
                )
            return False

        if hasattr(ctx.module_info, 'enabled') and not ctx.module_info.enabled:
            logger.info(f"Module {ctx.module_name} disabled, skipping")
            return False

        return True

    def _import_plugin_manifest(self, module_info, project_root: Path):
        """Import manifest module from plugin path."""
        import importlib

        module_path = module_info.path
        relative_path = Path(module_path).resolve().relative_to(project_root.resolve())
        # Path.parts is separator-agnostic (Windows uses '\\'; a str.replace('/', '.')
        # would leave backslashes and break the import path)
        base_import_path = '.'.join(relative_path.parts)

        manifest_module = None
        tried_paths = []

        for import_path in [f'{base_import_path}.manifest', f'{base_import_path}.readme.manifest']:
            try:
                manifest_module = importlib.import_module(import_path)  # nosemgrep: non-literal-import — import_path constructed from base_import_path (validated plugin path), not user input
                break
            except ModuleNotFoundError:
                tried_paths.append(import_path)
                continue

        if manifest_module is None:
            raise ModuleNotFoundError(f"Could not find manifest in any of: {tried_paths}")

        return manifest_module

    def _check_removed_routes_collision(
        self, router, removed_routes: list, module_name: str
    ) -> None:
        """Fail-fast if router registers a route declared as removed.

        Compares each route.path (which already includes the router prefix, e.g.
        '/mlx/chat') against prefix+manifest_route. Raises PluginLoadError on
        collision so the plugin is rejected at load time, not silently bypassed.
        """
        if not removed_routes:
            return
        from core.loader.protocol import PluginLoadError

        prefix = getattr(router, 'prefix', '') or ''
        for route in router.routes:
            route_path = getattr(route, 'path', '')
            for manifest_route in removed_routes:
                if route_path == (prefix + manifest_route):
                    raise PluginLoadError(
                        f"Plugin '{module_name}' declares removed_direct_routes={removed_routes!r} "
                        f"but also registers route '{manifest_route}' (full path: '{route_path}'). "
                        f"Action: remove the @router.*(\"{manifest_route}\") decorator from {module_name}.",
                        plugin_name=module_name,
                        colliding_route=manifest_route,
                    )

    def _register_removed_routes(
        self, router, removed_routes: list, module_name: str
    ) -> None:
        """Register removed routes in the guard middleware registry.

        Called after collision check passes. Idempotent via register_removed_route.
        """
        if not removed_routes:
            return
        from core.middleware import register_removed_route

        prefix = getattr(router, 'prefix', '') or ''
        for manifest_route in removed_routes:
            register_removed_route(module_name, manifest_route, prefix)

    def _attach_named_router(self, ctx: RouterContext, attr_name: str) -> bool:
        """Attach a router by attribute name from a manifest module to the FastAPI app."""
        if not hasattr(ctx.manifest_module, attr_name):
            return False
        router = getattr(ctx.manifest_module, attr_name)
        self._check_removed_routes_collision(router, ctx.removed_routes, ctx.module_name)
        self._register_removed_routes(router, ctx.removed_routes, ctx.module_name)
        ctx.app.include_router(router)
        logger.info(f"Loaded {attr_name} from {ctx.module_name}")
        return True

    def _attach_get_router(self, ctx: RouterContext) -> bool:
        """Attach a router obtained via the manifest's get_router() factory method."""
        from core.loader.protocol import PluginLoadError

        if not hasattr(ctx.manifest_module, 'get_router'):
            return False
        try:
            router = ctx.manifest_module.get_router()
            if router:
                self._check_removed_routes_collision(router, ctx.removed_routes, ctx.module_name)
                self._register_removed_routes(router, ctx.removed_routes, ctx.module_name)
                ctx.app.include_router(router)
                logger.info(f"Loaded router via get_router() from {ctx.module_name}")
                return True
        except PluginLoadError:
            raise  # collision is a hard error — propagate to load_plugin_routers
        except Exception as e:
            logger.warning(f"Failed to get router from {ctx.module_name} via get_router(): {e}")
        return False

    def _load_plugin_routers_from_manifest(
        self, app, manifest_module, module_name: str
    ) -> bool:
        """Load routers from manifest module into FastAPI app."""
        removed_routes = getattr(manifest_module, 'removed_direct_routes', [])
        ctx = RouterContext(
            app=app,
            manifest_module=manifest_module,
            module_name=module_name,
            removed_routes=removed_routes,
        )
        routers_loaded = False

        for attr_name in ('router_public', 'router_admin', 'router_ui'):
            if self._attach_named_router(ctx, attr_name):
                routers_loaded = True

        if not routers_loaded:
            routers_loaded = self._attach_get_router(ctx)

        if not routers_loaded:
            logger.info(f"{module_name} has no routers")

        return routers_loaded

    def _resolve_plugin_instance(self, module_name: str, manifest_module):
        """Resolve the plugin instance from a manifest module by trying known attribute names."""
        for attr in ['get_module_instance', 'module_instance', '_module', '_ollama_module']:
            if attr == 'get_module_instance' and hasattr(manifest_module, attr):
                try:
                    logger.info(f"Calling {module_name}.{attr}()...")
                    instance = getattr(manifest_module, attr)()
                    logger.info(f"{module_name}.{attr}() returned: {instance}")
                except Exception as e:
                    logger.error(f"Error calling {module_name}.{attr}(): {e}", exc_info=True)
                    instance = None
            elif hasattr(manifest_module, attr):
                logger.info(f"Getting {module_name}.{attr} (attribute)...")
                instance = getattr(manifest_module, attr)
                logger.info(f"{module_name}.{attr} = {instance}")
            else:
                instance = None
            if instance is not None:
                return instance
        return None

    def _register_plugin_instance(self, app, module_name: str, manifest_module) -> None:
        """Register plugin instance in app.state.modules."""
        if not hasattr(app.state, 'modules'):
            app.state.modules = {}

        instance = self._resolve_plugin_instance(module_name, manifest_module)
        if instance is None:
            return

        app.state.modules.setdefault(module_name, instance)
        if getattr(instance, "name", None):
            app.state.modules.setdefault(instance.name, instance)
