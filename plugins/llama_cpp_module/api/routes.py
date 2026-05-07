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
from fastapi import APIRouter, Depends

from plugins.security.core.auth import require_api_key

logger = logging.getLogger(__name__)


def create_router(module_instance) -> APIRouter:
    """
    Crea el router FastAPI amb tots els endpoints del modul Llama.cpp.

    Args:
        module_instance: LlamaCppModule instance
    """
    router = APIRouter(prefix="/llama-cpp")

    @router.get("/info", operation_id="llama_cpp_info")
    async def get_info(_: str = Depends(require_api_key)):
        """PROTECTED: Requires API key."""
        return module_instance.get_info()

    return router
