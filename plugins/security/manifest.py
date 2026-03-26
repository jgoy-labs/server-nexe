"""
────────────────────────────────────
Server Nexe
Version: 0.8
Author: Jordi Goy
Location: plugins/security/manifest.py
Description: Router FastAPI per modul security.
             Lazy initialization to avoid side effects at import.

www.jgoy.net · https://server-nexe.org
────────────────────────────────────
"""

from typing import Optional

# Lazy singleton — no side effects at import
_module: Optional["SecurityModule"] = None
_router = None


def _get_module():
    """Lazy initialization of module instance."""
    global _module
    if _module is None:
        from .module import SecurityModule
        _module = SecurityModule()
        _module._init_router()
    return _module


def get_router():
    """Get router with lazy initialization."""
    global _router
    if _router is None:
        module = _get_module()
        _router = module.get_router()
        _router.tags = ["security"]
    return _router


def get_metadata():
    """Get module metadata."""
    return _get_module().metadata


def get_module_instance():
    """Get module instance (lazy)."""
    return _get_module()


# ─── Retrocompatibilitat amb codi i tests existents ───
# El manifest.py antic exportava aquests noms directament.
# Els mantenim com a facades lazy per no trencar imports existents.

from .module import SecurityModule  # noqa: E402

MODULE_NAME = "security"

MODULE_METADATA = {
    "name": MODULE_NAME,
    "version": "0.8.2",
    "description": "Security scanning and validation module",
    "routers": ["router_public"],
    "auto_discover": True
}

try:
    from core.dependencies import limiter  # noqa: E402,F401
    RATE_LIMITING_AVAILABLE = True
except ImportError:
    RATE_LIMITING_AVAILABLE = False


def init_security_module():
    """Retrocompat: inicialitza el modul security."""
    import logging
    from pathlib import Path
    logger = logging.getLogger(__name__)
    logger.info("Security module initialized: %s v%s", MODULE_NAME, MODULE_METADATA['version'])
    log_path = Path(__file__).parent.parent.parent / "storage" / "system-logs" / MODULE_NAME
    log_path.mkdir(parents=True, exist_ok=True)
    return MODULE_METADATA


class _LazyRouterPublic:
    """Descriptor que retorna el router lazy quan s'accedeix com a atribut del modul."""

    def __get__(self, obj, objtype=None):
        return get_router()


class _LazyModuleInstance:
    """Descriptor que retorna la instancia lazy."""

    def __get__(self, obj, objtype=None):
        return get_module_instance()


# Per accedir com a atributs de modul (ex: `from plugins.security.manifest import router_public`)
# Usem __getattr__ del modul Python (PEP 562)
def __getattr__(name):
    if name == "router_public":
        return get_router()
    if name == "module_instance":
        return get_module_instance()
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
