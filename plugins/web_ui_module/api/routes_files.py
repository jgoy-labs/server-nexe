"""
------------------------------------
Server Nexe
Location: plugins/web_ui_module/api/routes_files.py
Description: File upload and management endpoints.
             Extracted from routes.py during tech debt refactoring.

www.jgoy.net · https://server-nexe.org
------------------------------------

C4.3: the body of POST /upload moved to `core/files/attach.py` — an attachment
belongs to the session, not to this door. What stays here is what IS this door:
the route, `require_ui_auth`, the rate limit, the session-id 400, the capped
read (this door holds the stream), and the translation of the one error whose
detail crosses as a code because `core/` may not import this plugin's i18n.
"""

from typing import Optional
import logging
from fastapi import APIRouter, HTTPException, UploadFile, File, Form, Depends, Request

from plugins.web_ui_module.messages import get_message, get_i18n
from core.dependencies import limiter
from core.files import attach as _attach
from core.files import handler as _fh

logger = logging.getLogger(__name__)


# ── File routes ──────────────────────────────────────────────────

def register_file_routes(router: APIRouter, *, session_mgr, file_handler, require_ui_auth):
    """Registers endpoints: POST /upload, GET /files, DELETE /files/cleanup"""

    # -- POST /upload --

    @router.post("/upload", operation_id="webui_upload_file")
    @limiter.limit("5/minute")
    async def upload_file(
        request: Request,
        file: UploadFile = File(...),
        session_id: Optional[str] = Form(None),
        _auth=Depends(require_ui_auth),
        i18n=Depends(get_i18n),
    ):
        """Upload file and add to session context + automatic memory ingestion"""
        # RT-10: reject malformed/traversal session ids with a clean 400 —
        # SessionManager blocks them anyway, but via ValueError → 500.
        if session_id is not None and not session_mgr.is_valid_session_id(session_id):
            raise HTTPException(status_code=400, detail="Invalid session_id")
        # MC-078: pre-read limit — do not load the whole body into memory before
        # validating the size. read(MAX+1) stops the read; over the cap → 413.
        # (Mitigates the memory DoS; a total receive limit would live in uvicorn.)
        content = await file.read(_fh.MAX_FILE_SIZE + 1)
        if len(content) > _fh.MAX_FILE_SIZE:
            raise HTTPException(status_code=413, detail="File too large")

        try:
            return await _attach.attach_to_session(
                app_state=request.app.state,
                session_mgr=session_mgr,
                file_handler=file_handler,
                filename=file.filename,
                content=content,
                session_id=session_id,
            )
        except HTTPException as exc:
            # The core hands this one over as a stable code so that each door
            # can phrase it; this one has always answered it translated, and
            # the response stays byte-identical to before the move.
            if exc.status_code == 400 and exc.detail == _attach.FILE_EXTRACT_FAILED:
                raise HTTPException(
                    status_code=400, detail=get_message(i18n, "webui.file.extract_failed"),
                ) from None
            raise

    # -- GET /files --

    @router.get("/files", operation_id="webui_list_files")
    async def list_uploaded_files(_auth=Depends(require_ui_auth)):
        """List all uploaded files"""
        files = file_handler.get_uploaded_files()
        return {"files": files, "total": len(files)}

    # -- POST /files/cleanup --

    @router.post("/files/cleanup", operation_id="webui_cleanup_files")
    @limiter.limit("5/minute")
    async def cleanup_files(request: Request, max_age_hours: int = 24, _auth=Depends(require_ui_auth)):
        """Clean up old files (default > 24h)"""
        # MC-072 (confirmed reachable in red team RT-06): without a minimum bound,
        # max_age_hours=0 or negative would delete ALL the user's uploads.
        if max_age_hours < 1:
            raise HTTPException(status_code=422, detail="max_age_hours must be >= 1")
        deleted = file_handler.cleanup_old_files(max_age_hours)
        return {"deleted": deleted, "message": f"{deleted} files deleted"}
