"""
------------------------------------
Server Nexe
Location: plugins/web_ui_module/api/routes_memory.py
Description: Endpoints de memoria (save/recall explicit).
             Extret de routes.py durant refactoring de tech debt.

www.jgoy.net · https://server-nexe.org
------------------------------------
"""

from typing import Dict, Any
import logging
from fastapi import APIRouter, HTTPException, Depends, Request

from plugins.web_ui_module.messages import get_message
from plugins.security.core.input_sanitizers import validate_string_input
from core.dependencies import limiter

def _get_memory_helper():
    """Lazy resolve via routes module so test patches work."""
    import plugins.web_ui_module.api.routes as _r
    return _r.get_memory_helper()

logger = logging.getLogger(__name__)


def register_memory_routes(router: APIRouter, *, require_ui_auth):
    """Registra endpoints: POST /memory/save, POST /memory/recall"""

    # -- POST /memory/save --

    @router.post("/memory/save")
    @limiter.limit("10/minute")
    async def memory_save(request: Request, body: Dict[str, Any], _auth=Depends(require_ui_auth)):
        """Guardar contingut explicitament a la memoria (via MemoryService if available)"""
        content = body.get("content", "")
        session_id = body.get("session_id", "unknown")
        metadata = body.get("metadata", {})

        # Security: validate input (XSS, SQL injection, path traversal)
        content = validate_string_input(content, max_length=5000, context="chat")
        session_id = validate_string_input(session_id, max_length=100, context="path")

        if not content:
            raise HTTPException(status_code=400, detail=get_message(None, "webui.memory.content_required"))

        memory_helper = _get_memory_helper()
        result = await memory_helper.save_to_memory(
            content=content,
            session_id=session_id,
            metadata=metadata
        )

        return result

    # -- POST /memory/recall --

    @router.post("/memory/recall")
    @limiter.limit("30/minute")
    async def memory_recall(request: Request, body: Dict[str, Any], _auth=Depends(require_ui_auth)):
        """Cercar a la memoria"""
        query = body.get("query", "")
        limit = body.get("limit", 5)

        # Security: validate input
        if not query:
            raise HTTPException(status_code=400, detail=get_message(None, "webui.memory.query_required"))
        query = validate_string_input(query, max_length=1000, context="chat")

        memory_helper = _get_memory_helper()
        result = await memory_helper.recall_from_memory(
            query=query,
            limit=limit
        )

        return result
