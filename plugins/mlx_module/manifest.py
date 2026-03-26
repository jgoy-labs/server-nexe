"""
────────────────────────────────────
Server Nexe
Version: 0.8
Author: Jordi Goy
Location: plugins/mlx_module/manifest.py
Description: Router FastAPI per mòdul MLX (Apple Silicon).
             Lazy initialization to avoid side effects at import.

www.jgoy.net · https://server-nexe.org
────────────────────────────────────
"""

import logging
from typing import Optional

logger = logging.getLogger(__name__)

# Lazy singleton - no side effects at import
_module: Optional["MLXModule"] = None
_router = None


def _get_module():
    """Lazy initialization of module instance."""
    global _module
    if _module is None:
        from .module import MLXModule
        logger.info("MLX manifest: Creating MLXModule instance...")
        _module = MLXModule()
        _module._init_router()
        logger.info("MLX manifest: MLXModule instance created")
    return _module


def get_router():
    """Get router with lazy initialization."""
    global _router
    if _router is None:
        module = _get_module()
        _router = module.get_router()
        _router.tags = ["mlx", "apple_silicon", "llm"]
    return _router


def get_metadata():
    """Get module metadata."""
    return _get_module().metadata


def get_module_instance():
    """Get module instance (lazy)."""
    logger.info("MLX manifest: get_module_instance() called")
    instance = _get_module()
    logger.info(f"MLX manifest: Returning instance: {instance}")
    return instance
