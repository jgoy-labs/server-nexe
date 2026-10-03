"""#1136 — «Cancel·la» on the delete dialog disarms the delete on the server.

Live 03/10: the dialog came up, Jordi cancelled, and nothing reached the
server — `close(false)` only painted «↩️ Cancel·lat». The pending flag stayed
armed until the next message, and a bare "sí" there (to anything) would have
deleted the entry he had just refused. `POST /ui/memory/cancel-delete` is the
dialog's «no» and the CLI's; tests/frontend/delete_dialog_cancel.mjs proves the
dialog calls it, tests/core/cli/test_cli_reads_the_ui_wire.py that the CLI does.
"""
from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi import APIRouter, HTTPException
from starlette.datastructures import State
from starlette.requests import Request as StarletteRequest

from core.memory_facts import intents
from core.memory_facts.intent_patterns import matches_clear_all_confirm
from core.sessions import ChatSession
from plugins.web_ui_module.api.routes_memory import register_memory_routes

ENTRY = {"id": "id-1", "collection": "personal_memory", "text": "el gos de l'usuari es diu Tro",
         "score": 0.9, "metadata": {}}


@pytest.fixture(autouse=True)
def _disable_rate_limiter():
    from core.dependencies import limiter
    original = limiter.enabled
    limiter.enabled = False
    yield
    limiter.enabled = original


def _request() -> StarletteRequest:
    app = MagicMock()
    app.state = State()
    app.state.i18n = None
    return StarletteRequest({
        "type": "http", "method": "POST", "path": "/ui/memory/cancel-delete", "query_string": b"",
        "headers": [], "client": ("127.0.0.1", 12345), "app": app,
    })


def _cancel(session):
    mgr = MagicMock()
    mgr.get_session = MagicMock(side_effect=lambda sid: session if session is not None and sid == session.id else None)
    router = APIRouter()
    register_memory_routes(router, session_mgr=mgr, require_ui_auth=AsyncMock(return_value=None))
    return next(r.endpoint for r in router.routes if getattr(r, "path", None) == "/memory/cancel-delete")


def _port():
    """detect_intent says "just chat"; the "sí" matcher is the real one."""
    port = MagicMock()
    port.detect_intent.return_value = ("chat", None)
    port.matches_clear_all_confirm = matches_clear_all_confirm
    return port


def _armed() -> ChatSession:
    session = ChatSession(session_id="s1")
    session._pending_partial_delete = {"content": "...", "entries": [ENTRY]}
    return session


def test_without_the_cancel_a_bare_si_next_turn_confirms_the_delete():
    # The hazard this fixes, measured: if it stopped being real, the test
    # below would prove nothing.
    detected, _ = intents.detect_with_pending(_armed(), "sí", _port())
    assert detected == "delete_confirm"


async def test_the_cancel_disarms_and_a_si_next_turn_confirms_nothing():
    session = _armed()
    result = await _cancel(session)(_request(), {"session_id": "s1"}, None)
    assert result == {"cancelled": True}
    assert session._pending_partial_delete is None
    detected, _ = intents.detect_with_pending(session, "sí", _port())
    assert detected != "delete_confirm"


async def test_nothing_pending_answers_false_and_is_not_an_error():
    session = ChatSession(session_id="s1")
    result = await _cancel(session)(_request(), {"session_id": "s1"}, None)
    assert result == {"cancelled": False}


async def test_an_unknown_session_is_a_404():
    with pytest.raises(HTTPException) as exc:
        await _cancel(None)(_request(), {"session_id": "ghost"}, None)
    assert exc.value.status_code == 404


async def test_the_session_is_required():
    with pytest.raises(HTTPException) as exc:
        await _cancel(_armed())(_request(), {}, None)
    assert exc.value.status_code == 400
