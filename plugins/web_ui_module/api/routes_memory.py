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
from fastapi import APIRouter, HTTPException, Depends

from plugins.web_ui_module.messages import get_message

def _get_memory_helper():
    """Lazy resolve via routes module so test patches work."""
    import plugins.web_ui_module.api.routes as _r
    return _r.get_memory_helper()

logger = logging.getLogger(__name__)


def register_memory_routes(router: APIRouter, *, require_ui_auth):
    """Registra endpoints: POST /memory/save, POST /memory/recall"""

    # -- POST /memory/save --

    @router.post("/memory/save")
    async def memory_save(request: Dict[str, Any], _auth=Depends(require_ui_auth)):
        """Guardar contingut explicitament a la memoria"""
        content = request.get("content", "")
        session_id = request.get("session_id", "unknown")
        metadata = request.get("metadata", {})

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
    async def memory_recall(request: Dict[str, Any], _auth=Depends(require_ui_auth)):
        """Cercar a la memoria"""
        query = request.get("query", "")
        limit = request.get("limit", 5)

        if not query:
            raise HTTPException(status_code=400, detail=get_message(None, "webui.memory.query_required"))

        memory_helper = _get_memory_helper()
        result = await memory_helper.recall_from_memory(
            query=query,
            limit=limit
        )

        return result
