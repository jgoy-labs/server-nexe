"""B255: _stream_gguf must authenticate gated GGUF downloads from the HF Hub
with an ``Authorization: Bearer <HF_TOKEN>`` header — but ONLY for HF hosts, so
the token is never handed to an arbitrary catalog host.

Each test asserts a behaviour a control mutation breaks:
- dropping the ``_is_hf_hub_url`` guard → the token leaks to a non-HF host (red).
- dropping the header entirely → a gated HF GGUF can't authenticate (red).
"""
from __future__ import annotations

import asyncio

import pytest

from core.endpoints import installer as installer_mod


# ── _is_hf_hub_url: only HF hosts, anchored so look-alikes don't match ─────────


@pytest.mark.parametrize(
    ("url", "expected"),
    [
        ("https://huggingface.co/TheBloke/x/resolve/main/m.gguf", True),
        ("https://hf.co/x/m.gguf", True),
        ("https://cdn-lfs.huggingface.co/x/m.gguf", True),
        ("https://example.com/m.gguf", False),
        ("https://huggingface.co.evil.com/m.gguf", False),   # suffix attack
        ("https://evilhuggingface.co/m.gguf", False),        # prefix attack
        ("https://myhuggingface.co/m.gguf", False),
        ("not a url", False),
        ("", False),
    ],
)
def test_is_hf_hub_url(url, expected):
    assert installer_mod._is_hf_hub_url(url) is expected


# ── _stream_gguf: header attached only for HF + token present ──────────────────


class _FakeResp:
    def __init__(self):
        self.headers = {"content-length": "2"}

    def raise_for_status(self):
        pass

    async def aiter_bytes(self, chunk_size=0):
        yield b"gg"

    async def __aenter__(self):
        return self

    async def __aexit__(self, *a):
        return False


class _FakeClient:
    """Captures the headers passed to .stream() so a test can inspect them."""

    captured: dict = {}

    def __init__(self, **kw):
        pass

    async def __aenter__(self):
        return self

    async def __aexit__(self, *a):
        return False

    def stream(self, method, url, headers=None):
        _FakeClient.captured = {"method": method, "url": url, "headers": dict(headers or {})}
        return _FakeResp()


class _FakeReq:
    async def is_disconnected(self):
        return False


def _run_stream(model_id, monkeypatch, tmp_path):
    monkeypatch.setattr(installer_mod, "_models_dir", lambda: tmp_path)
    monkeypatch.setattr("httpx.AsyncClient", _FakeClient)
    _FakeClient.captured = {}

    async def _collect():
        return [ev async for ev in installer_mod._stream_gguf(model_id, _FakeReq())]

    asyncio.run(_collect())
    return _FakeClient.captured["headers"]


def test_gguf_attaches_bearer_for_hf_url_with_token(monkeypatch, tmp_path):
    monkeypatch.setattr(installer_mod, "_read_hf_token_from_keychain", lambda: None)
    monkeypatch.setenv("HF_TOKEN", "hf_gtok")
    headers = _run_stream(
        "https://huggingface.co/TheBloke/x/resolve/main/m.gguf", monkeypatch, tmp_path
    )
    assert headers.get("Authorization") == "Bearer hf_gtok"


def test_gguf_no_bearer_for_non_hf_url(monkeypatch, tmp_path):
    """A token must NEVER be sent to a non-HF catalog host (leak guard)."""
    monkeypatch.setattr(installer_mod, "_read_hf_token_from_keychain", lambda: None)
    monkeypatch.setenv("HF_TOKEN", "hf_gtok")  # token IS available
    headers = _run_stream("https://example.com/models/m.gguf", monkeypatch, tmp_path)
    assert "Authorization" not in headers, "token leaked to a non-HF host"


def test_gguf_no_bearer_when_no_token(monkeypatch, tmp_path):
    """HF URL but no token anywhere → no header (public GGUF still downloads)."""
    monkeypatch.delenv("HF_TOKEN", raising=False)
    monkeypatch.setattr(installer_mod, "_read_hf_token_from_keychain", lambda: None)
    headers = _run_stream(
        "https://huggingface.co/x/resolve/main/m.gguf", monkeypatch, tmp_path
    )
    assert "Authorization" not in headers


def test_gguf_recovers_token_from_keychain_for_hf_url(monkeypatch, tmp_path):
    """B253 synergy: env lost the token (restart) but it's in the Keychain → the
    HF GGUF download still authenticates."""
    monkeypatch.delenv("HF_TOKEN", raising=False)
    monkeypatch.setattr(installer_mod, "_read_hf_token_from_keychain", lambda: "hf_kc")
    headers = _run_stream(
        "https://huggingface.co/x/resolve/main/m.gguf", monkeypatch, tmp_path
    )
    assert headers.get("Authorization") == "Bearer hf_kc"
