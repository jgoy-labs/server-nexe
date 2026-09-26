"""
------------------------------------
Server Nexe
Location: plugins/web_ui_module/api/routes_memory.py
Description: Memory endpoints (explicit save/recall).
             Extracted from routes.py during tech debt refactoring.

www.jgoy.net · https://server-nexe.org
------------------------------------
"""

from typing import Dict, Any
import logging
from fastapi import APIRouter, HTTPException, Depends, Request

from plugins.web_ui_module.messages import get_message, get_i18n
# R6-15 v1.0.4: tolerate absent security plugin (endpoints gated by require_ui_auth).
try:
    from core.security.input_sanitizers import validate_string_input  # pyright: ignore[reportAssignmentType]
except ImportError:
    def validate_string_input(s, *a, **k):  # type: ignore[misc, no-redef]
        return s
from core.dependencies import limiter
from core.log_redact import redact_user_content
import core.memory_facts as memory_facts
from core.memory_facts.deletes import confirm_pending_delete

logger = logging.getLogger(__name__)


def register_memory_routes(router: APIRouter, *, session_mgr, require_ui_auth):
    """Registers endpoints: POST /memory/save, POST /memory/recall, POST /memory/confirm-delete"""

    # -- POST /memory/save --

    @router.post("/memory/save", operation_id="webui_memory_save")
    @limiter.limit("10/minute")
    async def memory_save(request: Request, body: Dict[str, Any], _auth=Depends(require_ui_auth)):
        """Explicitly save content to memory (via MemoryService if available)"""
        content = body.get("content", "")
        session_id = body.get("session_id", "unknown")
        metadata = body.get("metadata", {})

        # Security: validate input (XSS, SQL injection, path traversal)
        content = validate_string_input(content, max_length=5000, context="chat")
        session_id = validate_string_input(session_id, max_length=100, context="path")

        if not content:
            raise HTTPException(status_code=400, detail=get_message(get_i18n(request), "webui.memory.content_required"))

        memory_helper = memory_facts.helper_for(request.app.state)
        result = await memory_helper.save_to_memory(
            content=content,
            session_id=session_id,
            metadata=metadata
        )

        return result

    # -- POST /memory/recall --

    @router.post("/memory/recall", operation_id="webui_memory_recall")
    @limiter.limit("30/minute")
    async def memory_recall(request: Request, body: Dict[str, Any], _auth=Depends(require_ui_auth)):
        """Search in memory"""
        query = body.get("query", "")
        limit = body.get("limit", 5)

        # Security: validate input
        if not query:
            raise HTTPException(status_code=400, detail=get_message(get_i18n(request), "webui.memory.query_required"))
        query = validate_string_input(query, max_length=1000, context="chat")

        memory_helper = memory_facts.helper_for(request.app.state)
        result = await memory_helper.recall_from_memory(
            query=query,
            limit=limit
        )

        return result

    # -- POST /memory/confirm-delete --

    @router.post("/memory/confirm-delete", operation_id="webui_memory_confirm_delete")
    @limiter.limit("10/minute")
    async def memory_confirm_delete(request: Request, body: Dict[str, Any], _auth=Depends(require_ui_auth)):
        """The dialog's button: delete THE entry this session has pending, by id.

        C4.5 (decision of 26/09). Until now this searched memory again by the
        dialog's text and deleted the best match — not necessarily the entry
        the user was shown, without the B093 guard the typed "sí" applies, and
        leaving the pending flag armed. Now it takes the same core path a typed
        "sí" takes (`confirm_pending_delete`): exact id, B093, flag cleared.
        `fact` is the text the dialog showed — the explicit reference B093
        asks for. Nothing pending → 404, nothing deleted.
        """
        session_id = validate_string_input(
            str(body.get("session_id") or "").strip(), max_length=100, context="path",
        )
        fact = validate_string_input(str(body.get("fact") or "").strip(), max_length=500, context="chat")
        if not session_id:
            raise HTTPException(status_code=400, detail="session_id required")
        session = session_mgr.get_session(session_id)
        memory_helper = memory_facts.helper_for(request.app.state)
        if session is None:
            raise HTTPException(status_code=404, detail="session not found")
        pending = bool(getattr(session, "_pending_partial_delete", None))
        outcome = await confirm_pending_delete(session, memory_helper, fact)
        if not pending:
            # The core answered "nothing pending" in the server's language.
            raise HTTPException(status_code=404, detail=outcome.text)
        logger.info(
            "MEM_DELETE confirmed by user (dialog): %s → deleted=%d [%s]",
            redact_user_content(fact), outcome.mem_deleted, outcome.memory_action,
        )
        return {
            "success": outcome.memory_action != "delete_blocked",
            "deleted": outcome.mem_deleted,
            "deleted_facts": [{"text": text} for text in outcome.deleted_facts],
            "message": outcome.text,
            "memory_action": outcome.memory_action,
        }
