"""
────────────────────────────────────
Server Nexe
Author: Jordi Goy
Location: plugins/mlx_module/manifest.py
Description: FastAPI router for the MLX module (Apple Silicon).
             Lazy initialization to avoid side effects at import.

www.jgoy.net · https://server-nexe.org
────────────────────────────────────
"""

import logging

from core.loader.manifest_base import create_lazy_manifest, install_lazy_manifest

logger = logging.getLogger(__name__)

_m = create_lazy_manifest(
    module_path="plugins.mlx_module.module",
    module_class="MLXModule",
    tags=["mlx", "apple_silicon", "llm"],
    on_create=lambda inst: (
        logger.info("MLX manifest: Creating MLXModule instance..."),
        logger.info("MLX manifest: MLXModule instance created"),
    ),
    on_get_instance=lambda inst: (
        logger.info("MLX manifest: get_module_instance() called"),
        logger.info(f"MLX manifest: Returning instance: {inst}"),
    ),
)

install_lazy_manifest(__name__, _m)
