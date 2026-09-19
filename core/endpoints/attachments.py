"""
────────────────────────────────────
Server Nexe
Author: Jordi Goy
Location: core/endpoints/attachments.py
Description: POST /v1/attachments — upload a document, attach it to a
             session, index it for RAG. The API door onto the same body
             `/ui/upload` has used since C4.3.

www.jgoy.net · https://server-nexe.org
────────────────────────────────────

C4.3-b: `core/files/attach.py::attach_to_session` has been door-neutral since
C4.3, and `FileHandler` has been a process-wide instance (not the web UI
plugin's alone) since `attach_file_handler`. This endpoint is what those two
moves were for — a second door that reaches both without importing `plugins/`.

`session_id` comes from the `X-Session-Id` header, not `derive_session_id`
(chat_engines/_common.py): that function derives an id from `body.messages`,
which a multipart upload does not have, and falling back to its API-key hash
would collide every attachment from the same key into one session. Without
the header, `attach_to_session` creates a new session — the same behaviour
`/ui/upload` gets from an empty `Form(None)`.

No i18n here, same as the rest of `/v1` (`memory/memory/api/v1.py`): errors
are stable codes in English, not translated sentences.
"""

from typing import Optional

from fastapi import APIRouter, Depends, File, Header, HTTPException, Request, UploadFile

from core.dependencies import limiter
from core.files import attach as _attach
from core.files import handler as _fh
from core.security.auth_dependencies import require_api_key

router = APIRouter()


@router.post(
    "/attachments",
    dependencies=[Depends(require_api_key)],
    summary="Upload a document, attach it to a session, index it for RAG",
    operation_id="v1_attachments_create",
)
@limiter.limit("5/minute")
async def create_attachment(
    request: Request,
    file: UploadFile = File(...),
    x_session_id: Optional[str] = Header(None, alias="X-Session-Id"),
):
    """Upload a document via the API — the `/v1` counterpart of `POST /ui/upload`.

    Returns the same body `attach_to_session` has always returned: `filename,
    size, text_length, chunks, preview, ingested, chunks_saved, session_id,
    has_rag_header`. A client of the API and the web UI see the same contract;
    only the language of the errors differs, by design.
    """
    session_mgr = getattr(request.app.state, "session_manager", None)
    file_handler = getattr(request.app.state, "file_handler", None)
    if session_mgr is None or file_handler is None:
        raise HTTPException(status_code=503, detail="attachments_unavailable")

    if x_session_id is not None and not session_mgr.is_valid_session_id(x_session_id):
        raise HTTPException(status_code=400, detail="invalid_session_id")

    # MC-078: read capped at the limit + 1 byte, so a 413 does not first buffer
    # an oversized upload in memory — same guard as POST /ui/upload.
    content = await file.read(_fh.MAX_FILE_SIZE + 1)
    if len(content) > _fh.MAX_FILE_SIZE:
        raise HTTPException(status_code=413, detail="file_too_large")

    # No wrapping: every rejection attach_to_session raises is already an
    # HTTPException carrying a stable code (FILE_EXTRACT_FAILED included) —
    # /ui/upload translates that one code via get_message(); /v1 has no i18n
    # to reach (core/ may not import plugins/), so it propagates untouched.
    return await _attach.attach_to_session(
        app_state=request.app.state,
        session_mgr=session_mgr,
        file_handler=file_handler,
        filename=file.filename,
        content=content,
        session_id=x_session_id,
    )
