"""C2.3 (ADR-007 §9/I9), at the column's `session` step: both doors refuse a
second live writer with a 409 carrying the blocking lease, and release it
wherever the turn actually ends — `emit` on the happy/short-circuit path,
`persist_assistant_turn` on the client-disconnect path (the only one where
`emit` never runs at all).

Exercises the real adapters (`ui_adapters`, `api_adapters`) against a real
`SessionManager` over a tmp dir — no route, no HTTP layer, same posture as
`test_api_turn_order.py` / `test_turn_adapters_ui.py`.
"""
from __future__ import annotations

from unittest.mock import MagicMock

import pytest
from fastapi import BackgroundTasks, HTTPException

from core.endpoints.chat import chat_completions  # noqa: F401 — import order avoids a circular import (see test_api_turn_order.py)
from core.endpoints.chat_schemas import ChatCompletionRequest, Message
from core.sessions.session_manager import SessionManager
from core.turn.adapters_api import api_adapters
from core.turn.context import TurnContext
from core.turn.gate import EngineGate
from plugins.web_ui_module.api.turn_adapters import ui_adapters

pytestmark = pytest.mark.asyncio


class _FakeAppState:
    def __init__(self, session_manager):
        self.session_manager = session_manager
        self.engine_gate = EngineGate(slots=100)
        # No post_commit_queue attached — queue_for() falls back to None,
        # exactly the "not every caller has one" case gate_for/queue_for
        # exist for.


@pytest.fixture
def manager(tmp_path, monkeypatch):
    monkeypatch.setenv("NEXE_ENV", "development")
    return SessionManager(storage_path=str(tmp_path / "sessions"))


# --------------------------------------------------------------- UI door


async def test_ui_second_door_gets_409_with_the_lease(manager):
    manager.create_session("s1")
    table = ui_adapters(manager, streaming=False)
    app_state = _FakeAppState(manager)

    ctx1 = TurnContext(turn_id="t1", entry="ui", body={"session_id": "s1"}, app_state=app_state)
    await table["session"](ctx1)  # acquires

    ctx2 = TurnContext(turn_id="t2", entry="ui", body={"session_id": "s1"}, app_state=app_state)
    with pytest.raises(HTTPException) as excinfo:
        await table["session"](ctx2)
    assert excinfo.value.status_code == 409
    assert excinfo.value.detail["code"] == "session_leased"
    assert excinfo.value.detail["lease"]["turn_id"] == "t1"
    assert excinfo.value.detail["lease"]["where"] == "web UI"


async def test_ui_force_lease_takes_over(manager):
    manager.create_session("s1")
    table = ui_adapters(manager, streaming=False)
    app_state = _FakeAppState(manager)

    ctx1 = TurnContext(turn_id="t1", entry="ui", body={"session_id": "s1"}, app_state=app_state)
    await table["session"](ctx1)

    ctx2 = TurnContext(
        turn_id="t2", entry="ui", body={"session_id": "s1", "force_lease": True}, app_state=app_state,
    )
    await table["session"](ctx2)  # must not raise
    assert manager.get_session("s1").lease["turn_id"] == "t2"


async def test_ui_lease_released_at_emit_json(manager):
    manager.create_session("s1")
    table = ui_adapters(manager, streaming=False)
    app_state = _FakeAppState(manager)

    ctx = TurnContext(turn_id="t1", entry="ui", body={"session_id": "s1"}, app_state=app_state)
    await table["session"](ctx)
    assert manager.get_session("s1").lease is not None
    ctx.response = "hola"
    ctx.intent = "chat"
    await table["emit"](ctx)
    assert manager.get_session("s1").lease is None


async def test_ui_lease_released_at_emit_stream_short_circuit(manager):
    """`emit_stream` when `stream_ctx` is None — the short-circuit path
    (a memory command's pre-built answer, char by char)."""
    manager.create_session("s1")
    table = ui_adapters(manager, streaming=True)
    app_state = _FakeAppState(manager)

    ctx = TurnContext(turn_id="t1", entry="ui", body={"session_id": "s1"}, app_state=app_state)
    await table["session"](ctx)
    ctx.response = "Fet."
    async for _ in table["emit"](ctx):
        pass
    assert manager.get_session("s1").lease is None


async def test_ui_lease_released_when_client_disconnects_mid_stream(manager):
    """`persist_assistant_turn` is the ONLY step that still runs on a client
    disconnect (AFTER_CANCEL) — `emit` never does, so this is the only place
    left to release the lease on that path."""
    manager.create_session("s1")
    table = ui_adapters(manager, streaming=True)
    app_state = _FakeAppState(manager)

    ctx = TurnContext(turn_id="t1", entry="ui", body={"session_id": "s1"}, app_state=app_state)
    await table["session"](ctx)
    ui_scratch = ctx.usage.setdefault("ui", {})
    ui_scratch["stream_ctx"] = MagicMock()
    ui_scratch["flags"] = MagicMock(trunc=False, trunc_continuable=False)
    ctx.response = "resposta parcial"
    ctx.outcomes["generate"] = "cancelled"

    await table["persist_assistant_turn"](ctx)

    assert manager.get_session("s1").lease is None


# -------------------------------------------------------------- API door


def _fake_v1_request(app_state):
    """A real dict for `.headers` (derive_session_id calls `.get` on it — a
    bare MagicMock would return a truthy Mock for ANY key, including
    "x-session-id", and that non-string would blow up SessionManager's id
    validation) and a real `.app.state` (session collision resolution reads
    it)."""
    req = MagicMock()
    req.headers = {}
    req.app.state = app_state
    return req


def _v1_body(text: str) -> ChatCompletionRequest:
    """A real pydantic model, not a MagicMock: `getattr(body, "force_lease",
    False)` in the adapter must see a real AttributeError-backed default —
    a MagicMock returns a truthy Mock for ANY attribute, silently forcing
    `force=True` on every acquire and hiding the whole point of this test."""
    return ChatCompletionRequest(messages=[Message(role="user", content=text)])


async def test_api_second_door_gets_409_with_the_lease(manager):
    table = api_adapters(BackgroundTasks())
    app_state = _FakeAppState(manager)
    request = _fake_v1_request(app_state)
    body = _v1_body("hola, sempre el mateix missatge")

    ctx1 = TurnContext(turn_id="t1", entry="api", request=request, app_state=app_state)
    ctx1.body = body
    await table["session"](ctx1)

    ctx2 = TurnContext(turn_id="t2", entry="api", request=request, app_state=app_state)
    ctx2.body = body  # same messages → derive_session_id resolves the same thread
    with pytest.raises(HTTPException) as excinfo:
        await table["session"](ctx2)
    assert excinfo.value.status_code == 409
    assert excinfo.value.detail["code"] == "session_leased"


async def test_api_lease_released_at_emit(manager):
    table = api_adapters(BackgroundTasks())
    app_state = _FakeAppState(manager)
    request = _fake_v1_request(app_state)

    ctx = TurnContext(turn_id="t1", entry="api", request=request, app_state=app_state)
    ctx.body = _v1_body("hola")
    await table["session"](ctx)
    session_id = ctx.session_id
    assert manager.get_session(session_id) is not None
    assert manager.get_session(session_id).lease is not None

    ctx.wire = {"choices": [{"message": {"content": "hola"}}]}
    ctx.engine = "ollama"
    ctx.recall_text = ""
    ctx.engine_fallback_from = None
    ctx.engine_fallback_reason = "preferred_unavailable"
    await table["emit"](ctx)

    assert manager.get_session(session_id).lease is None
