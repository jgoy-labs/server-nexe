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


@pytest.fixture()
def isolated_data_dir(tmp_path, monkeypatch):
    """Point NEXE_DATA_DIR at a fresh tmp dir so the /installer/finalize
    idempotency marker and any OnboardingState file live in test scope."""
    monkeypatch.setenv("NEXE_DATA_DIR", str(tmp_path))
    return tmp_path


# ---------------------------------------------------------------------------
# /installer/finalize
# ---------------------------------------------------------------------------

class TestFinalize:
    def test_returns_json_with_status_ready(self, client, isolated_data_dir):
        resp = client.get("/installer/finalize")
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "ready"
        assert "api_key" in data

    def test_returns_api_key_from_env(self, client, isolated_data_dir, monkeypatch):
        monkeypatch.setenv("NEXE_PRIMARY_API_KEY", "test-key-xyz")
        resp = client.get("/installer/finalize")
        assert resp.json()["api_key"] == "test-key-xyz"

    def test_returns_empty_key_when_env_unset(self, client, isolated_data_dir, monkeypatch):
        monkeypatch.delenv("NEXE_PRIMARY_API_KEY", raising=False)
        resp = client.get("/installer/finalize")
        assert resp.json()["api_key"] == ""

    def test_second_call_returns_404_idempotency_marker(self, client, isolated_data_dir):
        """The Advanced wizard flow only calls GET /installer/finalize once.
        A second call would be either a duplicate request or a local process
        attempting to read NEXE_PRIMARY_API_KEY post-onboarding — both 404."""
        first = client.get("/installer/finalize")
        assert first.status_code == 200
        marker = isolated_data_dir / ".finalize_called"
        assert marker.exists()
        second = client.get("/installer/finalize")
        assert second.status_code == 404

    def test_concurrent_calls_only_one_returns_key(self, client, isolated_data_dir):
        """The TOCTOU window between marker.exists() and marker.touch() must
        be closed: with N concurrent GETs, exactly one returns 200 (the
        creator of the O_EXCL marker) and the rest return 404."""
        from concurrent.futures import ThreadPoolExecutor

        n = 16

        def _hit() -> int:
            return client.get("/installer/finalize").status_code

        with ThreadPoolExecutor(max_workers=n) as ex:
            statuses = list(ex.map(lambda _: _hit(), range(n)))

        assert statuses.count(200) == 1, (
            f"exactly one caller must win; got {statuses.count(200)} 200s "
            f"out of {n} (full: {statuses})"
        )
        assert statuses.count(404) == n - 1

    def test_returns_404_when_onboarding_already_completed(
        self, client, isolated_data_dir
    ):
        """When OnboardingState has been persisted (Normal flow finalized via
        POST), the legacy GET must not leak the api_key any longer."""
        from core.onboarding_state import OnboardingState

        OnboardingState.save(
            engine="mlx",
            model_id="mlx-community/test-model",
            model_path=str(isolated_data_dir / "test-model"),
            hf_token=None,
        )
        resp = client.get("/installer/finalize")
        assert resp.status_code == 404


class TestSafeModelBasename:
    """Basename guard helper used by _resolve_model_path and the streamers."""

    def test_rejects_dot(self):
        from core.endpoints.installer import _safe_model_basename

        with pytest.raises(ValueError, match="invalid model_id"):
            _safe_model_basename(".")

    def test_rejects_double_dot(self):
        from core.endpoints.installer import _safe_model_basename

        with pytest.raises(ValueError, match="invalid model_id"):
            _safe_model_basename("..")

    def test_rejects_trailing_slash(self):
        from core.endpoints.installer import _safe_model_basename

        with pytest.raises(ValueError, match="invalid model_id"):
            _safe_model_basename("mlx-community/")

    def test_rejects_org_dotdot(self):
        from core.endpoints.installer import _safe_model_basename

        with pytest.raises(ValueError, match="invalid model_id"):
            _safe_model_basename("mlx-community/..")

    def test_accepts_org_name(self):
        from core.endpoints.installer import _safe_model_basename

        assert _safe_model_basename("mlx-community/gemma-3-4b-it-4bit") == "gemma-3-4b-it-4bit"

    def test_accepts_bare_name(self):
        from core.endpoints.installer import _safe_model_basename

        assert _safe_model_basename("gemma3:4b") == "gemma3:4b"


class TestDownloadEndpointBasenameGuard:
    """The /installer/download query endpoint must reject pathological
    model_id values (engine in {mlx, gguf}) BEFORE the SSE stream runs."""

    def test_mlx_with_dotdot_returns_invalid_model_id_event(self, client):
        resp = client.get("/installer/download?engine=mlx&model_id=..")
        assert resp.status_code == 200
        assert "text/event-stream" in resp.headers["content-type"]
        body = resp.text
        assert "INVALID_MODEL_ID" in body
        assert "invalid model_id" in body

    def test_gguf_with_dot_returns_invalid_model_id_event(self, client):
        resp = client.get("/installer/download?engine=gguf&model_id=.")
        body = resp.text
        assert "INVALID_MODEL_ID" in body

    def test_ollama_does_not_apply_basename_guard(self, client):
        # gemma3:4b is a legitimate ollama tag; even ':' or '..' inside an
        # ollama identifier is not a path component on disk.
        resp = client.get("/installer/download?engine=ollama&model_id=gemma3:4b")
        body = resp.text
        assert "INVALID_MODEL_ID" not in body


class TestResolveModelPath:
    """Path traversal guard on _resolve_model_path."""

    def test_rejects_double_dot_model_id(self):
        from core.endpoints.installer import _resolve_model_path

        with pytest.raises(ValueError, match="invalid model_id"):
            _resolve_model_path("mlx", "..")

    def test_rejects_single_dot_model_id(self):
        from core.endpoints.installer import _resolve_model_path

        with pytest.raises(ValueError, match="invalid model_id"):
            _resolve_model_path("gguf", ".")

    def test_rejects_trailing_slash_model_id(self):
        """model_id ending in '/' yields an empty basename — invalid."""
        from core.endpoints.installer import _resolve_model_path

        with pytest.raises(ValueError, match="invalid model_id"):
            _resolve_model_path("mlx", "mlx-community/")

    def test_rejects_double_dot_at_end_path_traversal(self, tmp_path, monkeypatch):
        """Basename '..' would resolve to the parent of models_dir."""
        from core.endpoints.installer import _resolve_model_path

        monkeypatch.setenv("NEXE_DATA_DIR", str(tmp_path))
        # 'mlx-community/..' -> basename '..'; the early check catches this.
        with pytest.raises(ValueError, match="invalid model_id"):
            _resolve_model_path("mlx", "mlx-community/..")

    def test_accepts_normal_mlx_model_id(self, tmp_path, monkeypatch):
        from core.endpoints.installer import _resolve_model_path

        monkeypatch.setenv("NEXE_DATA_DIR", str(tmp_path))
        out = _resolve_model_path("mlx", "mlx-community/gemma-3-4b-it-4bit")
        assert out.endswith("/gemma-3-4b-it-4bit")
        assert str(tmp_path) in out

    def test_finalize_post_returns_400_on_invalid_model_id(self, client, isolated_data_dir):
        """The POST endpoint must reject the bad model_id with 400, not 500."""
        resp = client.post(
            "/installer/finalize",
            json={"engine": "mlx", "model_id": ".."},
        )
        # FinalizeBody pattern allows ".." (length>=1) so the validator passes;
        # _resolve_model_path then raises ValueError -> 400.
        assert resp.status_code == 400
        assert "invalid model_id" in resp.json()["detail"]


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
    def test_valid_engines_do_not_return_error_event(self, client, engine, monkeypatch):
        """Each valid engine must return at least one non-error SSE event."""
        async def _fake_stream(model_id, request):
            yield {"type": "done", "model_id": model_id}

        monkeypatch.setattr("core.endpoints.installer._stream_gguf", _fake_stream)
        monkeypatch.setattr("core.endpoints.installer._stream_ollama", _fake_stream)
        resp = client.get(f"/installer/download?engine={engine}&model_id=test-model")
        assert resp.status_code == 200
        body = resp.text
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
