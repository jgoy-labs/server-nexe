"""
────────────────────────────────────
Server Nexe
Author: Jordi Goy
Location: tests/core/test_lifespan_launch_ollama.py
Description: MC-028 — behavioural tests for core/lifespan_services._launch_ollama
             after the Ollama-launch logic was centralised in ollama_runtime.

             These started life as characterisation tests pinning the PRE-MC-028
             behaviour (PATH-only spawn). The unification (Jordi-approved) made
             this call site honour NEXE_OLLAMA_BIN + the macOS bundle via the
             shared spawn_ollama_serve(); the tests now assert that NEW contract:
             the binary selection is delegated, but the readiness wait stays here
             and reuses the shared startup client.

www.jgoy.net · https://server-nexe.org
────────────────────────────────────
"""

import subprocess
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

import core.lifespan_services as ls
import plugins.ollama_module.core.ollama_runtime as rt


class _Resp:
    def __init__(self, status_code: int):
        self.status_code = status_code


def _fake_client(get_side_effect):
    client = MagicMock()
    client.get = AsyncMock(side_effect=get_side_effect)
    return client


# ──────────────────────────────────────────────────────────────────────────────
# 1 — Not installed (spawn returns None): no process stored, no readiness poll
# ──────────────────────────────────────────────────────────────────────────────

async def test_launch_ollama_not_installed_does_not_store_or_poll():
    """spawn_ollama_serve() → None ⇒ _launch_ollama stores nothing and never polls.

    Mutation: making _launch_ollama poll/store regardless of spawn → fails.
    """
    server_state = SimpleNamespace(ollama_process="UNSET")
    client = _fake_client(get_side_effect=AssertionError("must not poll when Ollama is unavailable"))

    with patch.object(rt, "spawn_ollama_serve", return_value=None):
        await ls._launch_ollama(client, "http://localhost:11434", server_state)

    assert server_state.ollama_process == "UNSET"
    client.get.assert_not_awaited()


# ──────────────────────────────────────────────────────────────────────────────
# 2 — Spawn succeeds: process stored on server_state, polled until ready
# ──────────────────────────────────────────────────────────────────────────────

async def test_launch_ollama_stores_process_and_polls_until_ready():
    server_state = SimpleNamespace(ollama_process=None)
    proc = MagicMock(name="popen_proc")
    client = _fake_client(get_side_effect=[_Resp(503), _Resp(200)])

    with patch.object(rt, "spawn_ollama_serve", return_value=proc), \
         patch.object(ls.asyncio, "sleep", new=AsyncMock()):
        await ls._launch_ollama(client, "http://localhost:11434", server_state)

    assert server_state.ollama_process is proc, "spawned process must be stored for shutdown reaping"
    assert client.get.await_count == 2, "must keep polling on non-200 and stop at the first 200"


# ──────────────────────────────────────────────────────────────────────────────
# 3 — UNIFICATION (the latent DMG bug is now fixed): with `ollama` absent from
#     PATH but NEXE_OLLAMA_BIN pointing at an existing binary, _launch_ollama
#     DOES start it (pre-MC-028 it was PATH-only and would silently skip).
# ──────────────────────────────────────────────────────────────────────────────

async def test_launch_ollama_now_honours_nexe_ollama_bin(monkeypatch):
    """End-to-end: lifespan no longer PATH-only — it honours the DMG override.

    Drives the real resolve_ollama_bin() → spawn_ollama_serve() chain (only the
    OS-level Popen/which/exists are patched), proving the unification.
    """
    monkeypatch.setenv("NEXE_OLLAMA_BIN", "/dmg/Ollama.app/Contents/Resources/ollama")
    server_state = SimpleNamespace(ollama_process=None)
    proc = MagicMock(name="popen_proc")
    client = _fake_client(get_side_effect=[_Resp(200)])

    with patch.object(rt.os.path, "exists", return_value=True), \
         patch.object(rt.shutil, "which", return_value=None), \
         patch.object(rt.subprocess, "Popen", return_value=proc) as popen, \
         patch.object(ls.asyncio, "sleep", new=AsyncMock()):
        await ls._launch_ollama(client, "http://localhost:11434", server_state)

    popen.assert_called_once()
    args, kwargs = popen.call_args
    assert args[0] == ["/dmg/Ollama.app/Contents/Resources/ollama", "serve"], (
        "lifespan must now spawn the NEXE_OLLAMA_BIN override (was PATH-only pre-MC-028)"
    )
    assert kwargs.get("start_new_session") is True
    assert kwargs.get("stdout") == subprocess.DEVNULL
    assert kwargs.get("stderr") == subprocess.DEVNULL
    assert server_state.ollama_process is proc


# ──────────────────────────────────────────────────────────────────────────────
# 4 — Orchestration (_auto_start_services): the decision to call _launch_ollama
#     (running? + NEXE_AUTOSTART_OLLAMA) — the caller's branching logic.
# ──────────────────────────────────────────────────────────────────────────────

class _NoopCM:
    async def __aenter__(self):
        return MagicMock()

    async def __aexit__(self, *exc):
        return False


@pytest.mark.parametrize(
    "running,autostart,expect_launch",
    [
        (True, "true", False),   # already running → never launch
        (False, "false", False),  # not running but auto-start disabled → don't launch
        (False, "true", True),    # not running + auto-start on → launch
    ],
)
async def test_auto_start_services_launch_decision(monkeypatch, running, autostart, expect_launch):
    """Pin the orchestrator's branching: _launch_ollama is invoked iff Ollama is
    not already running AND NEXE_AUTOSTART_OLLAMA is truthy.

    Mutation: flipping either guard in _auto_start_services → a row fails.
    """
    monkeypatch.setenv("NEXE_AUTOSTART_OLLAMA", autostart)
    server_state = SimpleNamespace(ollama_process=None, qdrant_available=False)

    with patch("httpx.AsyncClient", return_value=_NoopCM()), \
         patch.object(ls, "_setup_qdrant"), \
         patch.object(ls, "_check_ollama_running", new=AsyncMock(return_value=running)), \
         patch.object(ls, "_launch_ollama", new=AsyncMock()) as launch:
        await ls._auto_start_services({}, ls.Path("/tmp"), server_state)

    assert (launch.await_count == 1) is expect_launch, (
        f"running={running} autostart={autostart}: expected launch={expect_launch}"
    )
