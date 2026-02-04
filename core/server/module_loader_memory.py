"""
DELETED - Use ModuleManager directly.

from personality.module_manager import ModuleManager
mm = ModuleManager()
modules = await mm.load_memory_modules()

See: docs/NEXE_ARCHITECTURAL_DECISIONS.md (ADR-001)
"""
raise ImportError(
    "module_loader_memory is DELETED. "
    "Use ModuleManager.load_memory_modules() directly. "
    "See: docs/NEXE_ARCHITECTURAL_DECISIONS.md (ADR-001)"
)
