"""Tests for gated-model detection + dry_run preflight.

Covers:
- GET /installer/preflight returns access + plan
- engine=ollama short-circuits HF access check (returns ok directly)
- gated model without token → access.status="gated_no_access"
- gated model with token → access.status="ok" (token has access)
- not-found model → access.status="not_found"
- _stream_mlx emits SSE error with code=GATED_NO_TOKEN when applicable
"""

from __future__ import annotations

import asyncio
import json
import os
from unittest.mock import MagicMock, patch

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient


@pytest.fixture
def app_with_installer():
    from core.endpoints.installer import router
    app = FastAPI()
    app.include_router(router)
    return app


def _sse_events(text: str) -> list[dict]:
    events = []
    for chunk in text.split("\n\n"):
        line = next((l for l in chunk.splitlines() if l.startswith("data: ")), None)
        if line:
            try:
                events.append(json.loads(line[len("data: "):]))
            except json.JSONDecodeError:
                pass
    return events


# ──────────────────────────────────────────────────────────────────────────────
# GET /installer/preflight
# ──────────────────────────────────────────────────────────────────────────────


class TestPreflight:
    def test_preflight_ollama_short_circuits(self, app_with_installer):
        """For engine=ollama, preflight returns access=ok without any HF
        call (Ollama models live in the Ollama registry, not HF)."""
        with TestClient(app_with_installer) as client:
            r = client.get("/installer/preflight", params={
                "engine": "ollama",
                "model_id": "gemma3:4b",
            })
        assert r.status_code == 200
        data = r.json()
        assert data["engine"] == "ollama"
        assert data["access"]["status"] == "ok"
        assert data["plan"]["total_bytes"] == 0

    def test_preflight_invalid_engine_rejected(self, app_with_installer):
        with TestClient(app_with_installer) as client:
            r = client.get("/installer/preflight", params={
                "engine": "fastembedd",
                "model_id": "x",
            })
        assert r.status_code == 400

    def test_preflight_mlx_calls_hf_with_access_and_plan(self, app_with_installer):
        from huggingface_hub.file_download import DryRunFileInfo

        fake_info = MagicMock()
        fake_info.gated = False

        fake_plan = [
            DryRunFileInfo(
                commit_hash="abc",
                file_size=1_000_000,
                filename="model.safetensors",
                local_path="/tmp/x",
                is_cached=False,
                will_download=True,
            ),
            DryRunFileInfo(
                commit_hash="abc",
                file_size=500_000,
                filename="tokenizer.json",
                local_path="/tmp/y",
                is_cached=True,
                will_download=False,
            ),
        ]

        with patch("huggingface_hub.HfApi") as mock_api_cls, \
             patch("huggingface_hub.snapshot_download") as mock_snap:
            mock_api_cls.return_value.model_info.return_value = fake_info
            mock_snap.return_value = fake_plan

            with TestClient(app_with_installer) as client:
                r = client.get("/installer/preflight", params={
                    "engine": "mlx",
                    "model_id": "ns/test-model",
                })

        assert r.status_code == 200
        data = r.json()
        assert data["access"]["status"] == "ok"
        assert data["plan"]["total_bytes"] == 1_500_000
        assert data["plan"]["cached_bytes"] == 500_000
        assert data["plan"]["files_count"] == 2


# ──────────────────────────────────────────────────────────────────────────────
# Gated detection in /installer/download (SSE error code)
# ──────────────────────────────────────────────────────────────────────────────


class TestGatedSseError:
    def test_gated_no_token_emits_structured_error(self, app_with_installer, monkeypatch):
        """When the model is gated_no_access, _stream_mlx must NOT start
        the download; it emits a single SSE error with code=GATED_NO_TOKEN
        and the HF URL so the frontend can render an action link."""
        from core.endpoints import installer as installer_mod

        # Force HF_TOKEN absent so the gated path is hit
        monkeypatch.delenv("HF_TOKEN", raising=False)

        # Patch _check_model_access to return gated_no_access
        def fake_check(repo_id, token=None):
            return {"status": "gated_no_access", "url": f"https://huggingface.co/{repo_id}"}

        monkeypatch.setattr(installer_mod, "_check_model_access", fake_check)

        with TestClient(app_with_installer) as client:
            with client.stream(
                "GET",
                "/installer/download",
                params={"engine": "mlx", "model_id": "google/gemma-3-4b-it"},
            ) as r:
                body = "".join(chunk for chunk in r.iter_text())

        events = _sse_events(body)
        errs = [ev for ev in events if ev.get("type") == "error"]
        assert errs, f"No SSE error emitted: {events}"
        err = errs[0]
        assert err.get("code") == "GATED_NO_TOKEN"
        assert "huggingface.co/google/gemma-3-4b-it" in (err.get("url") or "")
        # B054: the guidance must NOT point at "Step 2 Advanced" (a dead end that
        # cannot download the catalog) and MUST surface the real escape routes:
        # paste the token in the download step, or switch the engine to Ollama.
        msg = err.get("message") or ""
        assert "Advanced" not in msg, msg
        assert "Ollama" in msg, msg

    def test_not_found_emits_structured_error(self, app_with_installer, monkeypatch):
        from core.endpoints import installer as installer_mod
        monkeypatch.delenv("HF_TOKEN", raising=False)

        def fake_check(repo_id, token=None):
            return {"status": "not_found"}

        monkeypatch.setattr(installer_mod, "_check_model_access", fake_check)

        with TestClient(app_with_installer) as client:
            with client.stream(
                "GET",
                "/installer/download",
                params={"engine": "mlx", "model_id": "ns/does-not-exist"},
            ) as r:
                body = "".join(chunk for chunk in r.iter_text())

        events = _sse_events(body)
        errs = [ev for ev in events if ev.get("type") == "error"]
        assert errs
        assert errs[0].get("code") == "NOT_FOUND"

    def test_ok_passes_through_to_stream(self, app_with_installer, monkeypatch, tmp_path):
        """When access is ok, _stream_mlx proceeds and emits progress
        events as usual (mocked snapshot_download to keep this fast)."""
        from core.endpoints import installer as installer_mod
        monkeypatch.delenv("HF_TOKEN", raising=False)
        monkeypatch.setattr(installer_mod, "_models_dir", lambda: tmp_path)

        def fake_check(repo_id, token=None):
            return {"status": "ok"}

        def fake_snap(repo_id, local_dir, tqdm_class=None, **kw):
            # Drop a small file so progress reports >0 bytes
            from pathlib import Path as _P
            (_P(local_dir) / "config.json").write_bytes(b"{}")

        monkeypatch.setattr(installer_mod, "_check_model_access", fake_check)
        monkeypatch.setattr("huggingface_hub.snapshot_download", fake_snap)

        with TestClient(app_with_installer) as client:
            with client.stream(
                "GET",
                "/installer/download",
                params={"engine": "mlx", "model_id": "ns/ok-model"},
            ) as r:
                body = "".join(chunk for chunk in r.iter_text())

        events = _sse_events(body)
        # No errors
        assert not any(ev.get("type") == "error" for ev in events)
        # Final done event
        assert any(ev.get("type") == "done" for ev in events)


# ──────────────────────────────────────────────────────────────────────────────
# B253 — HF token recovery from the Keychain when the live env lost it
# (sidecar PROCESS restart mid-download; page reload does NOT trigger this).
# ──────────────────────────────────────────────────────────────────────────────


class TestEnsureHfTokenInEnv:
    """Unit-level guards on the recovery helper (an async coroutine: the Keychain
    read runs off the event loop with a timeout, CRY-01). Each asserts a
    behaviour that a control mutation breaks (so these are not test-theatre)."""

    def test_env_present_returns_without_touching_keychain(self, monkeypatch):
        """Common case: the env already holds HF_TOKEN → return it and NEVER
        consult the Keychain. Mutation 'always read Keychain' → spy called → red."""
        from core.endpoints import installer as installer_mod
        monkeypatch.setenv("HF_TOKEN", "hf_env_value")
        calls = {"n": 0}

        def spy():
            calls["n"] += 1
            return "hf_should_not_be_used"

        monkeypatch.setattr(installer_mod, "_read_hf_token_from_keychain", spy)
        assert asyncio.run(installer_mod._ensure_hf_token_in_env()) == "hf_env_value"
        assert calls["n"] == 0, "Keychain must not be consulted when the env holds the token"

    def test_env_missing_recovers_from_keychain_and_reinjects(self, monkeypatch):
        """B253 core: env lost the token (restart) but it survives in the
        Keychain → recover it AND re-inject into os.environ so the env-based
        snapshot_download/preflight pick it up. Mutation 'drop the Keychain
        fallback' → returns None, env stays empty → red."""
        from core.endpoints import installer as installer_mod
        monkeypatch.delenv("HF_TOKEN", raising=False)
        monkeypatch.setattr(installer_mod, "_read_hf_token_from_keychain", lambda: "hf_recovered")
        token = asyncio.run(installer_mod._ensure_hf_token_in_env())
        assert token == "hf_recovered"
        assert os.environ.get("HF_TOKEN") == "hf_recovered", "must re-inject into env"

    def test_no_token_anywhere_returns_none(self, monkeypatch):
        """No token in env nor Keychain → None and env untouched (legitimate
        no-token case must still flow to gated_no_access, no regression)."""
        from core.endpoints import installer as installer_mod
        monkeypatch.delenv("HF_TOKEN", raising=False)
        monkeypatch.setattr(installer_mod, "_read_hf_token_from_keychain", lambda: None)
        assert asyncio.run(installer_mod._ensure_hf_token_in_env()) is None
        assert "HF_TOKEN" not in os.environ

    def test_keychain_read_timeout_is_swallowed(self, monkeypatch):
        """CRY-01 guard: a Keychain read that hangs (headless ACL prompt) must
        NOT hang the sidecar — the timeout fires and the wizard proceeds
        token-less. Mutation 'remove the wait_for/executor' → the call blocks
        on the read → the test hangs (no longer returns None promptly) → red.

        The blocking read is gated by an Event released in `finally` so the
        single-worker _dl_executor thread is freed immediately and does not
        poison the next test (the executor is shared at module scope)."""
        from core.endpoints import installer as installer_mod
        import threading
        monkeypatch.delenv("HF_TOKEN", raising=False)
        monkeypatch.setattr(installer_mod, "_HF_KEYCHAIN_READ_TIMEOUT", 0.1, raising=False)
        release = threading.Event()

        def hang():
            release.wait(timeout=10)  # blocks until the test releases it
            return "hf_never"

        monkeypatch.setattr(installer_mod, "_read_hf_token_from_keychain", hang)
        try:
            token = asyncio.run(installer_mod._ensure_hf_token_in_env())
            assert token is None
            assert "HF_TOKEN" not in os.environ
        finally:
            release.set()  # free the worker thread so it cannot poison later tests


class TestB253MidFlowRecovery:
    def test_gated_download_recovers_token_after_sidecar_restart(
        self, app_with_installer, monkeypatch, tmp_path
    ):
        """End-to-end at the download path: env has NO HF_TOKEN (sidecar
        restarted mid-flow) but the token is still in the Keychain. The gated
        preflight must recover it so the retry authenticates instead of
        dead-ending on GATED_NO_TOKEN. Mutation 'drop the Keychain fallback' →
        token is None → gated_no_access → GATED_NO_TOKEN → red."""
        from core.endpoints import installer as installer_mod
        monkeypatch.delenv("HF_TOKEN", raising=False)
        monkeypatch.setattr(installer_mod, "_models_dir", lambda: tmp_path)
        # token survives in the Keychain (step3 best-effort persist)
        monkeypatch.setattr(installer_mod, "_read_hf_token_from_keychain", lambda: "hf_kc_token")

        # capture the token that actually reaches the access check, and grant
        # access ONLY if a (non-None) token reaches it
        seen = {"token": "SENTINEL"}

        def fake_check(repo_id, token=None):
            seen["token"] = token
            if token:
                return {"status": "ok"}
            return {"status": "gated_no_access", "url": f"https://huggingface.co/{repo_id}"}

        def fake_snap(repo_id, local_dir, tqdm_class=None, **kw):
            from pathlib import Path as _P
            (_P(local_dir) / "config.json").write_bytes(b"{}")

        monkeypatch.setattr(installer_mod, "_check_model_access", fake_check)
        monkeypatch.setattr("huggingface_hub.snapshot_download", fake_snap)

        with TestClient(app_with_installer) as client:
            with client.stream(
                "GET",
                "/installer/download",
                params={"engine": "mlx", "model_id": "google/gemma-3-4b-it"},
            ) as r:
                body = "".join(chunk for chunk in r.iter_text())

        events = _sse_events(body)
        assert not any(ev.get("code") == "GATED_NO_TOKEN" for ev in events), (
            f"token should have been recovered from Keychain: {events}"
        )
        assert any(ev.get("type") == "done" for ev in events), events
        # the recovered token actually reached the gated access check (non-None)
        assert seen["token"] == "hf_kc_token", f"check got {seen['token']!r}"
        # and was re-injected so snapshot_download (env-based) sees it
        assert os.environ.get("HF_TOKEN") == "hf_kc_token"

    def test_gguf_gated_recovers_token_after_sidecar_restart(
        self, app_with_installer, monkeypatch, tmp_path
    ):
        """Same recovery must hold for engine=gguf (the other HF-hosted engine
        _preflight_hf_access covers), not only mlx."""
        from core.endpoints import installer as installer_mod
        monkeypatch.delenv("HF_TOKEN", raising=False)
        monkeypatch.setattr(installer_mod, "_models_dir", lambda: tmp_path)
        monkeypatch.setattr(installer_mod, "_read_hf_token_from_keychain", lambda: "hf_kc_gguf")
        seen = {"token": "SENTINEL"}

        def fake_check(repo_id, token=None):
            seen["token"] = token
            return {"status": "ok"} if token else {
                "status": "gated_no_access", "url": f"https://huggingface.co/{repo_id}"}

        monkeypatch.setattr(installer_mod, "_check_model_access", fake_check)
        # short-circuit the gguf streamer after the preflight has run
        async def fake_stream_gguf(model_id, request):
            yield {"type": "done", "model_id": model_id}
        monkeypatch.setattr(installer_mod, "_stream_gguf", fake_stream_gguf)
        monkeypatch.setattr(installer_mod, "_sha256_check", lambda *a, **k: _noop_coro())

        with TestClient(app_with_installer) as client:
            with client.stream(
                "GET",
                "/installer/download",
                params={"engine": "gguf", "model_id": "ns/gated-gguf"},
            ) as r:
                body = "".join(chunk for chunk in r.iter_text())

        events = _sse_events(body)
        assert not any(ev.get("code") == "GATED_NO_TOKEN" for ev in events), events
        assert seen["token"] == "hf_kc_gguf", f"check got {seen['token']!r}"

    def test_no_keychain_token_still_dead_ends_gated(
        self, app_with_installer, monkeypatch, tmp_path
    ):
        """No-regression: with neither env nor Keychain token, a gated model
        still surfaces GATED_NO_TOKEN (we did not paper over the legitimate
        no-token case)."""
        from core.endpoints import installer as installer_mod
        monkeypatch.delenv("HF_TOKEN", raising=False)
        monkeypatch.setattr(installer_mod, "_models_dir", lambda: tmp_path)
        monkeypatch.setattr(installer_mod, "_read_hf_token_from_keychain", lambda: None)

        def fake_check(repo_id, token=None):
            if token:
                return {"status": "ok"}
            return {"status": "gated_no_access", "url": f"https://huggingface.co/{repo_id}"}

        monkeypatch.setattr(installer_mod, "_check_model_access", fake_check)

        with TestClient(app_with_installer) as client:
            with client.stream(
                "GET",
                "/installer/download",
                params={"engine": "mlx", "model_id": "google/gemma-3-4b-it"},
            ) as r:
                body = "".join(chunk for chunk in r.iter_text())

        events = _sse_events(body)
        assert any(ev.get("code") == "GATED_NO_TOKEN" for ev in events), events

    def test_get_preflight_recovers_token_after_sidecar_restart(
        self, app_with_installer, monkeypatch
    ):
        """The GET /installer/preflight endpoint (consulted by the wizard before
        the download) must also recover the token from the Keychain so it reports
        access=ok instead of gated_no_access after a mid-flow restart."""
        from core.endpoints import installer as installer_mod
        monkeypatch.delenv("HF_TOKEN", raising=False)
        monkeypatch.setattr(installer_mod, "_read_hf_token_from_keychain", lambda: "hf_kc_pf")
        seen = {"token": "SENTINEL"}

        def fake_check(repo_id, token=None):
            seen["token"] = token
            return {"status": "ok"} if token else {
                "status": "gated_no_access", "url": f"https://huggingface.co/{repo_id}"}

        monkeypatch.setattr(installer_mod, "_check_model_access", fake_check)
        monkeypatch.setattr(installer_mod, "_dry_run_plan", lambda repo_id, token=None: {
            "total_bytes": 0, "cached_bytes": 0, "files_count": 0})

        with TestClient(app_with_installer) as client:
            r = client.get("/installer/preflight", params={
                "engine": "mlx", "model_id": "ns/gated"})

        assert r.status_code == 200
        assert r.json()["access"]["status"] == "ok"
        assert seen["token"] == "hf_kc_pf"
        assert os.environ.get("HF_TOKEN") == "hf_kc_pf"


# ──────────────────────────────────────────────────────────────────────────────
# B257 — gguf preflight must probe the HF repo_id, not the raw .gguf URL
# ──────────────────────────────────────────────────────────────────────────────


class TestB257RepoIdHelpers:
    @pytest.mark.parametrize("url,expected", [
        ("https://huggingface.co/Org/Model-GGUF/resolve/main/m.Q4_K_M.gguf", "Org/Model-GGUF"),
        ("https://huggingface.co/Org/Model/blob/main/m.gguf", "Org/Model"),
        ("https://hf.co/Org/Model/resolve/main/m.gguf", "Org/Model"),
        ("https://example.com/Org/Model/resolve/main/m.gguf", None),   # non-HF host
        ("https://huggingface.co/onlyorg", None),                       # too short
    ])
    def test_hf_repo_id_from_url(self, url, expected):
        from core.endpoints.installer import _hf_repo_id_from_url
        assert _hf_repo_id_from_url(url) == expected

    def test_preflight_repo_id_passthrough_for_mlx(self):
        """mlx model_ids are already repo_ids (no URL scheme) → returned as-is."""
        from core.endpoints.installer import _preflight_repo_id
        assert _preflight_repo_id("ns/test-model") == "ns/test-model"

    def test_preflight_repo_id_derives_for_gguf_url(self):
        from core.endpoints.installer import _preflight_repo_id
        assert _preflight_repo_id(
            "https://huggingface.co/Org/Model/resolve/main/m.gguf") == "Org/Model"


class TestB257GgufPreflight:
    """B257: gguf preflight must derive the HF repo_id from the .gguf URL before
    calling _check_model_access/_dry_run_plan (which expect org/model). Passing
    the raw URL degraded the gated/size probe to a spurious network_error."""

    def test_preflight_gguf_derives_repo_id_for_hf_url(self, app_with_installer, monkeypatch):
        from core.endpoints import installer as installer_mod
        monkeypatch.delenv("HF_TOKEN", raising=False)
        seen = {"repo_id": "SENTINEL"}

        def fake_check(repo_id, token=None):
            seen["repo_id"] = repo_id
            return {"status": "ok"}

        monkeypatch.setattr(installer_mod, "_check_model_access", fake_check)
        monkeypatch.setattr(installer_mod, "_dry_run_plan", lambda repo_id, token=None: {
            "total_bytes": 0, "cached_bytes": 0, "files_count": 0})

        url = "https://huggingface.co/TheOrg/Some-Model-GGUF/resolve/main/model.Q4_K_M.gguf"
        with TestClient(app_with_installer) as client:
            r = client.get("/installer/preflight", params={"engine": "gguf", "model_id": url})

        assert r.status_code == 200
        # Mutation 'pass model_id instead of repo_id' → seen would be the full URL → red
        assert seen["repo_id"] == "TheOrg/Some-Model-GGUF"

    def test_preflight_gguf_non_hf_url_skips_hf_probe(self, app_with_installer, monkeypatch):
        from core.endpoints import installer as installer_mod
        monkeypatch.delenv("HF_TOKEN", raising=False)
        called = {"n": 0}

        def fake_check(repo_id, token=None):
            called["n"] += 1
            return {"status": "ok"}

        monkeypatch.setattr(installer_mod, "_check_model_access", fake_check)

        url = "https://example.com/models/model.Q4_K_M.gguf"
        with TestClient(app_with_installer) as client:
            r = client.get("/installer/preflight", params={"engine": "gguf", "model_id": url})

        assert r.status_code == 200
        data = r.json()
        assert data["access"]["status"] == "ok"
        assert data["plan"]["total_bytes"] == 0
        assert called["n"] == 0, "a non-HF gguf URL must not reach the HF probe"


def _noop_coro():
    async def _c():
        return None
    return _c()
