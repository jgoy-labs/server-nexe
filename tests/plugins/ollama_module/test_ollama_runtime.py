"""
────────────────────────────────────
Server Nexe
Author: Jordi Goy
Location: tests/plugins/ollama_module/test_ollama_runtime.py
Description: MC-028 — unit tests for the centralised Ollama-launch runtime.
             Pins the resolution priority (NEXE_OLLAMA_BIN → macOS bundle →
             PATH), the headless detached spawn contract, and the OPT-IN
             readiness wait (wait=False must never poll after spawning).

www.jgoy.net · https://server-nexe.org
────────────────────────────────────
"""

import subprocess
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

import plugins.ollama_module.core.ollama_runtime as rt


# ──────────────────────────────────────────────────────────────────────────────
# resolve_ollama_bin — SINGLE read of NEXE_OLLAMA_BIN, priority order
# ──────────────────────────────────────────────────────────────────────────────

def test_resolve_prefers_nexe_ollama_bin_when_it_exists(monkeypatch):
    monkeypatch.setenv("NEXE_OLLAMA_BIN", "/custom/ollama")
    with patch.object(rt.os.path, "exists", return_value=True), \
         patch.object(rt.shutil, "which", return_value="/usr/local/bin/ollama"):
        assert rt.resolve_ollama_bin() == "/custom/ollama"


def test_resolve_skips_nexe_ollama_bin_when_missing(monkeypatch):
    """Override that doesn't exist on disk → fall through (matches client.py today)."""
    monkeypatch.setenv("NEXE_OLLAMA_BIN", "/custom/ollama")
    with patch.object(rt.os.path, "exists", return_value=False), \
         patch.object(rt.platform, "system", return_value="Linux"), \
         patch.object(rt.shutil, "which", return_value="/usr/local/bin/ollama"):
        assert rt.resolve_ollama_bin() == "/usr/local/bin/ollama"


def test_resolve_uses_macos_bundle_when_present(monkeypatch):
    monkeypatch.delenv("NEXE_OLLAMA_BIN", raising=False)
    with patch.object(rt.platform, "system", return_value="Darwin"), \
         patch.object(rt.os.path, "exists", return_value=True), \
         patch.object(rt.shutil, "which", return_value=None):
        assert rt.resolve_ollama_bin() == rt.OLLAMA_BUNDLE_BIN


def test_resolve_falls_back_to_path(monkeypatch):
    monkeypatch.delenv("NEXE_OLLAMA_BIN", raising=False)
    with patch.object(rt.platform, "system", return_value="Linux"), \
         patch.object(rt.os.path, "exists", return_value=False), \
         patch.object(rt.shutil, "which", return_value="/opt/homebrew/bin/ollama"):
        assert rt.resolve_ollama_bin() == "/opt/homebrew/bin/ollama"


def test_resolve_none_when_nothing_found(monkeypatch):
    monkeypatch.delenv("NEXE_OLLAMA_BIN", raising=False)
    with patch.object(rt.platform, "system", return_value="Linux"), \
         patch.object(rt.os.path, "exists", return_value=False), \
         patch.object(rt.shutil, "which", return_value=None):
        assert rt.resolve_ollama_bin() is None


# ──────────────────────────────────────────────────────────────────────────────
# spawn_ollama_serve — headless, detached, literal argv
# ──────────────────────────────────────────────────────────────────────────────

def test_spawn_returns_none_when_unresolved():
    with patch.object(rt, "resolve_ollama_bin", return_value=None), \
         patch.object(rt.subprocess, "Popen") as popen:
        assert rt.spawn_ollama_serve() is None
    popen.assert_not_called()


def test_spawn_starts_detached_serve():
    proc = MagicMock()
    with patch.object(rt, "resolve_ollama_bin", return_value="/usr/local/bin/ollama"), \
         patch.object(rt.subprocess, "Popen", return_value=proc) as popen:
        result = rt.spawn_ollama_serve()
    assert result is proc
    args, kwargs = popen.call_args
    assert args[0] == ["/usr/local/bin/ollama", "serve"]
    assert kwargs["start_new_session"] is True
    assert kwargs["stdout"] == subprocess.DEVNULL
    assert kwargs["stderr"] == subprocess.DEVNULL


def test_spawn_returns_none_on_popen_failure():
    with patch.object(rt, "resolve_ollama_bin", return_value="/usr/local/bin/ollama"), \
         patch.object(rt.subprocess, "Popen", side_effect=OSError("boom")):
        assert rt.spawn_ollama_serve() is None


# ──────────────────────────────────────────────────────────────────────────────
# is_ollama_running / wait_ollama_ready
# ──────────────────────────────────────────────────────────────────────────────

class _CM:
    def __init__(self, client):
        self._c = client

    async def __aenter__(self):
        return self._c

    async def __aexit__(self, *exc):
        return False


def _client_returning(status_seq):
    seq = list(status_seq)

    async def _get(*a, **k):
        item = seq.pop(0)
        if isinstance(item, Exception):
            raise item
        resp = MagicMock()
        resp.status_code = item
        return resp

    client = MagicMock()
    client.get = _get
    return client


async def test_is_running_true_on_200():
    with patch("httpx.AsyncClient", return_value=_CM(_client_returning([200]))):
        assert await rt.is_ollama_running("http://localhost:11434") is True


async def test_is_running_false_on_non_200():
    with patch("httpx.AsyncClient", return_value=_CM(_client_returning([503]))):
        assert await rt.is_ollama_running("http://localhost:11434") is False


async def test_is_running_false_on_exception():
    with patch("httpx.AsyncClient", return_value=_CM(_client_returning([ConnectionError("x")]))):
        assert await rt.is_ollama_running("http://localhost:11434") is False


async def test_wait_ready_returns_true_on_second_attempt():
    cm = _CM(_client_returning([503, 200]))
    with patch("httpx.AsyncClient", return_value=cm), \
         patch.object(rt.asyncio, "sleep", new=AsyncMock()):
        assert await rt.wait_ollama_ready("http://localhost:11434", attempts=5, interval=0) is True


async def test_wait_ready_times_out():
    cm = _CM(_client_returning([503, 503]))
    with patch("httpx.AsyncClient", return_value=cm), \
         patch.object(rt.asyncio, "sleep", new=AsyncMock()):
        assert await rt.wait_ollama_ready("http://localhost:11434", attempts=2, interval=0) is False


# ──────────────────────────────────────────────────────────────────────────────
# ensure_ollama_running — façade combining check + spawn + opt-in wait
# ──────────────────────────────────────────────────────────────────────────────

async def test_ensure_already_running_returns_none_no_spawn():
    with patch.object(rt, "is_ollama_running", new=AsyncMock(return_value=True)), \
         patch.object(rt, "spawn_ollama_serve") as spawn:
        result = await rt.ensure_ollama_running("http://localhost:11434")
    assert result is None
    spawn.assert_not_called()


async def test_ensure_not_installed_returns_none():
    with patch.object(rt, "is_ollama_running", new=AsyncMock(return_value=False)), \
         patch.object(rt, "spawn_ollama_serve", return_value=None):
        assert await rt.ensure_ollama_running("http://localhost:11434") is None


async def test_ensure_wait_true_polls_ready():
    proc = MagicMock()
    waiter = AsyncMock(return_value=True)
    with patch.object(rt, "is_ollama_running", new=AsyncMock(return_value=False)), \
         patch.object(rt, "spawn_ollama_serve", return_value=proc), \
         patch.object(rt, "wait_ollama_ready", new=waiter):
        result = await rt.ensure_ollama_running("http://localhost:11434", wait=True)
    assert result is proc
    waiter.assert_awaited_once()


async def test_ensure_wait_false_does_not_poll():
    """CRITICAL (routes_auth contract): wait=False must NEVER call wait_ollama_ready."""
    proc = MagicMock()
    waiter = AsyncMock(return_value=True)
    with patch.object(rt, "is_ollama_running", new=AsyncMock(return_value=False)), \
         patch.object(rt, "spawn_ollama_serve", return_value=proc), \
         patch.object(rt, "wait_ollama_ready", new=waiter):
        result = await rt.ensure_ollama_running("http://localhost:11434", wait=False)
    assert result is proc
    waiter.assert_not_awaited()
