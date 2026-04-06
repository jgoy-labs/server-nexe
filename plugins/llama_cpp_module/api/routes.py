"""
────────────────────────────────────
Server Nexe
Author: Jordi Goy
Location: plugins/llama_cpp_module/api/routes.py
Description: Endpoints FastAPI del modul Llama.cpp.
             Separat de module.py durant normalitzacio (factory pattern).

www.jgoy.net · https://server-nexe.org
────────────────────────────────────
"""

import logging
from typing import Any, Dict

from fastapi import APIRouter, HTTPException

logger = logging.getLogger(__name__)


def create_router(module_instance) -> APIRouter:
    """
    Crea el router FastAPI amb tots els endpoints del modul Llama.cpp.

    Args:
        module_instance: LlamaCppModule instance
    """
    router = APIRouter(prefix="/llama-cpp")

    @router.get("/info")
    async def get_info():
        return module_instance.get_info()

    @router.post("/chat")
    async def chat_endpoint(request: Dict[str, Any]):
        if not module_instance._initialized:
            raise HTTPException(status_code=503, detail="Module not initialized")

        messages = request.get("messages", [])
        system = request.get("system", "")
        session_id = request.get("session_id", "default")

        try:
            result = await module_instance.chat(messages, system, session_id)
            return result
        except Exception as e:
            raise HTTPException(status_code=500, detail=str(e))

    return router
