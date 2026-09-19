"""C4.3 — the upload body is the core's; what is left at the door is the door.

The body of `POST /ui/upload` moved to `core/files/attach.py` so that a second
door can attach a document to the same session (D4). Two things about that move
had nothing guarding them before this file existed:

1. **The translated error.** `core/` may not import `plugins/`, so the one
   message the upload answered through i18n now crosses as a stable CODE and
   the web door phrases it. If the door ever stops translating it, users start
   seeing `file_extract_failed` where they used to read a sentence — and the
   whole suite would have stayed green.
2. **The response body.** The claim that the move is invisible to the UI's JS
   rests on the door returning what the core builds, key for key.

The router is mounted with doubles at its edges (the seam `register_file_routes`
already offers) and the real handler in the middle: what is under test is what
the client receives, which is exactly what neither side can assert alone.
"""
from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import APIRouter, FastAPI
from fastapi.testclient import TestClient
from slowapi import _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded

from core.dependencies import limiter as core_limiter
from core.files.attach import FILE_EXTRACT_FAILED, attach_to_session
from plugins.web_ui_module.api.routes_files import register_file_routes
from plugins.web_ui_module.messages import get_message

DOC = b"Contingut de prova per a l'adjunt compartit."


@pytest.fixture(autouse=True)
def _no_rate_limit(monkeypatch):
    """@limiter.limit uses the singleton keyed by "testclient": across the full
    suite the counts accumulate and a spurious 429 fires."""
    monkeypatch.setattr(core_limiter, "enabled", False)


@pytest.fixture()
def session():
    s = MagicMock()
    s.id = "c43-session"
    return s


@pytest.fixture()
def session_mgr(session):
    mgr = MagicMock()
    mgr.is_valid_session_id.return_value = True
    mgr.get_or_create_session.return_value = session
    return mgr


@pytest.fixture()
def file_handler(tmp_path):
    fh = MagicMock()
    fh.validate_file.return_value = (True, None)
    saved = tmp_path / "c43_nota.txt"
    saved.write_bytes(DOC)
    fh.save_file = AsyncMock(return_value=saved)
    fh.extract_text_async = AsyncMock(return_value=DOC.decode())
    fh.chunk_text.return_value = ["Contingut de prova", "per a l'adjunt compartit."]
    return fh


@pytest.fixture()
def client(session_mgr, file_handler):
    router = APIRouter()
    register_file_routes(
        router,
        session_mgr=session_mgr,
        file_handler=file_handler,
        require_ui_auth=lambda: None,
    )
    app = FastAPI()
    app.state.limiter = core_limiter
    app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)
    app.include_router(router)
    return TestClient(app, raise_server_exceptions=False)


def _healthy_helper():
    helper = MagicMock()
    helper.save_document_chunks = AsyncMock(
        return_value={"success": True, "chunks_saved": 2}
    )
    return helper


def _upload(client):
    return client.post(
        "/upload",
        files={"file": ("c43_nota.txt", DOC, "text/plain")},
        data={"session_id": "c43-session"},
    )


def test_the_web_door_still_answers_the_extraction_failure_translated(client, file_handler):
    """The door translates; the code never reaches the user."""
    file_handler.extract_text_async = AsyncMock(return_value="")

    with patch("core.memory_facts.helper_for", return_value=_healthy_helper()):
        r = _upload(client)

    assert r.status_code == 400, r.text[:300]
    detail = r.json()["detail"]
    assert detail == get_message(None, "webui.file.extract_failed"), (
        "the web door must keep phrasing this one itself: the core hands it "
        f"over as a code so each door can, and this answered {detail!r}"
    )
    assert detail != FILE_EXTRACT_FAILED, (
        "the raw code reached the user — the door stopped translating it"
    )


@pytest.mark.asyncio
async def test_the_core_hands_the_extraction_failure_over_as_a_code(
    session_mgr, file_handler,
):
    """The other half of the same contract, measured at the core's edge.

    Without this, a door could keep its translation while the core quietly
    changed the code, and the test above would still pass.
    """
    from fastapi import HTTPException

    file_handler.extract_text_async = AsyncMock(return_value="")

    with pytest.raises(HTTPException) as exc:
        await attach_to_session(
            app_state=MagicMock(),
            session_mgr=session_mgr,
            file_handler=file_handler,
            filename="c43_nota.txt",
            content=DOC,
            session_id="c43-session",
        )

    assert exc.value.status_code == 400
    assert exc.value.detail == FILE_EXTRACT_FAILED, (
        "the core must not phrase this one — it has no i18n of its own and "
        f"plugins/ is out of its reach; it answered {exc.value.detail!r}"
    )
    file_handler.delete_file.assert_called_once(), "the unusable file stays on disk"


def test_the_door_returns_the_body_the_core_builds(client, session):
    """The UI's JS is untouched by the move because these keys are."""
    with patch("core.memory_facts.helper_for", return_value=_healthy_helper()):
        r = _upload(client)

    assert r.status_code == 200, r.text[:300]
    body = r.json()
    assert set(body) == {
        "filename", "size", "text_length", "chunks", "preview",
        "ingested", "chunks_saved", "session_id", "has_rag_header",
    }, f"the upload response grew or lost a key: {sorted(body)}"
    assert body["filename"] == "c43_nota.txt"
    assert body["size"] == len(DOC)
    assert body["chunks"] == 2
    assert body["ingested"] is True
    assert body["chunks_saved"] == 2
    assert body["session_id"] == session.id
    assert body["has_rag_header"] is False
