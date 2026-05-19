"""
────────────────────────────────────
Server Nexe
Location: tests/test_installer_endpoints.py
Description: Unit tests for F5.3 installer HTTP endpoints
             (GET /installer/download, POST /installer/ollama, GET /installer/finalize).

www.jgoy.net · https://server-nexe.org
────────────────────────────────────
"""

import os
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from core.endpoints.installer import router, _VALID_ENGINES


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture()
def app():
    a = FastAPI()
    a.include_router(router)
    return a


@pytest.fixture()
def client(app):
    return TestClient(app, raise_server_exceptions=True)


# ---------------------------------------------------------------------------
# /installer/finalize
# ---------------------------------------------------------------------------

class TestFinalize:
    def test_returns_json_with_status_ready(self, client):
        resp = client.get("/installer/finalize")
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "ready"
        assert "api_key" in data

    def test_returns_api_key_from_env(self, client, monkeypatch):
        monkeypatch.setenv("NEXE_PRIMARY_API_KEY", "test-key-xyz")
        resp = client.get("/installer/finalize")
        assert resp.json()["api_key"] == "test-key-xyz"

    def test_returns_empty_key_when_env_unset(self, client, monkeypatch):
        monkeypatch.delenv("NEXE_PRIMARY_API_KEY", raising=False)
        resp = client.get("/installer/finalize")
        assert resp.json()["api_key"] == ""


# ---------------------------------------------------------------------------
# /installer/download — engine validation
# ---------------------------------------------------------------------------

class TestDownloadValidation:
    def test_rejects_unknown_engine(self, client):
        """An unknown engine returns an error SSE event (not HTTP 4xx)."""
        resp = client.get("/installer/download?engine=bad_engine&model_id=foo")
        assert resp.status_code == 200
        assert "text/event-stream" in resp.headers.get("content-type", "")
        assert '"type": "error"' in resp.text
        assert "bad_engine" in resp.text

    @pytest.mark.parametrize("engine", sorted(_VALID_ENGINES))
    def test_valid_engines_do_not_return_error_event(self, client, engine):
        """Each valid engine must return at least one non-error SSE event."""
        resp = client.get(f"/installer/download?engine={engine}&model_id=test-model")
        assert resp.status_code == 200
        body = resp.text
        # The stub / real path must emit at least a 'done' event.
        assert '"type": "done"' in body or '"type": "progress"' in body


# ---------------------------------------------------------------------------
# /installer/download — SSE format
# ---------------------------------------------------------------------------

class TestDownloadSSE:
    def test_content_type_is_event_stream(self, client):
        resp = client.get("/installer/download?engine=ollama&model_id=gemma3:4b")
        assert "text/event-stream" in resp.headers.get("content-type", "")

    def test_each_line_is_data_prefix(self, client):
        resp = client.get("/installer/download?engine=ollama&model_id=gemma3:4b")
        lines = [l for l in resp.text.splitlines() if l.strip()]
        data_lines = [l for l in lines if l.startswith("data:")]
        assert len(data_lines) >= 1, "Expected at least one 'data:' line"

    def test_done_event_contains_model_id(self, client):
        resp = client.get("/installer/download?engine=ollama&model_id=gemma3:4b")
        assert "gemma3:4b" in resp.text

    def test_cache_control_header_set(self, client):
        resp = client.get("/installer/download?engine=ollama&model_id=foo")
        assert resp.headers.get("cache-control") == "no-cache"


# ---------------------------------------------------------------------------
# /installer/ollama
# ---------------------------------------------------------------------------

class TestOllamaEndpoint:
    def test_returns_done_event(self, client):
        resp = client.post("/installer/ollama")
        assert resp.status_code == 200
        assert '"type": "done"' in resp.text

    def test_content_type_is_event_stream(self, client):
        resp = client.post("/installer/ollama")
        assert "text/event-stream" in resp.headers.get("content-type", "")

    def test_already_installed_field_present(self, client):
        resp = client.post("/installer/ollama")
        import json as _json
        data_lines = [l[5:].strip() for l in resp.text.splitlines() if l.startswith("data:")]
        events = [_json.loads(l) for l in data_lines if l]
        done_events = [e for e in events if e.get("type") == "done"]
        assert done_events, "Expected at least one 'done' event"
        assert "already_installed" in done_events[-1]


# ---------------------------------------------------------------------------
# _VALID_ENGINES constant
# ---------------------------------------------------------------------------

class TestValidEngines:
    def test_contains_expected_engines(self):
        assert "mlx" in _VALID_ENGINES
        assert "ollama" in _VALID_ENGINES
        assert "gguf" in _VALID_ENGINES

    def test_does_not_contain_unknown(self):
        assert "bad" not in _VALID_ENGINES
        assert "torchscript" not in _VALID_ENGINES
