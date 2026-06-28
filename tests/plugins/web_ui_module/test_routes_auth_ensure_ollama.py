"""
────────────────────────────────────
Server Nexe
Author: Jordi Goy
Location: tests/plugins/web_ui_module/test_routes_auth_ensure_ollama.py
Description: MC-028 — behavioural tests for the routes_auth._ensure_ollama_running
             call site after centralisation. This is a closure defined inside
             register_auth_routes(), so we reach it through the real registered
             endpoint's __closure__ (stable, no source-splitting).

             CRITICAL INVARIANT pinned here: this call site is fire-and-forget —
             it delegates with wait=False and NEVER blocks on readiness. The end-
             to-end test confirms that only the initial probe touches the network
             (no readiness poll after spawning).

www.jgoy.net · https://server-nexe.org
────────────────────────────────────
"""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

import plugins.ollama_module.core.ollama_runtime as rt
from plugins.web_ui_module.api.routes_auth import register_auth_routes


def _get_ensure_ollama_running():
    """Extract the _ensure_ollama_running closure from the registered set_backend.

    set_backend captures _ensure_ollama_running as a free variable (it calls it),
    so it lives in set_backend.__closure__ at the index of its name in co_freevars.
    """
    from fastapi import APIRouter

    router = APIRouter()

    async def _fake_auth():
        return None

    register_auth_routes(router, require_ui_auth=_fake_auth, session_mgr=MagicMock())

    for route in router.routes:
        endpoint = getattr(route, "endpoint", None)
        if endpoint is not None and endpoint.__name__ == "set_backend":
            freevars = endpoint.__code__.co_freevars
            assert "_ensure_ollama_running" in freevars, (
                "set_backend no longer closes over _ensure_ollama_running — "
                "the test hook is stale"
            )
            cell = endpoint.__closure__[freevars.index("_ensure_ollama_running")]
            return cell.cell_contents
    raise RuntimeError("set_backend endpoint not found in registered routes")


class _AsyncCM:
    def __init__(self, client):
        self._client = client

    async def __aenter__(self):
        return self._client

    async def __aexit__(self, *exc):
        return False


def _httpx_factory(get_calls, *, raise_on_get=False, status_code=200):
    async def _get(*args, **kwargs):
        get_calls.append((args, kwargs))
        if raise_on_get:
            raise ConnectionError("Ollama down")
        resp = MagicMock()
        resp.status_code = status_code
        return resp

    def _ctor(*args, **kwargs):
        client = MagicMock()
        client.get = _get
        return _AsyncCM(client)

    return _ctor


# ──────────────────────────────────────────────────────────────────────────────
# Delegation contract: maps the helper's Popen|None to a bool, with wait=False
# ──────────────────────────────────────────────────────────────────────────────

async def test_closure_delegates_with_wait_false_and_maps_started_to_true():
    """Started (helper returns a process) → True; AND the helper is invoked with
    wait=False (the routes_auth fire-and-forget contract).

    Mutation: dropping wait=False / inverting the bool mapping → fails.
    """
    ensure = _get_ensure_ollama_running()

    with patch.object(rt, "ensure_ollama_running", new=AsyncMock(return_value=MagicMock())) as m:
        result = await ensure()

    assert result is True
    m.assert_awaited_once()
    args, kwargs = m.call_args
    assert kwargs.get("wait") is False, "routes_auth must NOT wait for readiness (wait=False)"
    # the resolved base_url must be forwarded as the positional target
    from plugins.ollama_module.core.client import resolve_base_url
    assert args[0] == resolve_base_url(), "must forward the resolved Ollama base_url"


async def test_closure_maps_none_to_false():
    """Already running or not installed (helper returns None) → False."""
    ensure = _get_ensure_ollama_running()

    with patch.object(rt, "ensure_ollama_running", new=AsyncMock(return_value=None)):
        result = await ensure()

    assert result is False


# ──────────────────────────────────────────────────────────────────────────────
# End-to-end: only the initial probe hits the network — NO readiness poll
# ──────────────────────────────────────────────────────────────────────────────

async def test_closure_end_to_end_starts_and_never_waits(monkeypatch):
    """Real chain (is_ollama_running → spawn_ollama_serve), only OS calls patched.

    The probe fails (Ollama down) → spawn via PATH → return immediately. The ONLY
    network call is the single probe; a readiness wait would add more .get calls.
    Mutation: adding a wait loop to routes_auth/helper-with-wait=True → get>1.
    """
    monkeypatch.delenv("NEXE_OLLAMA_BIN", raising=False)
    ensure = _get_ensure_ollama_running()
    get_calls = []

    with patch("httpx.AsyncClient", new=_httpx_factory(get_calls, raise_on_get=True)), \
         patch.object(rt.platform, "system", return_value="Linux"), \
         patch.object(rt.os.path, "exists", return_value=False), \
         patch.object(rt.shutil, "which", return_value="/usr/local/bin/ollama"), \
         patch.object(rt.subprocess, "Popen") as popen:
        result = await ensure()

    assert result is True
    popen.assert_called_once()
    args, kwargs = popen.call_args
    assert args[0] == ["/usr/local/bin/ollama", "serve"]
    assert kwargs.get("start_new_session") is True
    assert len(get_calls) == 1, (
        "INVARIANT: routes_auth must NOT wait for readiness — only the initial "
        f"probe is allowed, got {len(get_calls)} .get calls"
    )


async def test_closure_end_to_end_already_running_returns_false():
    ensure = _get_ensure_ollama_running()
    get_calls = []

    with patch("httpx.AsyncClient", new=_httpx_factory(get_calls, status_code=200)), \
         patch.object(rt.subprocess, "Popen") as popen:
        result = await ensure()

    assert result is False, "already running → did NOT start it"
    popen.assert_not_called()
    assert len(get_calls) == 1
