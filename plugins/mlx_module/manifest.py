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
    removed_direct_routes=["/chat"],
    on_create=lambda inst: (
        logger.info("MLX manifest: Creating MLXModule instance..."),  # type: ignore[func-returns-value]  # tuple trick lambda: logger.info retorna None, tuple expression vàlid
        logger.info("MLX manifest: MLXModule instance created"),  # type: ignore[func-returns-value]  # tuple trick lambda: logger.info retorna None, tuple expression vàlid
    ),
    on_get_instance=lambda inst: (
        logger.info("MLX manifest: get_module_instance() called"),  # type: ignore[func-returns-value]  # tuple trick lambda: logger.info retorna None, tuple expression vàlid
        logger.info(f"MLX manifest: Returning instance: {inst}"),  # type: ignore[func-returns-value]  # tuple trick lambda: logger.info retorna None, tuple expression vàlid
    ),
)

install_lazy_manifest(__name__, _m)
