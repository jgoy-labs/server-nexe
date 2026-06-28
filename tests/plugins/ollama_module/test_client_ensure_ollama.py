"""
────────────────────────────────────
Server Nexe
Author: Jordi Goy
Location: tests/plugins/ollama_module/test_client_ensure_ollama.py
Description: MC-028 — behavioural tests for OllamaClient.ensure_ollama_running
             after it was rewired to delegate to the centralised ollama_runtime.

             The canonical client call site now (a) delegates with wait=True and
             (b) KEEPS the spawned Popen on self._ollama_process so reap_process()
             can reap it at shutdown. Existing suites mocked ensure_ollama_running
             wholesale, leaving this new body uncovered — these tests close that
             gap and exercise the real production method (no theatre): the
             shutdown chain ensure → reap is driven end-to-end.

www.jgoy.net · https://server-nexe.org
────────────────────────────────────
"""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

import plugins.ollama_module.core.ollama_runtime as rt
from plugins.ollama_module.core.client import OllamaClient


# ──────────────────────────────────────────────────────────────────────────────
# Delegation contract: wait=True, base_url forwarded, process stored for reaping
# ──────────────────────────────────────────────────────────────────────────────

async def test_client_delegates_with_wait_true_and_stores_process():
    """Started: the spawned Popen is kept on self._ollama_process (for reaping),
    and the helper is called with the client's base_url and wait=True.

    Mutation: dropping `self._ollama_process = process` or passing wait=False
    (in client.py) → this fails.
    """
    c = OllamaClient("http://localhost:11434")
    assert c._ollama_process is None

    proc = MagicMock(name="popen")
    with patch.object(rt, "ensure_ollama_running", new=AsyncMock(return_value=proc)) as m:
        await c.ensure_ollama_running()

    assert c._ollama_process is proc, "spawned process must be stored so reap_process() can reap it"
    m.assert_awaited_once()
    args, kwargs = m.call_args
    assert args[0] == "http://localhost:11434", "must forward the client's base_url"
    assert kwargs.get("wait") is True, "client call site must wait for readiness (wait=True)"


async def test_client_does_not_store_when_already_running_or_absent():
    """Helper returns None (already running / not installed) → nothing to reap."""
    c = OllamaClient("http://localhost:11434")

    with patch.object(rt, "ensure_ollama_running", new=AsyncMock(return_value=None)):
        await c.ensure_ollama_running()

    assert c._ollama_process is None


# ──────────────────────────────────────────────────────────────────────────────
# Shutdown chain (end-to-end, no mock of our own code): ensure → reap_process
# ──────────────────────────────────────────────────────────────────────────────

async def test_ensure_then_reap_polls_the_stored_handle():
    """Anti-regression: a process started via ensure_ollama_running is reaped by
    reap_process() at shutdown — i.e. poll() is called on the stored handle.

    Mutation: if ensure stops storing the handle, reap_process() sees None and
    proc.poll() is never called → this fails.
    """
    c = OllamaClient("http://localhost:11434")
    proc = MagicMock(name="popen")

    with patch.object(rt, "ensure_ollama_running", new=AsyncMock(return_value=proc)):
        await c.ensure_ollama_running()

    c.reap_process()
    proc.poll.assert_called_once()


async def test_reap_is_safe_when_nothing_was_started():
    """reap_process() must be a no-op (no crash) when no process was stored."""
    c = OllamaClient("http://localhost:11434")
    # never started anything
    c.reap_process()  # must not raise
    assert c._ollama_process is None


# ──────────────────────────────────────────────────────────────────────────────
# Real chain (only OS-level calls patched): client honours NEXE_OLLAMA_BIN too
# ──────────────────────────────────────────────────────────────────────────────

async def test_client_end_to_end_starts_and_stores(monkeypatch):
    """Drive the real ensure_ollama_running → spawn_ollama_serve chain: Ollama is
    down, PATH has the binary → it is spawned and the handle stored. Only httpx /
    subprocess / shutil / os.path are patched (production logic runs).
    """
    monkeypatch.delenv("NEXE_OLLAMA_BIN", raising=False)
    c = OllamaClient("http://localhost:11434")
    proc = MagicMock(name="popen")

    class _CM:
        def __init__(self, client):
            self._c = client

        async def __aenter__(self):
            return self._c

        async def __aexit__(self, *exc):
            return False

    async def _down_get(*a, **k):
        raise ConnectionError("down")

    def _ctor(*a, **k):
        cl = MagicMock()
        cl.get = _down_get
        return _CM(cl)

    with patch("httpx.AsyncClient", new=_ctor), \
         patch.object(rt.platform, "system", return_value="Linux"), \
         patch.object(rt.os.path, "exists", return_value=False), \
         patch.object(rt.shutil, "which", return_value="/usr/local/bin/ollama"), \
         patch.object(rt.subprocess, "Popen", return_value=proc) as popen, \
         patch.object(rt.asyncio, "sleep", new=AsyncMock()):
        await c.ensure_ollama_running()

    popen.assert_called_once()
    args, _ = popen.call_args
    assert args[0] == ["/usr/local/bin/ollama", "serve"]
    assert c._ollama_process is proc
