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

import json
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
