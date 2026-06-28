"""
MC-078 — POST /upload ha de rebutjar (413) un cos més gran que MAX_FILE_SIZE
ABANS de carregar-lo sencer a memòria (límit pre-read amb read(MAX+1)).
"""
from __future__ import annotations

import pytest
from unittest.mock import MagicMock
from fastapi import FastAPI, APIRouter
from fastapi.testclient import TestClient
from slowapi.errors import RateLimitExceeded
from slowapi import _rate_limit_exceeded_handler

import plugins.web_ui_module.core.file_handler as fh
from plugins.web_ui_module.api.routes_files import register_file_routes
from core.dependencies import limiter as core_limiter


@pytest.fixture(autouse=True)
def _no_rate_limit(monkeypatch):
    # The @limiter.limit("5/minute") decorator uses the singleton
    # core.dependencies.limiter (not app.state.limiter), and the "testclient" key
    # is shared → across the full suite counts accumulate and a spurious 429
    # fires. Disabling the limiter during these tests avoids it.
    monkeypatch.setattr(core_limiter, "enabled", False)


def _client(session_valid=True) -> TestClient:
    router = APIRouter()
    session_mgr = MagicMock()
    session_mgr.is_valid_session_id.return_value = session_valid
    file_handler = MagicMock()
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


def test_upload_larger_than_max_is_413(monkeypatch):
    monkeypatch.setattr(fh, "MAX_FILE_SIZE", 50)
    big = b"x" * 100  # > MAX (50)
    r = _client().post("/upload", files={"file": ("big.txt", big, "text/plain")})
    assert r.status_code == 413


def test_upload_at_limit_not_413(monkeypatch):
    """A body <= MAX must not be rejected by the pre-read limit (it may fail
    further down due to the mocked validation, but NEVER with 413)."""
    monkeypatch.setattr(fh, "MAX_FILE_SIZE", 50)
    small = b"x" * 10
    r = _client().post("/upload", files={"file": ("small.txt", small, "text/plain")})
    assert r.status_code != 413
