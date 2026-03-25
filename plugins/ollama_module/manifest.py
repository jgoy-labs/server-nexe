"""
────────────────────────────────────
Server Nexe
Version: 0.8
Author: Jordi Goy
Location: plugins/ollama_module/manifest.py
Description: Router FastAPI per modul Ollama.
             Lazy initialization to avoid side effects at import.

www.jgoy.net · https://server-nexe.org
────────────────────────────────────
"""

from typing import Optional

# Lazy singleton — no side effects at import
_module: Optional["OllamaModule"] = None
_router = None


def _get_module():
    """Lazy initialization of module instance."""
    global _module
    if _module is None:
        from .module import OllamaModule
        _module = OllamaModule()
        _module._init_router()
    return _module


def get_router():
    """Get router with lazy initialization."""
    global _router
    if _router is None:
        module = _get_module()
        _router = module.get_router()
        _router.prefix = "/ollama"
        _router.tags = ["ollama", "llm", "chat", "local"]
    return _router


def get_metadata():
    """Get module metadata."""
    return _get_module().metadata


def get_module_instance():
    """Get module instance (lazy)."""
    return _get_module()


# Retrocompatibilitat
def __getattr__(name):
    if name == "router_public":
        return get_router()
    if name == "_ollama_module":
        return get_module_instance()
    if name == "get_ollama_module":
        return get_module_instance
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
