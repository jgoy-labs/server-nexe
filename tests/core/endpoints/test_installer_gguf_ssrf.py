"""NEXE-SRV-WS2-01: _stream_gguf is an unauthenticated, CSRF-exempt, cross-origin
reachable endpoint. Before the fix it fetched ``model_id`` verbatim with
``follow_redirects=True`` and ``timeout=None`` and no size cap — a blind SSRF
(fetch to http://127.0.0.1:11434/api/tags) + disk-fill + arbitrary write into
models_dir.

The fix restricts the fetch to an ``https://`` URL on the HuggingFace Hub
allow-list, caps the streamed size, uses a finite read timeout, and rejects
redirects that leave the allow-list.

Each test asserts a behaviour a control mutation breaks:
- dropping the scheme/host guard → a non-HF or http:// target reaches the fetch.
- dropping the size cap → an unbounded body is written to disk.
- dropping the redirect validation → a 30x to a non-HF host is followed (SSRF).
"""
from __future__ import annotations

import asyncio
from urllib.parse import urljoin

import pytest

from core.endpoints import installer as installer_mod


class _FakeReq:
    async def is_disconnected(self):
        return False


class _FakeURL:
    def __init__(self, url: str):
        self._u = url

    def join(self, other: str) -> str:
        return urljoin(self._u, other)


class _Resp:
    def __init__(
        self,
        *,
        is_redirect: bool = False,
        location: str | None = None,
        content_length: int | None = None,
        body: bytes = b"",
        url: str = "https://huggingface.co/x/resolve/main/m.gguf",
    ):
        self.is_redirect = is_redirect
        self.headers: dict = {}
        if location is not None:
            self.headers["location"] = location
        if content_length is not None:
            self.headers["content-length"] = str(content_length)
        self._body = body
        self.url = _FakeURL(url)

    def raise_for_status(self):
        pass

    async def aiter_bytes(self, chunk_size: int = 0):
        step = chunk_size or len(self._body) or 1
        for i in range(0, len(self._body), step):
            yield self._body[i:i + step]

    async def __aenter__(self):
        return self

    async def __aexit__(self, *a):
        return False


class _ScriptedClient:
    """Returns pre-scripted responses in order and records each .stream() call."""

    script: list = []
    calls: list = []

    def __init__(self, **kw):
        pass

    async def __aenter__(self):
        return self

    async def __aexit__(self, *a):
        return False

    def stream(self, method, url, headers=None):
        _ScriptedClient.calls.append({"url": url, "headers": dict(headers or {})})
        return _ScriptedClient.script.pop(0)


def _install(monkeypatch, tmp_path, script):
    monkeypatch.setattr(installer_mod, "_models_dir", lambda: tmp_path)
    monkeypatch.setattr(installer_mod, "_read_hf_token_from_keychain", lambda: None)
    monkeypatch.delenv("HF_TOKEN", raising=False)
    monkeypatch.setattr("httpx.AsyncClient", _ScriptedClient)
    _ScriptedClient.script = list(script)
    _ScriptedClient.calls = []


def _run(model_id):
    async def _collect():
        return [ev async for ev in installer_mod._stream_gguf(model_id, _FakeReq())]

    return asyncio.run(_collect())


# ── _is_allowed_gguf_url: https + HF host only ────────────────────────────────


@pytest.mark.parametrize(
    ("url", "expected"),
    [
        ("https://huggingface.co/TheBloke/x/resolve/main/m.gguf", True),
        ("https://hf.co/x/m.gguf", True),
        ("https://cdn-lfs.huggingface.co/x/m.gguf", True),
        ("http://huggingface.co/x/m.gguf", False),          # http rejected
        ("https://example.com/m.gguf", False),              # non-HF rejected
        ("http://127.0.0.1:11434/api/tags", False),         # SSRF target rejected
        ("https://huggingface.co.evil.com/m.gguf", False),  # suffix attack
        ("ftp://huggingface.co/m.gguf", False),
        ("not a url", False),
        ("", False),
    ],
)
def test_is_allowed_gguf_url(url, expected):
    assert installer_mod._is_allowed_gguf_url(url) is expected


# ── positive: HF https URL downloads and writes bytes ─────────────────────────


def test_hf_https_url_downloads(monkeypatch, tmp_path):
    _install(monkeypatch, tmp_path, [_Resp(content_length=4, body=b"gguf")])
    events = _run("https://huggingface.co/org/model/resolve/main/m.gguf")
    assert (tmp_path / "m.gguf").read_bytes() == b"gguf"
    assert any(ev.get("type") == "progress" for ev in events)
    assert len(_ScriptedClient.calls) == 1


# ── negative: http scheme rejected before any fetch ───────────────────────────


def test_http_scheme_rejected(monkeypatch, tmp_path):
    _install(monkeypatch, tmp_path, [_Resp(body=b"pwn")])
    events = _run("http://huggingface.co/org/model/resolve/main/m.gguf")
    assert events[0]["type"] == "error"
    assert events[0]["code"] == "INVALID_MODEL_URL"
    assert _ScriptedClient.calls == [], "no fetch for an http:// URL"
    assert not list(tmp_path.iterdir())


# ── negative: internal SSRF target rejected before any fetch ──────────────────


def test_ssrf_internal_target_rejected(monkeypatch, tmp_path):
    _install(monkeypatch, tmp_path, [_Resp(body=b"ATTACKER_PAYLOAD")])
    events = _run("http://127.0.0.1:11434/api/tags")
    assert events[0]["type"] == "error"
    assert events[0]["code"] == "INVALID_MODEL_URL"
    assert _ScriptedClient.calls == [], "internal host must never be fetched"
    assert not list(tmp_path.iterdir()), "no attacker bytes written"


# ── negative: content-length over the cap rejected before streaming ───────────


def test_content_length_over_cap_rejected(monkeypatch, tmp_path):
    monkeypatch.setattr(installer_mod, "_GGUF_MAX_BYTES", 10)
    _install(monkeypatch, tmp_path, [_Resp(content_length=1000, body=b"x" * 1000)])
    events = _run("https://huggingface.co/org/model/resolve/main/m.gguf")
    assert events[0]["type"] == "error"
    assert events[0]["code"] == "MODEL_TOO_LARGE"
    assert not (tmp_path / "m.gguf").exists()


# ── negative: unbounded body (no content-length) capped mid-stream ────────────


def test_streamed_body_over_cap_aborted(monkeypatch, tmp_path):
    monkeypatch.setattr(installer_mod, "_GGUF_MAX_BYTES", 10)
    _install(monkeypatch, tmp_path, [_Resp(body=b"x" * 1000)])  # no content-length
    events = _run("https://huggingface.co/org/model/resolve/main/m.gguf")
    assert any(ev.get("code") == "MODEL_TOO_LARGE" for ev in events)
    assert not (tmp_path / "m.gguf").exists(), "partial disk-fill must be cleaned up"


# ── negative: redirect off the allow-list rejected ────────────────────────────


def test_redirect_off_allowlist_rejected(monkeypatch, tmp_path):
    redirect = _Resp(
        is_redirect=True,
        location="https://evil.example.com/pwn.gguf",
        url="https://huggingface.co/org/model/resolve/main/m.gguf",
    )
    _install(monkeypatch, tmp_path, [redirect, _Resp(body=b"pwn")])
    events = _run("https://huggingface.co/org/model/resolve/main/m.gguf")
    assert events[0]["type"] == "error"
    assert events[0]["code"] == "REDIRECT_OFF_ALLOWLIST"
    # Only the first (redirect) request was made; the evil target was NOT fetched.
    assert len(_ScriptedClient.calls) == 1
    assert not list(tmp_path.iterdir())


# ── positive: redirect within the allow-list is followed, bearer stripped ─────


def test_redirect_within_allowlist_followed_and_auth_stripped(monkeypatch, tmp_path):
    monkeypatch.setenv("HF_TOKEN", "hf_secret")  # bearer attached on first hop
    monkeypatch.setattr(installer_mod, "_models_dir", lambda: tmp_path)
    monkeypatch.setattr(installer_mod, "_read_hf_token_from_keychain", lambda: None)
    monkeypatch.setattr("httpx.AsyncClient", _ScriptedClient)
    redirect = _Resp(
        is_redirect=True,
        location="https://cdn-lfs.huggingface.co/repo/m.gguf",
        url="https://huggingface.co/org/model/resolve/main/m.gguf",
    )
    _ScriptedClient.script = [redirect, _Resp(content_length=4, body=b"gguf")]
    _ScriptedClient.calls = []

    events = _run("https://huggingface.co/org/model/resolve/main/m.gguf")

    assert (tmp_path / "m.gguf").read_bytes() == b"gguf"
    assert any(ev.get("type") == "progress" for ev in events)
    assert len(_ScriptedClient.calls) == 2
    # First hop (huggingface.co) carries the bearer; the CDN hop must NOT.
    assert _ScriptedClient.calls[0]["headers"].get("Authorization") == "Bearer hf_secret"
    assert "Authorization" not in _ScriptedClient.calls[1]["headers"], (
        "bearer must be stripped on the cross-host CDN redirect"
    )
