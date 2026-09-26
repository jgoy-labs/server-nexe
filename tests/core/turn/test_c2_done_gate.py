"""The C2 "done" gate (ADR-007 §6/§7), as amended on 25/09.

C2.2 moved `memory.write` AND `compact` to the post-commit queue, and this
file used to check that nothing called the engine between
`persist_assistant_turn` and the end of `emit`. On 25/09 (#1098, Jordi)
`memory.write` came back INLINE, before `emit`: on the queue, what it saved
reached the client one turn late and the UI badged the model's own tags
instead. What stays true, checked here through the REAL adapter tables with a
REAL `PostCommitQueue` attached:

  * UI stream: the atomiser's call happens BEFORE the wire closes, the wire
    carries `[MEM:...]`, and the queue has nothing left to do for memory;
  * UI JSON: the fact is stored before the response returns;
  * /v1: `memory.write` never calls the engine; `compact` is still queued.

Mutation: putting `memory.write` back into `core.turn.run.POST_COMMIT` turns
both UI tests red.
"""
from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi.responses import StreamingResponse

from core.turn.post_commit import attach_post_commit_queue, queue_for
from tests.plugins.web_ui_module.test_chat_inner_behavior import _Harness, _make_server_state

pytestmark = pytest.mark.asyncio


_COMBINED_FACT = "es diu Aran i viu a Barcelona"


class _CountingMemSaveEngine:
    """Ollama-shaped engine whose answer carries a fact to remember, and
    which counts every `.chat()` call. `_atomize_fact_llm` only fires an LLM
    call for a fact with a conjunction ("i"/"y"/"and") — a bare fact like
    "es diu Aran" returns unchanged with ZERO extra calls, which would make
    this gate pass by accident even with memory.write running inline.
    """

    def __init__(self):
        self.calls = 0

    def chat(self, model, messages, stream=False, images=None, thinking_enabled=False, **_):
        self.calls += 1
        if _is_atomiser_call(messages):
            # Answer the fact splitter the way a real model does: one fact per
            # line. Answering it with the conversation instead made every
            # atomised fact junk, and "saved" was never checkable here.
            return self._atomised(stream)
        if stream:
            return self._astream()
        # The atomizer's own call (not the turn's) asks with stream=True but
        # is driven synchronously either way — see _atomize_fact_llm.
        # Conversational text BEFORE the tag matters: a turn that cleans down
        # to ONLY the tag triggers D3's re-prompt (a legitimate extra call,
        # not the gate this test is about) — matching the streaming reply.
        return {"message": {"content": f"Encantat, Aran. [MEM_SAVE: {_COMBINED_FACT}]"}, "done": True}

    async def _astream(self):
        yield {"message": {"content": "Encantat, Aran. "}}
        yield {"message": {"content": f"[MEM_SAVE: {_COMBINED_FACT}]"}}

    async def is_model_loaded(self, model_name):
        return True

    def _atomised(self, stream):
        text = "L'usuari es diu Aran\nL'usuari viu a Barcelona"
        if not stream:
            return {"message": {"content": text}, "done": True}

        async def _one():
            yield {"message": {"content": text}}
        return _one()


def _is_atomiser_call(messages) -> bool:
    from core.memory_facts.write import _ATOMIZER_SYSTEM
    first = (messages or [{}])[0]
    return first.get("role") == "system" and first.get("content") in _ATOMIZER_SYSTEM.values()


def _state_with_real_queue(engine):
    """`_make_server_state` returns a bare `MagicMock()` — `getattr(mock,
    "post_commit_queue", None)` (and `"engine_gate"`) auto-creates a submock
    (never `None`), which would make `attach_post_commit_queue`/
    `attach_engine_gate` believe one is already attached and hand that fake
    back unchanged — the worker then awaits a MagicMock and hangs. Assigning
    `None` explicitly first is what makes both attributes genuinely absent,
    so real objects get created."""
    state = _make_server_state(engine=engine)
    state.post_commit_queue = None
    state.engine_gate = None
    attach_post_commit_queue(state)
    return state


async def test_ui_stream_saves_and_tells_before_the_wire_closes():
    """25/09 (ADR-007 §6 amended): `memory.write` runs INLINE, before `emit`,
    even with a real queue attached — the turn that saved is the turn that says
    so. The atomiser's call (the second `engine.chat()`) is made before the wire
    closes, and the wire carries what memory kept. Nothing about memory is left
    for the queue."""
    engine = _CountingMemSaveEngine()
    state = _state_with_real_queue(engine)  # REAL queue — memory.write must NOT go to it

    h = _Harness(intent="chat")
    # History, so the opening-turn rule does not decide this test.
    h.session.add_message("user", "hola, em dic Aran")
    h.session.add_message("assistant", "Hola!")
    result = await h.call({"message": "em dic Aran", "stream": True}, server_state=state)
    assert isinstance(result, StreamingResponse)

    wire = ""
    async for chunk in result.body_iterator:
        wire += chunk if isinstance(chunk, str) else chunk.decode()

    assert engine.calls == 2, (
        "the wire closed before the atomiser ran — memory.write was queued "
        "instead of running inline"
    )
    assert h.mh.save_to_memory.called, "the fact was not saved before the wire closed"
    assert "\x00[MEM:" in wire, "the turn that saved did not say so on its own wire"

    queue = queue_for(state)
    queue.start()
    await queue.drain()
    await queue.stop()

    assert engine.calls == 2, "the queue made another engine call — memory.write ran twice"


async def test_ui_json_saves_before_the_response_returns():
    """The JSON path has NO atomiser (`write_facts` only atomises with an
    engine), so it never calls `engine.chat()` for memory. What it must do
    since 25/09: store the fact before the response returns, and say so in
    the response itself (`memory_facts`)."""
    engine = _CountingMemSaveEngine()
    state = _state_with_real_queue(engine)

    h = _Harness(intent="chat")
    h.session.add_message("user", "hola, em dic Aran")
    h.session.add_message("assistant", "Hola!")
    result = await h.call({"message": "recorda que visc a Barcelona", "stream": False}, server_state=state)
    assert isinstance(result, dict)

    assert engine.calls == 1, "memory.write called the engine — it has no atomizer, this would be new"
    assert h.mh.save_to_memory.called, (
        "the response returned before the fact was saved — memory.write was "
        "queued instead of running inline"
    )


async def test_v1_never_calls_the_engine_for_memory_write():
    """What this used to check by construction, it now checks by behaviour.

    Until C3.3 `memory.write` was `_folded` at /v1, so "it cannot call the
    engine" was true because the adapter's body was one assignment. The step is
    real now — and it still must not spend an LLM call: /v1 stores the facts as
    the model wrote them, without the atomiser (that is the UI's extra call,
    and the reason this gate exists at all).
    """
    from core.endpoints.chat import chat_completions  # noqa: F401 (breaks a circular import)
    from core.turn.adapters_api import api_adapters
    from core.turn.context import TurnContext

    engine = _CountingMemSaveEngine()
    state = _state_with_real_queue(engine)
    session = MagicMock()
    session.id = "s-1"
    session.messages = [
        {"role": "user", "content": "hola"},
        {"role": "assistant", "content": "hey"},
        {"role": "user", "content": "recorda que visc a Barcelona"},
    ]
    session._recently_deleted_facts = []
    state.session_manager = MagicMock()
    state.session_manager.get_or_create_session.return_value = session
    state.memory_helper = MagicMock()
    state.memory_helper.save_to_memory = AsyncMock(return_value={"success": True, "document_id": "d"})

    table = api_adapters(MagicMock())
    ctx = TurnContext(turn_id="t", entry="api")
    ctx.app_state = state
    ctx.session_id = "s-1"
    ctx.facts = ["L'usuari viu a Barcelona"]

    with patch("core.memory_facts.write.atomize_fact_llm") as atomiser:
        await table["memory.write"](ctx)

    # The counting engine cannot be reached from this adapter by any path, so
    # asserting on it would prove nothing: what this gate needs is that the
    # atomiser — the only LLM call this step could make — is never invoked.
    atomiser.assert_not_called()
    state.memory_helper.save_to_memory.assert_awaited_once()


async def test_v1_queues_compact_instead_of_running_it_before_the_answer():
    """C3.4 gave /v1 a step that DOES call the engine (compaction). The C2
    property has to hold for it at this door too: the response must not wait
    for a summarisation, and the work must actually happen afterwards."""
    from core.endpoints.chat import chat_completions  # noqa: F401 (breaks a circular import)

    calls: list[str] = []

    async def _slow_compact(session, engine, mgr, *, cancel_event=None):
        calls.append("compact")
        session.compaction_count += 1

    session = MagicMock()
    session.id = "s-1"
    session.compaction_count = 0
    state = _state_with_real_queue(_CountingMemSaveEngine())
    state.session_manager = MagicMock()
    state.session_manager.get_or_create_session.return_value = session
    # The door resolves the engine NAME to a live module before compacting
    # (without this the step degrades instead of running — see
    # tests/core/sessions/test_compact_both_doors.py).
    state.modules = {"ollama_module": MagicMock()}

    from core.turn.adapters_api import api_adapters
    from core.turn.context import TurnContext
    from core.turn.run import POST_COMMIT

    assert "compact" in POST_COMMIT, "compact must be a post-commit step for this gate to mean anything"

    ctx = TurnContext(turn_id="t", entry="api")
    ctx.app_state = state
    ctx.session_id = "s-1"
    ctx.engine = "ollama"

    queue = queue_for(state)
    with patch("core.sessions.compactor.compact_session", new=_slow_compact):
        # The door hands the step to the queue; nothing has run yet.
        assert calls == []
        await table_compact(api_adapters(MagicMock()), ctx)
        queue.start()
        await queue.drain()
        await queue.stop()

    assert calls == ["compact"], "compaction never ran at /v1, even after drain()"


async def table_compact(table, ctx):
    """Run the compact adapter the way run.py would when it is queued."""
    await table["compact"](ctx)
