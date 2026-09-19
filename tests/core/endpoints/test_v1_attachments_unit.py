"""
────────────────────────────────────
Server Nexe
Author: Jordi Goy
Location: tests/core/endpoints/test_v1_attachments_unit.py
Description: Unit tests for POST /v1/attachments (C4.3-b) — pre-read 413,
             503 when session_manager/file_handler are missing, invalid
             X-Session-Id, and that the extraction failure leaves as a raw
             code (no i18n, unlike /ui/upload). Calcat de
             tests/plugins/web_ui_module/unit/test_mc078_upload_size.py.

www.jgoy.net · https://server-nexe.org
────────────────────────────────────
"""
from __future__ import annotations

from unittest.mock import MagicMock

import pytest
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient
from slowapi import _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded

import core.files.handler as fh
from core.dependencies import limiter as core_limiter
from core.endpoints.attachments import router
from core.files import attach as _attach
from core.security.auth_dependencies import require_api_key


@pytest.fixture(autouse=True)
def _no_rate_limit(monkeypatch):
    # Same reason as test_mc078_upload_size.py: @limiter.limit uses the
    # core.dependencies singleton, whose counters accumulate across the suite.
    monkeypatch.setattr(core_limiter, "enabled", False)


def _sessionish(valid: bool = True) -> MagicMock:
    mgr = MagicMock()
    mgr.is_valid_session_id.return_value = valid
    return mgr


def _client(*, session_mgr=None, file_handler=None) -> TestClient:
    app = FastAPI()
    app.state.limiter = core_limiter
    app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)
    app.state.session_manager = session_mgr
    app.state.file_handler = file_handler
    app.dependency_overrides[require_api_key] = lambda: "test-key"
    app.include_router(router)
    return TestClient(app, raise_server_exceptions=False)


def test_upload_larger_than_max_is_413(monkeypatch):
    monkeypatch.setattr(fh, "MAX_FILE_SIZE", 50)
    big = b"x" * 100
    r = _client(session_mgr=_sessionish(), file_handler=MagicMock()).post(
        "/attachments", files={"file": ("big.txt", big, "text/plain")}
    )
    assert r.status_code == 413
    assert r.json()["detail"] == "file_too_large"


def test_upload_at_limit_not_413(monkeypatch):
    """A body of EXACTLY MAX_FILE_SIZE bytes must not be rejected by the
    pre-read limit (it may fail further down since attach_to_session sees a
    mocked file_handler, but NEVER with 413). At the boundary on purpose —
    10 bytes against a 50-byte max would not catch `>` silently becoming
    `>=`; this would."""
    monkeypatch.setattr(fh, "MAX_FILE_SIZE", 50)
    at_limit = b"x" * 50
    r = _client(session_mgr=_sessionish(), file_handler=MagicMock()).post(
        "/attachments", files={"file": ("at_limit.txt", at_limit, "text/plain")}
    )
    assert r.status_code != 413


def test_missing_file_handler_returns_503():
    r = _client(session_mgr=_sessionish(), file_handler=None).post(
        "/attachments", files={"file": ("a.txt", b"hola", "text/plain")}
    )
    assert r.status_code == 503
    assert r.json()["detail"] == "attachments_unavailable"


def test_missing_session_manager_returns_503():
    r = _client(session_mgr=None, file_handler=MagicMock()).post(
        "/attachments", files={"file": ("a.txt", b"hola", "text/plain")}
    )
    assert r.status_code == 503
    assert r.json()["detail"] == "attachments_unavailable"


def test_invalid_x_session_id_returns_400():
    r = _client(session_mgr=_sessionish(valid=False), file_handler=MagicMock()).post(
        "/attachments",
        headers={"X-Session-Id": "../etc/passwd"},
        files={"file": ("a.txt", b"hola", "text/plain")},
    )
    assert r.status_code == 400
    assert r.json()["detail"] == "invalid_session_id"


def test_extract_failed_returns_raw_code_not_translated(monkeypatch):
    """Unlike /ui/upload (which translates this via get_message), /v1 has no
    i18n to reach — the code must leave exactly as attach_to_session raised
    it. Asserted against the CONSTANT, not a copy of today's string: a
    hardcoded "file_extract_failed" here would pass whether or not the
    endpoint actually propagates it untouched, since that string happens to
    equal FILE_EXTRACT_FAILED's own value — this would keep passing even if
    a future rewrite reintroduced a translation step."""
    async def _raise(**kwargs):
        raise HTTPException(status_code=400, detail=_attach.FILE_EXTRACT_FAILED)

    monkeypatch.setattr(_attach, "attach_to_session", _raise)
    r = _client(session_mgr=_sessionish(), file_handler=MagicMock()).post(
        "/attachments", files={"file": ("a.pdf", b"%PDF-broken", "application/pdf")}
    )
    assert r.status_code == 400
    assert r.json()["detail"] == _attach.FILE_EXTRACT_FAILED


def test_other_http_exceptions_propagate_unchanged(monkeypatch):
    async def _raise(**kwargs):
        raise HTTPException(status_code=400, detail="sensitive_content_rejected")

    monkeypatch.setattr(_attach, "attach_to_session", _raise)
    r = _client(session_mgr=_sessionish(), file_handler=MagicMock()).post(
        "/attachments", files={"file": ("a.txt", b"root:x:0:0:", "text/plain")}
    )
    assert r.status_code == 400
    assert r.json()["detail"] == "sensitive_content_rejected"
