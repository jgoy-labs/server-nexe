"""G6 (#893) — a broken memory/ costs the document its index, not its attachment.

Uploading a file does two things: it attaches the document to the conversation,
and it indexes its chunks for RAG. Only the second one needs memory/. The
handler did them in the wrong order — indexing first at routes_files.py:252,
attaching at :264 — and `upload_file` has no try/except of its own (the only one
in the whole module guards an import). So a memory/ that was down turned an
upload into a 500 AND the document was never attached to the session, which
needs memory/ for nothing at all.

That is the rule of #888 stated for documents: "sense memòria" is "sense records
vells", never "sense conversa". An optional dependency must not be fatal for a
function that does not depend on it.

The response already had the vocabulary to say so: `ingested` is part of the
contract. It just never got the chance to be False.

The router is mounted with doubles at its edges (the seam register_file_routes
already offers) and the real upload_file handler in the middle: what is under
test is the ORDER of the two operations and what survives when the second one
fails, and neither can be seen by calling the pieces one by one.
"""
from __future__ import annotations

from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import APIRouter, FastAPI
from fastapi.testclient import TestClient
from slowapi import _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded

from core.dependencies import limiter as core_limiter
from plugins.web_ui_module.api.routes_files import register_file_routes

DOC = b"Contingut de prova. Val per adjuntar i per indexar."


@pytest.fixture(autouse=True)
def _no_rate_limit(monkeypatch):
    """@limiter.limit uses the singleton keyed by "testclient": across the full
    suite the counts accumulate and a spurious 429 fires."""
    monkeypatch.setattr(core_limiter, "enabled", False)


@pytest.fixture()
def calls():
    """Ordered log of what the handler did, so order can be asserted."""
    return []


@pytest.fixture()
def session(calls):
    s = MagicMock()
    s.id = "g6-session"
    s.add_context_file.side_effect = lambda *a, **k: calls.append("add_context_file")
    s.attach_document.side_effect = lambda *a, **k: calls.append("attach_document")
    return s


@pytest.fixture()
def session_mgr(session, calls):
    mgr = MagicMock()
    mgr.is_valid_session_id.return_value = True
    mgr.get_or_create_session.return_value = session
    mgr._save_session_to_disk.side_effect = lambda *a, **k: calls.append("save_session")
    return mgr


@pytest.fixture()
def file_handler(tmp_path):
    fh = MagicMock()
    fh.validate_file.return_value = (True, None)
    saved = tmp_path / "g6_nota.txt"
    saved.write_bytes(DOC)
    fh.save_file = AsyncMock(return_value=saved)
    fh.extract_text_async = AsyncMock(return_value=DOC.decode())
    fh.chunk_text.return_value = ["Contingut de prova.", "Val per adjuntar i per indexar."]
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


def _broken_helper():
    """Fails the way a down Qdrant fails it: save_document_chunks reaches
    collection_exists()/create_collection() with no guard above it."""
    helper = MagicMock()
    helper.save_document_chunks = AsyncMock(
        side_effect=RuntimeError("Qdrant is down: collection_exists failed")
    )
    return helper


def _healthy_helper(calls):
    helper = MagicMock()

    async def _save(**kwargs):
        calls.append("index")
        return {"success": True, "chunks_saved": len(kwargs.get("chunks", []))}

    helper.save_document_chunks = AsyncMock(side_effect=_save)
    return helper


def _upload(client):
    return client.post(
        "/upload",
        files={"file": ("g6_nota.txt", DOC, "text/plain")},
        data={"session_id": "g6-session"},
    )


def test_upload_survives_a_broken_memory(client):
    """The upload answers 200 and tells the truth about the indexing."""
    with patch(
        "core.memory_facts.helper_for",
        return_value=_broken_helper(),
    ):
        r = _upload(client)

    assert r.status_code == 200, (
        f"a broken memory/ must not take the upload with it, got "
        f"{r.status_code}: {r.text[:300]}"
    )
    body = r.json()
    assert body["ingested"] is False, (
        "the response must report the failed indexing, not hide it: " + str(body)
    )
    assert body["chunks_saved"] == 0


def test_the_document_is_attached_even_with_memory_broken(client, session, calls):
    """The point of the fix: the conversation keeps the document."""
    with patch(
        "core.memory_facts.helper_for",
        return_value=_broken_helper(),
    ):
        r = _upload(client)

    assert r.status_code == 200, r.text[:300]
    session.attach_document.assert_called_once()
    assert "attach_document" in calls, (
        "the indexing failure took the attachment with it: " + str(calls)
    )
    assert "save_session" in calls, (
        "the attachment was never persisted, so it dies with the process: "
        + str(calls)
    )


def test_the_attachment_happens_before_the_indexing(client, calls):
    """Order is the fix, not a detail.

    The same guarantee the chat path already gives (the user's turn is written
    to disk before memory/ enters the scene): whatever the indexing does, the
    conversation already has the document.
    """
    with patch(
        "core.memory_facts.helper_for",
        return_value=_healthy_helper(calls),
    ):
        r = _upload(client)

    assert r.status_code == 200, r.text[:300]
    assert "attach_document" in calls and "index" in calls, calls
    assert calls.index("attach_document") < calls.index("index"), (
        "indexing runs before the document is attached — the old order, where "
        f"a memory/ failure costs the conversation its document: {calls}"
    )


def test_a_healthy_memory_still_reports_ingested(client, calls):
    """Calibration: without it the gate would pass on a handler that dropped
    the indexing altogether."""
    helper = _healthy_helper(calls)
    with patch(
        "core.memory_facts.helper_for",
        return_value=helper,
    ):
        r = _upload(client)

    assert r.status_code == 200, r.text[:300]
    body = r.json()
    assert body["ingested"] is True, body
    assert body["chunks_saved"] == 2, body
    helper.save_document_chunks.assert_awaited_once()
