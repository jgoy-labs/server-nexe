"""
DELETED - Use ModuleManager directly.

from personality.module_manager import ModuleManager
mm = ModuleManager()
modules = await mm.load_memory_modules()

See: docs/NEXE_ARCHITECTURAL_DECISIONS.md (ADR-001)
"""
from personality.i18n.resolve import t_modular

def _t(key: str, fallback: str, **kwargs) -> str:
    return t_modular(f"core.module_loader.{key}", fallback, **kwargs)

raise ImportError(
    _t(
        "memory_deprecated",
        "module_loader_memory is DELETED. Use ModuleManager.load_memory_modules() "
        "directly. See: docs/NEXE_ARCHITECTURAL_DECISIONS.md (ADR-001)"
    )
)
