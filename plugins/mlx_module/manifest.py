"""
────────────────────────────────────
Server Nexe
Version: 0.8
Author: Jordi Goy
Location: plugins/mlx_module/manifest.py
Description: FastAPI router for the MLX module (Apple Silicon).
             Lazy initialization to avoid side effects at import.

www.jgoy.net
────────────────────────────────────
"""

import logging
from typing import Optional

from personality.i18n.resolve import t_modular

logger = logging.getLogger(__name__)

def _t_log(key: str, fallback: str, **kwargs) -> str:
    return t_modular(f"mlx_module.logs.{key}", fallback, **kwargs)

# Lazy singleton - no side effects at import
_module: Optional["MLXModule"] = None
_router = None


def _get_module():
    """Lazy initialization of module instance."""
    global _module
    if _module is None:
        from .module import MLXModule
        logger.info(
            _t_log("manifest_creating_instance", "MLX manifest: Creating MLXModule instance...")
        )
        _module = MLXModule()
        _module._init_router()
        logger.info(
            _t_log("manifest_instance_created", "MLX manifest: MLXModule instance created")
        )
    return _module


def get_router():
    """Get router with lazy initialization."""
    global _router
    if _router is None:
        module = _get_module()
        _router = module.get_router()
        _router.prefix = "/mlx"
        _router.tags = ["mlx", "apple_silicon", "llm"]
    return _router


def get_metadata():
    """Get module metadata."""
    return _get_module().metadata


def get_module_instance():
    """Get module instance (lazy)."""
    logger.info(
        _t_log("manifest_get_instance_called", "MLX manifest: get_module_instance() called")
    )
    instance = _get_module()
    logger.info(
        _t_log(
            "manifest_returning_instance",
            "MLX manifest: Returning instance: {instance}",
            instance=instance,
        )
    )
    return instance
