"""
────────────────────────────────────
Server Nexe
Author: Jordi Goy
Location: tests/core/turn/test_v1_pending_delete.py
Description: ADR-007 C4.5 at /v1 — a model's [MEM_DELETE:] arms the same
             confirmation the web door arms, and the door says so in its own
             alphabet (nexe_pending_delete / X-Nexe-Pending-Delete). Until
             26/09 the tags landed in usage["mem_deletes"] and nobody read them.

www.jgoy.net · https://server-nexe.org
────────────────────────────────────
"""
from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi import BackgroundTasks
from starlette.datastructures import State

from core.endpoints.chat import chat_completions  # noqa: F401 — breaks a circular import
from core.sessions import ChatSession
from core.turn.adapters_api import _memory_news, api_adapters
from core.turn.context import TurnContext
from core.turn.run import TurnShortCircuit

ENTRY = {"id": "id-1", "collection": "personal_memory", "text": "el gos de l'usuari es diu Tro",
         "score": 0.9, "metadata": {}}


def _ctx(content: str, candidates=None) -> tuple[TurnContext, MagicMock]:
    helper = MagicMock()
    helper.preview_delete_from_memory = AsyncMock(return_value={"success": True, "candidates": candidates or []})
    helper.delete_memory_entries = AsyncMock()
    helper.delete_from_memory = AsyncMock()
    state = State()
    state.memory_helper = helper
    ctx = TurnContext(turn_id="t", entry="api", lang="ca", engine="ollama", app_state=state)
    ctx.body = MagicMock(rag_collections=["personal_memory"])
    ctx.session = ChatSession(session_id="s1")
    ctx.message = "oblida el gos"
    ctx.wire = {"choices": [{"message": {"role": "assistant", "content": content}}]}
    return ctx, helper


async def test_a_model_delete_tag_arms_the_confirmation_and_the_door_says_so():
    ctx, helper = _ctx("D'acord. [MEM_DELETE: el gos]", candidates=[ENTRY])

    await api_adapters(BackgroundTasks())["postprocess"](ctx)

    helper.preview_delete_from_memory.assert_awaited_once_with("el gos", collections=["personal_memory"])
    helper.delete_memory_entries.assert_not_called()
    helper.delete_from_memory.assert_not_called()
    assert ctx.session._pending_partial_delete == {"content": "el gos", "entries": [ENTRY]}
    content = ctx.wire["choices"][0]["message"]["content"]
    assert content.startswith("D'acord.") and "MEM_DELETE" not in content
    assert ENTRY["text"] in content, "the question rides in the content"
    assert ctx.usage["memory_action"] == "delete_pending"
    assert ctx.usage["pending_delete"] == ENTRY["text"]
    assert _memory_news(ctx)["Pending-Delete"] == ENTRY["text"]
    assert "mem_deletes" not in ctx.usage, "the field nobody read is gone"


async def test_a_delete_tag_the_user_never_asked_for_arms_nothing():
    """#1135 (live 03/10): a model explaining its memory wrote a delete tag
    with the user's real name. /v1 hands the user's message to the rule too."""
    ctx, helper = _ctx("Així funciono. [MEM_DELETE: el gos]", candidates=[ENTRY])
    ctx.message = "com funciona la teva memòria?"
    await api_adapters(BackgroundTasks())["postprocess"](ctx)
    helper.preview_delete_from_memory.assert_not_called()
    assert not getattr(ctx.session, "_pending_partial_delete", None)
    assert "pending_delete" not in ctx.usage


async def test_no_match_arms_nothing_and_the_door_stays_quiet():
    ctx, helper = _ctx("D'acord. [MEM_DELETE: el gos]", candidates=[])

    await api_adapters(BackgroundTasks())["postprocess"](ctx)

    assert not getattr(ctx.session, "_pending_partial_delete", None)
    assert ctx.wire["choices"][0]["message"]["content"] == "D'acord."
    assert "pending_delete" not in ctx.usage
    assert _memory_news(ctx)["Pending-Delete"] == ""


async def test_a_stream_names_the_pending_delete_on_the_last_chunk():
    """C4.6-b: the question goes out as a content delta, and the entry rides
    on the last chunk before `[DONE]`, the same name as the JSON body."""
    import json

    ctx, helper = _ctx("D'acord. [MEM_DELETE: el gos]", candidates=[ENTRY])
    ctx.response = "D'acord. [MEM_DELETE: el gos]"
    ctx.engine = "ollama"
    ctx.usage["served_model"] = "qwen3.5:4b"
    table = api_adapters(BackgroundTasks(), streaming=True)

    mid = [c async for c in table["postprocess"](ctx)]
    tail = [c async for c in table["emit"](ctx)]

    helper.preview_delete_from_memory.assert_awaited_once()
    assert mid and ENTRY["text"] in mid[0] and "MEM_DELETE" not in mid[0]
    assert tail[-1].strip() == "data: [DONE]"
    final = json.loads(tail[-2][len("data:"):].strip())
    assert final["nexe_pending_delete"] == ENTRY["text"]
    assert final["choices"][0]["finish_reason"] == "stop"


async def test_a_pending_confirmation_is_not_overwritten_at_this_door_either():
    ctx, helper = _ctx("[MEM_DELETE: el gat]", candidates=[ENTRY])
    ctx.session._pending_partial_delete = {"content": "first", "entries": [{**ENTRY, "id": "id-0", "text": "first"}]}

    await api_adapters(BackgroundTasks())["postprocess"](ctx)

    helper.preview_delete_from_memory.assert_not_called()
    assert ctx.session._pending_partial_delete["content"] == "first"


async def test_a_typed_forget_at_v1_exposes_the_pending_entry_too():
    """C3.1 arms it at the `intent` step; since C4.5 this door says which entry
    is waiting, the same way it does for a model's tag."""
    ctx, helper = _ctx("", candidates=[ENTRY])
    helper.detect_intent = MagicMock(return_value=("delete", "el gos"))
    helper.matches_clear_all_confirm = MagicMock(return_value=False)
    ctx.app_state.session_manager = MagicMock()
    ctx.app_state.session_manager.get_or_create_session.return_value = ctx.session
    ctx.message = "oblida que el gos es diu Tro"
    ctx.body = MagicMock(rag_collections=None, model=None)

    with pytest.raises(TurnShortCircuit):
        await api_adapters(BackgroundTasks())["intent"](ctx)

    assert ctx.session._pending_partial_delete["entries"] == [ENTRY]
    assert ctx.usage["pending_delete"] == ENTRY["text"]
    assert ctx.usage["memory_action"] == "delete_pending"
    assert _memory_news(ctx)["Pending-Delete"] == ENTRY["text"]
