"""
────────────────────────────────────
Server Nexe
Author: Jordi Goy
Location: plugins/llama_cpp_module/api/routes.py
Description: FastAPI endpoints for the Llama.cpp module.
             Separated from module.py during normalisation (factory pattern).

www.jgoy.net · https://server-nexe.org
────────────────────────────────────
"""

import logging
from fastapi import APIRouter, Depends

from plugins.security.core.auth import require_api_key

logger = logging.getLogger(__name__)


def create_router(module_instance) -> APIRouter:
    """
    Create the FastAPI router with all Llama.cpp module endpoints.

    Args:
        module_instance: LlamaCppModule instance
    """
    router = APIRouter(prefix="/llama-cpp")

    @router.get("/info", operation_id="llama_cpp_info")
    async def get_info(_: str = Depends(require_api_key)):
        """PROTECTED: Requires API key."""
        return module_instance.get_info()

    return router
