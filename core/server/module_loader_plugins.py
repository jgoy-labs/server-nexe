"""
DELETED - Use ModuleManager directly.

from personality.module_manager import ModuleManager
mm = ModuleManager()
result = mm.load_plugin_routers(app, project_root)

See: docs/NEXE_ARCHITECTURAL_DECISIONS.md (ADR-001)
"""
raise ImportError(
    "module_loader_plugins is DELETED. "
    "Use ModuleManager.load_plugin_routers() directly. "
    "See: docs/NEXE_ARCHITECTURAL_DECISIONS.md (ADR-001)"
)
