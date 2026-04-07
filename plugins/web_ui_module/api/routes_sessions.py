"""
------------------------------------
Server Nexe
Location: plugins/web_ui_module/api/routes_sessions.py
Description: Endpoints de gestio de sessions (CRUD + llistat).
             Extret de routes.py durant refactoring de tech debt.

www.jgoy.net · https://server-nexe.org
------------------------------------
"""

from typing import Dict, Any, Optional
import logging
from fastapi import APIRouter, HTTPException, Depends, Request

from plugins.web_ui_module.messages import get_message, get_i18n
from plugins.security.core.input_sanitizers import validate_string_input
from core.dependencies import limiter

logger = logging.getLogger(__name__)


def register_session_routes(router: APIRouter, *, session_mgr, require_ui_auth):
    """Registra endpoints: POST /session/new, GET /session/{id},
    DELETE /session/{id}, GET /session/{id}/history, GET /sessions"""

    # -- POST /session/new --

    @router.post("/session/new")
    async def create_session(request: Optional[Dict[str, Any]] = None, _auth=Depends(require_ui_auth)):
        """Crear nova sessio"""
        session = session_mgr.create_session()
        return {
            "session_id": session.id,
            "created_at": session.created_at.isoformat()
        }

    # -- GET /session/{session_id} --

    @router.get("/session/{session_id}")
    @limiter.limit("30/minute")
    async def get_session_info(request: Request, session_id: str, _auth=Depends(require_ui_auth)):
        """Obtenir info de sessio"""
        session_id = validate_string_input(session_id, max_length=100, context="path")
        session = session_mgr.get_session(session_id)
        if not session:
            raise HTTPException(status_code=404, detail=get_message(get_i18n(request), "webui.session.not_found"))
        return session.to_dict()

    # -- GET /session/{session_id}/history --

    @router.get("/session/{session_id}/history")
    @limiter.limit("30/minute")
    async def get_session_history(request: Request, session_id: str, _auth=Depends(require_ui_auth)):
        """Obtenir historial de sessio"""
        session_id = validate_string_input(session_id, max_length=100, context="path")
        session = session_mgr.get_session(session_id)
        if not session:
            raise HTTPException(status_code=404, detail=get_message(get_i18n(request), "webui.session.not_found"))
        return {"messages": session.get_history()}

    # -- DELETE /session/{session_id} --

    @router.delete("/session/{session_id}")
    @limiter.limit("10/minute")
    async def delete_session(request: Request, session_id: str, _auth=Depends(require_ui_auth)):
        """Eliminar sessio"""
        session_id = validate_string_input(session_id, max_length=100, context="path")
        deleted = session_mgr.delete_session(session_id)
        if not deleted:
            raise HTTPException(status_code=404, detail=get_message(get_i18n(request), "webui.session.not_found"))
        return {"status": "deleted"}

    # -- PATCH /session/{session_id} (rename) --

    @router.patch("/session/{session_id}")
    @limiter.limit("10/minute")
    async def rename_session(request: Request, session_id: str, _auth=Depends(require_ui_auth)):
        """Rename a session"""
        session_id = validate_string_input(session_id, max_length=100, context="path")
        session = session_mgr.get_session(session_id)
        if not session:
            raise HTTPException(status_code=404, detail=get_message(get_i18n(request), "webui.session.not_found"))
        body = await request.json()
        name = validate_string_input(body.get("name", ""), max_length=100, context="body")
        if not name or not name.strip():
            raise HTTPException(status_code=400, detail=get_message(get_i18n(request), "webui.session.name_length"))
        session.custom_name = name.strip()
        session_mgr.save_session(session_id)
        return {"ok": True, "name": session.custom_name}

    # -- POST /session/{session_id}/clear-document --

    @router.post("/session/{session_id}/clear-document")
    async def clear_document(request: Request, session_id: str, _auth=Depends(require_ui_auth)):
        """Netejar document adjuntat d'una sessio"""
        session_id = validate_string_input(session_id, max_length=100, context="path")
        session = session_mgr.get_session(session_id)
        if not session:
            raise HTTPException(status_code=404, detail=get_message(get_i18n(request), "webui.session.not_found"))
        session.attached_document = None
        session_mgr.save_session(session_id)
        return {"success": True}

    # -- GET /sessions --

    @router.get("/sessions")
    async def list_sessions(_auth=Depends(require_ui_auth)):
        """Llistar totes les sessions"""
        return {"sessions": session_mgr.list_sessions()}
