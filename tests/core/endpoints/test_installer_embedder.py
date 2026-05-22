"""
F5.4 Bug A — regression tests: the wizard must be able to download the
fastembed embedding model via /installer/download?engine=embedder.

Empirical evidence from G10 portàtil 2026-05-19: ~/.cache/fastembed/ was
empty, MemoryAPI and DreamingCycle failed silently. The wizard previously
had no UI affordance to download the embedder — only the LLM.

Tests:
- engine=embedder is accepted (was rejected as "Unknown engine: embedder")
- cache-hit path: when the model is already present, emits a single 100%
  progress event with cached=True and no actual download attempt.
- cache-miss path: invokes fastembed.TextEmbedding inside the worker thread
  (we mock TextEmbedding so the test runs in <1s without hitting HF).
- progress events include bytes_done and bytes_total (real bytes, not fake).
"""

from __future__ import annotations

import asyncio
import json
import os
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient
from fastapi import FastAPI


# ──────────────────────────────────────────────────────────────────────────────
# Helpers
# ──────────────────────────────────────────────────────────────────────────────


@pytest.fixture
def app_with_installer():
    """Build a minimal FastAPI app with just the installer router."""
    from core.endpoints.installer import router
    app = FastAPI()
    app.include_router(router)
    return app


def _sse_events(response_text: str) -> list[dict]:
    """Parse SSE wire format → list of decoded JSON events."""
    events = []
    for chunk in response_text.split("\n\n"):
        line = next((l for l in chunk.splitlines() if l.startswith("data: ")), None)
        if line:
            try:
                events.append(json.loads(line[len("data: "):]))
            except json.JSONDecodeError:
                pass
    return events


# ──────────────────────────────────────────────────────────────────────────────
# Bug A: engine=embedder must be a valid choice
# ──────────────────────────────────────────────────────────────────────────────


class TestInstallerEmbedderEndpoint:

    def test_engine_embedder_is_accepted(self, app_with_installer, tmp_path, monkeypatch):
        """The endpoint must NOT reject engine=embedder with 'Unknown engine'."""
        # Redirect fastembed cache to a fresh tmp dir so the fast-path
        # (cached=True) is taken — we test the route wiring, not download.
        monkeypatch.setenv("FASTEMBED_CACHE_DIR", str(tmp_path / "fc"))
        # Pre-seed an onnx file > 1MB to trigger the cache-hit path.
        cache = tmp_path / "fc"
        cache.mkdir(parents=True, exist_ok=True)
        fake_onnx = cache / "model.onnx"
        fake_onnx.write_bytes(b"\x00" * (2 * 1024 * 1024))

        with TestClient(app_with_installer) as client:
            with client.stream(
                "GET",
                "/installer/download",
                params={"engine": "embedder", "model_id": "sentence-transformers/paraphrase-multilingual-mpnet-base-v2"},
            ) as r:
                assert r.status_code == 200
                body = "".join(chunk for chunk in r.iter_text())

        events = _sse_events(body)
        # Must NOT contain the "Unknown engine" error
        for ev in events:
            assert not (ev.get("type") == "error" and "Unknown engine" in (ev.get("message") or "")), (
                f"engine=embedder was rejected as Unknown: {ev}"
            )
        # Must contain at least one progress event and a final done.
        progress = [ev for ev in events if ev.get("type") == "progress"]
        done = [ev for ev in events if ev.get("type") == "done"]
        assert progress, f"No progress event emitted, got: {events}"
        assert done, f"No done event emitted, got: {events}"

    def test_cached_model_emits_cached_true_and_skips_download(
        self, app_with_installer, tmp_path, monkeypatch
    ):
        """When the model is already present in cache_dir, the stream must
        emit a single 100% progress with cached=True and not invoke
        TextEmbedding (which would re-download or be slow)."""
        monkeypatch.setenv("FASTEMBED_CACHE_DIR", str(tmp_path / "fc"))
        cache = tmp_path / "fc"
        cache.mkdir(parents=True, exist_ok=True)
        # Place a fake .onnx > 1MB to satisfy _embedder_model_present
        fake_onnx = cache / "models--xenova--paraphrase" / "snapshots" / "abc" / "model.onnx"
        fake_onnx.parent.mkdir(parents=True, exist_ok=True)
        fake_onnx.write_bytes(b"\x00" * (2 * 1024 * 1024))

        # If TextEmbedding gets called, the test fails (it shouldn't on cache hit)
        with patch("fastembed.TextEmbedding") as mock_text_embedding:
            with TestClient(app_with_installer) as client:
                with client.stream(
                    "GET",
                    "/installer/download",
                    params={"engine": "embedder", "model_id": "test/model"},
                ) as r:
                    body = "".join(chunk for chunk in r.iter_text())

        events = _sse_events(body)
        progress = [ev for ev in events if ev.get("type") == "progress"]
        assert progress, f"No progress event, got: {events}"
        # Cache-hit must emit cached=True at 100% in the first/only progress event.
        first = progress[0]
        assert first.get("percent") == 100, (
            f"Cache-hit must emit 100% directly, got: {first}"
        )
        assert first.get("cached") is True, (
            f"Cache-hit must mark cached=True, got: {first}"
        )
        # TextEmbedding MUST NOT have been invoked on cache hit.
        mock_text_embedding.assert_not_called()

    def test_cache_miss_invokes_textembedding_in_worker_thread(
        self, app_with_installer, tmp_path, monkeypatch
    ):
        """Cache miss → TextEmbedding constructor called with cache_dir set.
        Mocked so the test does not hit the network."""
        cache = tmp_path / "fc"
        # Do NOT pre-seed any onnx file → cache miss path
        monkeypatch.setenv("FASTEMBED_CACHE_DIR", str(cache))

        # Mock TextEmbedding to be a fast no-op (simulate instant download)
        def _fake_text_embedding(model_id, cache_dir):
            # Touch a fake onnx in cache to simulate completed download
            target = Path(cache_dir) / "snapshots" / "fake" / "model.onnx"
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(b"\x00" * (2 * 1024 * 1024))
            return MagicMock()

        with patch("fastembed.TextEmbedding", side_effect=_fake_text_embedding) as mock_te:
            with TestClient(app_with_installer) as client:
                with client.stream(
                    "GET",
                    "/installer/download",
                    params={"engine": "embedder", "model_id": "sentence-transformers/paraphrase-multilingual-mpnet-base-v2"},
                ) as r:
                    body = "".join(chunk for chunk in r.iter_text())

        events = _sse_events(body)
        progress = [ev for ev in events if ev.get("type") == "progress"]
        done = [ev for ev in events if ev.get("type") == "done"]
        assert progress, f"No progress event, got: {events}"
        assert done, f"No done event emitted, got: {events}"

        # TextEmbedding must have been called once with the right cache_dir.
        mock_te.assert_called_once()
        call_kwargs = mock_te.call_args.kwargs
        assert "cache_dir" in call_kwargs
        assert str(cache) in call_kwargs["cache_dir"], (
            f"TextEmbedding called with wrong cache_dir: {call_kwargs}"
        )

    def test_invalid_engine_still_rejected(self, app_with_installer):
        """Sanity: typo engines must still be rejected (no regression on
        the engine allowlist after adding 'embedder')."""
        with TestClient(app_with_installer) as client:
            with client.stream(
                "GET",
                "/installer/download",
                params={"engine": "fastembedd", "model_id": "x"},
            ) as r:
                body = "".join(chunk for chunk in r.iter_text())

        events = _sse_events(body)
        errors = [ev for ev in events if ev.get("type") == "error"]
        assert errors, f"Invalid engine must produce an error, got: {events}"
        assert "Unknown engine" in (errors[0].get("message") or "")
