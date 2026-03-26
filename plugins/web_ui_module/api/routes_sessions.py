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
from fastapi import APIRouter, HTTPException, Depends

from plugins.web_ui_module.messages import get_message

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
    async def get_session_info(session_id: str, _auth=Depends(require_ui_auth)):
        """Obtenir info de sessio"""
        session = session_mgr.get_session(session_id)
        if not session:
            raise HTTPException(status_code=404, detail=get_message(None, "webui.session.not_found"))
        return session.to_dict()

    # -- GET /session/{session_id}/history --

    @router.get("/session/{session_id}/history")
    async def get_session_history(session_id: str, _auth=Depends(require_ui_auth)):
        """Obtenir historial de sessio"""
        session = session_mgr.get_session(session_id)
        if not session:
            raise HTTPException(status_code=404, detail=get_message(None, "webui.session.not_found"))
        return {"messages": session.get_history()}

    # -- DELETE /session/{session_id} --

    @router.delete("/session/{session_id}")
    async def delete_session(session_id: str, _auth=Depends(require_ui_auth)):
        """Eliminar sessio"""
        deleted = session_mgr.delete_session(session_id)
        if not deleted:
            raise HTTPException(status_code=404, detail=get_message(None, "webui.session.not_found"))
        return {"status": "deleted"}

    # -- GET /sessions --

    @router.get("/sessions")
    async def list_sessions(_auth=Depends(require_ui_auth)):
        """Llistar totes les sessions"""
        return {"sessions": session_mgr.list_sessions()}
