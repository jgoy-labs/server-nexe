"""
────────────────────────────────────
Server Nexe
Author: Jordi Goy
Location: tests/core/turn/test_1105_lease_released_on_failure.py
Description: #1105 — a turn that fails after `session` lets go of the lease.

Before: only `emit`, the disconnect path and a memory command's short-circuit
released it, so a 429 (gate busy) or a 503 (no engine) left the session leased
for 600 s and the user's next message got the 409 "open elsewhere". Driven
through the REAL routes — the fix lives at the door, around the turn.

www.jgoy.net · https://server-nexe.org
────────────────────────────────────
"""
import pytest
from fastapi import APIRouter, BackgroundTasks, HTTPException

from core.endpoints.chat import chat_completions
from core.endpoints.chat_schemas import ChatCompletionRequest, Message
from core.turn.gate import EngineGate, Priority

from .conftest import door_patches, make_request


def _ui_endpoint(session_manager):
    from plugins.web_ui_module.api.routes_chat import register_chat_routes

    router = APIRouter()
    register_chat_routes(router, session_mgr=session_manager, require_ui_auth=lambda: None)
    return next(r.endpoint for r in router.routes if getattr(r, "path", None) == "/chat")


def _lease_is_free(session_manager, session_id: str) -> bool:
    """A NEW turn may take the session — what the user's next message needs."""
    result = session_manager.acquire_lease(session_id, holder="ui", turn_id="the-next-turn", where="test")
    return result.granted


async def _busy_gate(app_state, monkeypatch):
    """One slot, held by another user turn (not preemptible), and a short wait."""
    monkeypatch.setenv("NEXE_ENGINE_GATE_WAIT_S", "0.05")
    app_state.engine_gate = EngineGate(slots=1)
    await app_state.engine_gate.acquire(Priority.USER_TURN, holder="someone-else")


# ── web door ───────────────────────────────────────────────────────────────


async def test_web_json_turn_with_no_engine_releases_the_lease(app_state, session_manager,
                                                               memory_helper, server_state):
    app_state.modules = {}
    endpoint = _ui_endpoint(session_manager)
    with door_patches(server_state, memory_helper), pytest.raises(HTTPException) as exc:
        await endpoint(request=make_request(app_state),
                       body={"message": "hola", "session_id": "l1105-json", "stream": False}, _auth=None)
    assert exc.value.status_code == 503
    assert _lease_is_free(session_manager, "l1105-json")


async def test_web_json_turn_with_the_gate_busy_releases_the_lease(app_state, session_manager,
                                                                   memory_helper, server_state, monkeypatch):
    await _busy_gate(app_state, monkeypatch)
    endpoint = _ui_endpoint(session_manager)
    with door_patches(server_state, memory_helper), pytest.raises(HTTPException) as exc:
        await endpoint(request=make_request(app_state),
                       body={"message": "hola", "session_id": "l1105-busy", "stream": False}, _auth=None)
    assert exc.value.status_code == 429
    assert _lease_is_free(session_manager, "l1105-busy")


async def test_web_stream_failing_inside_the_body_releases_the_lease(app_state, session_manager,
                                                                     memory_helper, server_state, monkeypatch):
    """The 429 happens AFTER the response was committed: `generate` runs inside
    the streamed body, so the door's own try/except never sees it."""
    await _busy_gate(app_state, monkeypatch)
    endpoint = _ui_endpoint(session_manager)
    with door_patches(server_state, memory_helper):
        response = await endpoint(request=make_request(app_state),
                                  body={"message": "hola", "session_id": "l1105-stream", "stream": True},
                                  _auth=None)
        with pytest.raises(HTTPException) as exc:
            async for _ in response.body_iterator:
                pass
    assert exc.value.status_code == 429
    assert _lease_is_free(session_manager, "l1105-stream")


async def test_a_refused_turn_does_not_release_the_lease_it_was_refused_for(app_state, session_manager,
                                                                            memory_helper, server_state):
    """The 409 is someone else's lease: failing must not hand it over."""
    session_manager.create_session("l1105-409")
    session_manager.acquire_lease("l1105-409", holder="api", turn_id="the-holder", where="API")
    endpoint = _ui_endpoint(session_manager)
    with door_patches(server_state, memory_helper), pytest.raises(HTTPException) as exc:
        await endpoint(request=make_request(app_state),
                       body={"message": "hola", "session_id": "l1105-409", "stream": False}, _auth=None)
    assert exc.value.status_code == 409
    assert not _lease_is_free(session_manager, "l1105-409")


async def test_a_web_turn_that_succeeds_still_releases_it(app_state, session_manager,
                                                          memory_helper, server_state):
    endpoint = _ui_endpoint(session_manager)
    with door_patches(server_state, memory_helper):
        response = await endpoint(request=make_request(app_state),
                                  body={"message": "hola", "session_id": "l1105-ok", "stream": True},
                                  _auth=None)
        async for _ in response.body_iterator:
            pass
    assert _lease_is_free(session_manager, "l1105-ok")


# ── /v1 ────────────────────────────────────────────────────────────────────


def _v1_request(app_state, session_id: str):
    request = make_request(app_state)
    request.scope["headers"] = [(b"x-api-key", b"test-key"), (b"x-session-id", session_id.encode())]
    return request


async def test_v1_turn_with_the_gate_busy_releases_the_lease(app_state, session_manager,
                                                             memory_helper, server_state, monkeypatch):
    await _busy_gate(app_state, monkeypatch)
    body = ChatCompletionRequest(messages=[Message(role="user", content="hola")], stream=False, engine="ollama")
    with door_patches(server_state, memory_helper), pytest.raises(HTTPException) as exc:
        await chat_completions(body, _v1_request(app_state, "l1105-v1"), BackgroundTasks())
    assert exc.value.status_code == 429
    assert _lease_is_free(session_manager, "l1105-v1")
