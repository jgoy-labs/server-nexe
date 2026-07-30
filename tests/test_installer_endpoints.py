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
    # WS1-01: /installer/finalize is loopback-guarded; the default TestClient
    # presents as "testclient" (non-loopback) and would be 403'd.
    return TestClient(app, raise_server_exceptions=True, client=("127.0.0.1", 50000))


@pytest.fixture()
def remote_client(app):
    """A client that presents a non-loopback peer address (LAN attacker)."""
    return TestClient(app, raise_server_exceptions=True, client=("192.168.1.66", 50000))


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
    def test_get_finalize_refuses_non_loopback_client(self, remote_client, isolated_data_dir):
        """WS1-01: the primary key is never served across the network, even
        if the operator opted into a public bind."""
        resp = remote_client.get("/installer/finalize")
        assert resp.status_code == 403
        assert "api_key" not in resp.text

    def test_post_finalize_refuses_non_loopback_client(self, remote_client, isolated_data_dir):
        resp = remote_client.post(
            "/installer/finalize",
            json={"engine": "ollama", "model_id": "qwen3.5:4b", "lang": "ca"},
        )
        assert resp.status_code == 403
        assert "api_key" not in resp.text

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

    def test_post_returns_404_when_onboarding_already_completed(
        self, client, isolated_data_dir
    ):
        """INST-001: once onboarding is complete, the unauthenticated, repeatable
        POST must not keep re-serving NEXE_PRIMARY_API_KEY (symmetric with GET).
        The guard fires before model resolution, so the body need only be valid."""
        from core.onboarding_state import OnboardingState

        OnboardingState.save(
            engine="mlx",
            model_id="mlx-community/test-model",
            model_path=str(isolated_data_dir / "test-model"),
            hf_token=None,
        )
        resp = client.post(
            "/installer/finalize",
            json={"engine": "mlx", "model_id": "mlx-community/test-model"},
        )
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

    def test_local_rejects_nonexistent_folder(self):
        """engine='local' with a folder that does not exist → ValueError (→400)."""
        from core.endpoints.installer import _resolve_model_path

        with pytest.raises(ValueError, match="local models folder not found"):
            _resolve_model_path("local", "/no/such/models/folder/xyz")

    def test_local_accepts_existing_dir(self, tmp_path):
        """engine='local' with an existing dir returns its resolved path."""
        from core.endpoints.installer import _resolve_model_path

        folder = tmp_path / "my-models"
        folder.mkdir()
        resolved = _resolve_model_path("local", str(folder))
        assert resolved == str(folder.resolve())

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

        async def _no_preflight(engine, model_id):
            return None

        monkeypatch.setattr("core.endpoints.installer._stream_gguf", _fake_stream)
        monkeypatch.setattr("core.endpoints.installer._stream_ollama", _fake_stream)
        # El preflight HF real fa XARXA: amb connexió viva, "test-model" → 404
        # → error event i el test flaquejava segons l'estat de HF. El contracte
        # d'aquest test és el dispatch per engine, no l'accés a HF.
        monkeypatch.setattr("core.endpoints.installer._preflight_hf_access", _no_preflight)
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


# ---------------------------------------------------------------------------
# POST /installer/hf-token  (B054: hand the HF token to the live sidecar env
# BEFORE a gated-model download in the same onboarding run)
# ---------------------------------------------------------------------------

class TestSetHfToken:
    """The endpoint must load the token into os.environ['HF_TOKEN'] (where the
    gated preflight + snapshot_download read it from) and best-effort persist
    it to the Keychain — without ever touching the real Keychain in tests."""

    @pytest.fixture()
    def no_keychain(self, monkeypatch):
        """Stub the Keychain writer so tests never prompt/persist for real;
        capture the token it was handed so we can assert on it."""
        import core.endpoints.installer as inst
        seen = {}

        def fake_store(tok):
            seen["token"] = tok
            return True

        monkeypatch.setattr(inst, "_store_hf_token_in_keychain", fake_store)
        monkeypatch.delenv("HF_TOKEN", raising=False)
        yield seen
        # The endpoint writes os.environ directly (outside monkeypatch's
        # bookkeeping); scrub it so it never leaks into sibling tests.
        os.environ.pop("HF_TOKEN", None)

    def test_loads_token_into_env(self, client, no_keychain):
        resp = client.post("/installer/hf-token", json={"token": "hf_secret123"})
        assert resp.status_code == 200
        assert resp.json()["ok"] is True
        # The whole point of the fix: the live env now carries the token, so a
        # gated download in this same run authenticates. Mutation: drop the
        # `os.environ["HF_TOKEN"] = token` line and this assertion goes red.
        assert os.environ.get("HF_TOKEN") == "hf_secret123"

    def test_persists_to_keychain(self, client, no_keychain):
        resp = client.post("/installer/hf-token", json={"token": "hf_abc"})
        assert resp.json()["persisted"] is True
        # Mutation: remove the _store_hf_token_in_keychain call → not captured.
        assert no_keychain["token"] == "hf_abc"

    def test_persisted_false_propagates_when_keychain_declines(self, client, monkeypatch):
        """`persisted` must reflect the REAL return of the Keychain write, not be
        hardcoded True. Pairs with test_persists_to_keychain (True case) so a
        mutation that ignores the bool (persisted = True) is caught here."""
        import core.endpoints.installer as inst
        monkeypatch.delenv("HF_TOKEN", raising=False)
        monkeypatch.setattr(inst, "_store_hf_token_in_keychain", lambda _t: False)
        try:
            resp = client.post("/installer/hf-token", json={"token": "hf_x"})
            assert resp.status_code == 200
            assert resp.json()["persisted"] is False
            assert os.environ.get("HF_TOKEN") == "hf_x"  # env set regardless
        finally:
            os.environ.pop("HF_TOKEN", None)

    def test_trims_whitespace_before_loading(self, client, no_keychain):
        resp = client.post("/installer/hf-token", json={"token": "  hf_xyz  "})
        assert resp.status_code == 200
        assert os.environ.get("HF_TOKEN") == "hf_xyz"

    def test_whitespace_only_rejected_and_env_untouched(self, client, no_keychain):
        resp = client.post("/installer/hf-token", json={"token": "   "})
        assert resp.status_code == 400
        # The guard runs BEFORE the env write, so a blank token must not clobber
        # HF_TOKEN (mutation: move the write above the guard → this goes red).
        assert os.environ.get("HF_TOKEN") is None

    def test_keychain_failure_does_not_break_env_load(self, client, monkeypatch):
        """A04/CRY-01: the Keychain write runs off-thread with a timeout and is
        best-effort. If it raises (or would hang), the endpoint still returns
        200 with the env set — the download path depends on the env, not the
        Keychain. Mutation: drop the try/except and this goes 500."""
        import core.endpoints.installer as inst
        monkeypatch.delenv("HF_TOKEN", raising=False)

        def boom(_tok):
            raise RuntimeError("keyring exploded")

        monkeypatch.setattr(inst, "_store_hf_token_in_keychain", boom)
        try:
            resp = client.post("/installer/hf-token", json={"token": "hf_resilient"})
            assert resp.status_code == 200
            assert resp.json()["persisted"] is False
            assert os.environ.get("HF_TOKEN") == "hf_resilient"
        finally:
            os.environ.pop("HF_TOKEN", None)

    def test_missing_token_field_is_422(self, client, no_keychain):
        resp = client.post("/installer/hf-token", json={})
        assert resp.status_code == 422

    def test_empty_token_field_is_422(self, client, no_keychain):
        # Field(min_length=1) rejects "" at the validation layer.
        resp = client.post("/installer/hf-token", json={"token": ""})
        assert resp.status_code == 422
