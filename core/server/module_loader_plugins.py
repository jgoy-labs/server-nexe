"""
DELETED - Use ModuleManager directly.

from personality.module_manager import ModuleManager
mm = ModuleManager()
result = mm.load_plugin_routers(app, project_root)

See: docs/NEXE_ARCHITECTURAL_DECISIONS.md (ADR-001)
"""
from personality.i18n.resolve import t_modular

def _t(key: str, fallback: str, **kwargs) -> str:
    return t_modular(f"core.module_loader.{key}", fallback, **kwargs)

raise ImportError(
    _t(
        "plugins_deprecated",
        "module_loader_plugins is DELETED. Use ModuleManager.load_plugin_routers() "
        "directly. See: docs/NEXE_ARCHITECTURAL_DECISIONS.md (ADR-001)"
    )
)
