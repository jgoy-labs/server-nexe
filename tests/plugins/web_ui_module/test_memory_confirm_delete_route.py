"""
────────────────────────────────────
Server Nexe
Author: Jordi Goy
Location: tests/plugins/web_ui_module/test_memory_confirm_delete_route.py
Description: `POST /ui/memory/confirm-delete` (ADR-007 C4.5, decision of 26/09):
             the dialog's button deletes THE entry the session has pending, by
             exact id, through the same core path a typed "sí" takes — no
             second search by text, B093 applied, pending flag cleared.

www.jgoy.net · https://server-nexe.org
────────────────────────────────────
"""
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import APIRouter, HTTPException
from starlette.datastructures import State
from starlette.requests import Request as StarletteRequest

from core.memory_facts import intents
from core.memory_facts.intent_texts import text as _intent_text
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
        "type": "http", "method": "POST", "path": "/ui/memory/confirm-delete", "query_string": b"",
        "headers": [], "client": ("127.0.0.1", 12345), "app": app,
    })


def _endpoint(session_mgr):
    router = APIRouter()
    register_memory_routes(router, session_mgr=session_mgr, require_ui_auth=AsyncMock(return_value=None))
    return next(r.endpoint for r in router.routes if getattr(r, "path", None) == "/memory/confirm-delete")


def _manager(session):
    mgr = MagicMock()
    mgr.get_session = MagicMock(side_effect=lambda sid: session if session is not None and sid == session.id else None)
    return mgr


def _helper(entry=ENTRY):
    mh = MagicMock()
    mh.delete_memory_entries = AsyncMock(return_value={
        "success": True, "deleted": 1,
        "deleted_facts": [{"text": entry["text"], "id": entry["id"], "score": entry["score"]}],
    })
    mh.delete_from_memory = AsyncMock()
    return mh


async def _post(session_mgr, body, helper):
    with patch("core.memory_facts.helper_for", return_value=helper):
        return await _endpoint(session_mgr)(_request(), body, None)


async def test_the_button_deletes_the_pending_entry_by_id_and_clears_it():
    session = ChatSession(session_id="s1")
    session._pending_partial_delete = {"content": "el gos", "entries": [ENTRY]}
    mh = _helper()

    result = await _post(_manager(session), {"session_id": "s1", "fact": ENTRY["text"]}, mh)

    mh.delete_memory_entries.assert_awaited_once_with([ENTRY])
    mh.delete_from_memory.assert_not_called()  # the old route searched memory again by text
    assert result["success"] is True and result["deleted"] == 1
    assert result["deleted_facts"] == [{"text": ENTRY["text"]}]
    assert result["memory_action"] == "delete"
    assert session._pending_partial_delete is None, "the pending flag stayed armed"


async def test_nothing_pending_is_a_404_and_deletes_nothing():
    session = ChatSession(session_id="s1")
    mh = _helper()
    with pytest.raises(HTTPException) as exc:
        await _post(_manager(session), {"session_id": "s1", "fact": "whatever"}, mh)
    assert exc.value.status_code == 404
    assert exc.value.detail == _intent_text("delete.nothing_pending")
    mh.delete_memory_entries.assert_not_called()
    mh.delete_from_memory.assert_not_called()


async def test_an_unknown_session_is_a_404():
    with pytest.raises(HTTPException) as exc:
        await _post(_manager(None), {"session_id": "ghost", "fact": "x"}, _helper())
    assert exc.value.status_code == 404


async def test_the_session_is_required():
    with pytest.raises(HTTPException) as exc:
        await _post(_manager(ChatSession(session_id="s1")), {"fact": "x"}, _helper())
    assert exc.value.status_code == 400


async def test_a_profile_entry_is_confirmed_by_the_text_the_dialog_showed_b093():
    profile_type = next(iter(intents.PROFILE_LIKE_TYPES))
    entry = {**ENTRY, "text": "the user is called Aran", "metadata": {"type": profile_type}}
    mh = _helper(entry)

    # A bare click with no reference: B093 refuses, nothing dies, the answer says so.
    session = ChatSession(session_id="s1")
    session._pending_partial_delete = {"content": "x", "entries": [entry]}
    refused = await _post(_manager(session), {"session_id": "s1", "fact": ""}, mh)
    assert refused["success"] is False and refused["deleted"] == 0
    assert refused["memory_action"] == "delete_blocked"
    mh.delete_memory_entries.assert_not_called()

    # The dialog sends the entry's own text: that names it.
    session = ChatSession(session_id="s1")
    session._pending_partial_delete = {"content": "x", "entries": [entry]}
    confirmed = await _post(_manager(session), {"session_id": "s1", "fact": entry["text"]}, mh)
    assert confirmed["deleted"] == 1
    mh.delete_memory_entries.assert_awaited_once_with([entry])


async def test_the_dialogs_own_text_is_an_explicit_reference_even_with_short_words():
    """Live 26/09: the entry «el meu gos es diu Tro.» is profile-like and none
    of its words is long enough for `references_entry`; the click was refused.
    What the dialog showed, sent back, names the entry."""
    profile_type = next(iter(intents.PROFILE_LIKE_TYPES))
    entry = {**ENTRY, "text": "el meu gos es diu Tro.", "metadata": {"type": profile_type}}
    mh = _helper(entry)
    session = ChatSession(session_id="s1")
    session._pending_partial_delete = {"content": "el gos", "entries": [entry]}

    result = await _post(_manager(session), {"session_id": "s1", "fact": "el meu gos es diu Tro."}, mh)

    assert result["deleted"] == 1 and result["success"] is True
    mh.delete_memory_entries.assert_awaited_once_with([entry])
    assert session._pending_partial_delete is None
