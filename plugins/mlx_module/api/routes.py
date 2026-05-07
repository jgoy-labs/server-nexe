"""
────────────────────────────────────
Server Nexe
Author: Jordi Goy
Location: plugins/mlx_module/api/routes.py
Description: FastAPI endpoints for the MLX module (Apple Silicon).
             Separated from module.py during normalization.

www.jgoy.net · https://server-nexe.org
────────────────────────────────────
"""

import logging
from fastapi import APIRouter, Depends, HTTPException

from plugins.security.core.auth import require_api_key

logger = logging.getLogger(__name__)


def create_router(module_instance) -> APIRouter:
    """
    Creates the FastAPI router with all MLX endpoints.

    Args:
        module_instance: MLXModule instance
    """
    router = APIRouter(prefix="/mlx")

    def _get_module():
        if module_instance is None:
            raise HTTPException(status_code=503, detail="MLXModule not initialized")
        return module_instance

    @router.get("/info", operation_id="mlx_info")
    async def get_info(_: str = Depends(require_api_key)):
        """MLX module information. PROTECTED: Requires API key."""
        module = _get_module()
        return module.get_info()

    return router
