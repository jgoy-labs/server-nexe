"""
────────────────────────────────────
Server Nexe
Version: 0.8
Author: Jordi Goy
Location: core/server/module_loader.py
Description: Module Loader - Re-exports from ModuleManager (SINGLE SOURCE OF TRUTH).

ARCHITECTURE:
  ModuleManager is the SINGLE SOURCE OF TRUTH for all module operations.
  This file provides backwards-compatible re-exports.

  For direct access, use:
    from personality.module_manager import ModuleManager
    mm = ModuleManager()
    result = mm.load_plugin_routers(app, project_root)
    modules = await mm.load_memory_modules()

  See: docs/NEXE_ARCHITECTURAL_DECISIONS.md (ADR-001)

www.jgoy.net
────────────────────────────────────
"""

import warnings

# Re-export from ModuleManager for backwards compatibility
# All these functions are available directly on ModuleManager instance

def _get_module_manager():
    """Get or create ModuleManager instance."""
    from personality.module_manager.module_manager import ModuleManager
    return ModuleManager()


def load_module_routers(app, discovered, module_manager, project_root, registry=None):
    """
    DEPRECATED: Use module_manager.load_plugin_routers() directly.
    """
    warnings.warn(
        "load_module_routers() from core.server.module_loader is deprecated. "
        "Use module_manager.load_plugin_routers() directly.",
        DeprecationWarning,
        stacklevel=2
    )
    return module_manager.load_plugin_routers(app, project_root, discovered)


async def load_memory_modules(config=None, module_manager=None):
    """
    DEPRECATED: Use module_manager.load_memory_modules() directly.
    """
    warnings.warn(
        "load_memory_modules() from core.server.module_loader is deprecated. "
        "Use module_manager.load_memory_modules() directly.",
        DeprecationWarning,
        stacklevel=2
    )
    if module_manager is None:
        module_manager = _get_module_manager()
    return await module_manager.load_memory_modules(config)


__all__ = [
    'load_module_routers',
    'load_memory_modules',
]
