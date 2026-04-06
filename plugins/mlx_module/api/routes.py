"""
────────────────────────────────────
Server Nexe
Author: Jordi Goy
Location: plugins/mlx_module/api/routes.py
Description: Endpoints FastAPI del modul MLX (Apple Silicon).
             Separat de module.py durant normalitzacio.

www.jgoy.net · https://server-nexe.org
────────────────────────────────────
"""

import logging
from typing import Any, Dict

from fastapi import APIRouter, HTTPException

logger = logging.getLogger(__name__)


def create_router(module_instance) -> APIRouter:
    """
    Crea el router FastAPI amb tots els endpoints d'MLX.

    Args:
        module_instance: MLXModule instance
    """
    router = APIRouter(prefix="/mlx")

    def _get_module():
        if module_instance is None:
            raise HTTPException(status_code=503, detail="MLXModule not initialized")
        return module_instance

    @router.get("/info")
    async def get_info():
        """Informacio del modul MLX."""
        module = _get_module()
        return module.get_info()

    @router.post("/chat")
    async def chat_endpoint(request: Dict[str, Any]):
        """Chat amb model MLX."""
        module = _get_module()
        if not module._initialized:
            raise HTTPException(status_code=503, detail="Module not initialized")

        messages = request.get("messages", [])
        system = request.get("system", "")
        session_id = request.get("session_id", "default")

        try:
            result = await module.chat(messages, system, session_id)
            return result
        except Exception as e:
            logger.error("MLX chat failed: %s", e)
            raise HTTPException(status_code=500, detail=str(e))

    return router
