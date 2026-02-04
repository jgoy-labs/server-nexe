"""
────────────────────────────────────
Server Nexe
Version: 0.8
Author: Jordi Goy
Location: plugins/llama_cpp_module/manifest.py
Description: Router FastAPI per mòdul Llama.cpp (Universal).
             Lazy initialization to avoid side effects at import.

www.jgoy.net
────────────────────────────────────
"""

from typing import Optional

# Lazy singleton - no side effects at import
_module: Optional["LlamaCppModule"] = None
_router = None


def _get_module():
    """Lazy initialization of module instance."""
    global _module
    if _module is None:
        from .module import LlamaCppModule
        _module = LlamaCppModule()
        _module._init_router()
    return _module


def get_router():
    """Get router with lazy initialization."""
    global _router
    if _router is None:
        module = _get_module()
        _router = module.get_router()
        _router.prefix = "/llama-cpp"
        _router.tags = ["llama-cpp", "gguf", "llm"]
    return _router


def get_metadata():
    """Get module metadata."""
    return _get_module().metadata


def get_module_instance():
    """Get module instance (lazy)."""
    return _get_module()
