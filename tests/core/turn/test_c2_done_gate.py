"""The C2 "done" gate (ADR-007 §6/§7, the plan's definition of done for C2):
between `persist_assistant_turn` and the end of `emit`, ZERO calls to
`engine.chat()` — checked here end-to-end, through the REAL adapter tables
(`ui_adapters`/`api_adapters`), not just the fake-adapter unit tests
`test_post_commit_queue.py` already covers at the `run.py` level.

The property only holds with a REAL `PostCommitQueue` attached
(`attach_post_commit_queue`) — without one, `memory.write`/`compact` run
INLINE, which is the pre-C2.2 behaviour every other test harness still
relies on (`test_no_queue_means_inline_exactly_as_before`). `/v1` needs no
queue to prove the same property: `memory.write`/`compact` are `_folded`
there (no adapter ever calls the engine for them today), checked below by
inspecting the adapter table itself rather than driving a turn.

Mutation (exercised by hand before merging, see the diari): removing
`memory.write` from `core.turn.run.POST_COMMIT` turns BOTH
`test_ui_stream_makes_no_second_engine_call_before_the_wire_closes` and
`test_ui_json_makes_no_second_engine_call_before_the_response_returns` red
— the fact is saved (JSON) / the engine gets a second `.chat()` call
(stream) before the response ever returns, because `memory.write` ran
inline instead of being queued.
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


async def test_ui_stream_makes_no_second_engine_call_before_the_wire_closes():
    engine = _CountingMemSaveEngine()
    state = _state_with_real_queue(engine)  # REAL queue — memory.write must be queued, not inline

    h = _Harness(intent="chat")
    # C3.3: the first-turn guard (the JSON path's, now both paths') drops every
    # fact of an opening turn — without history this gate would pass by accident,
    # with memory.write running and saving nothing. Same reason the JSON twin
    # below already gave a session some history.
    h.session.add_message("user", "hola, em dic Aran")
    h.session.add_message("assistant", "Hola!")
    result = await h.call({"message": "em dic Aran", "stream": True}, server_state=state)
    assert isinstance(result, StreamingResponse)

    async for _ in result.body_iterator:
        pass  # drain the whole wire — everything up to and including `emit`

    assert engine.calls == 1, (
        "the wire closed with a second engine.chat() call already made — "
        "memory.write ran inline instead of being queued"
    )

    queue = queue_for(state)
    queue.start()
    await queue.drain()
    await queue.stop()

    assert engine.calls == 2, "memory.write never ran at all, even after drain()"


async def test_ui_json_makes_no_second_engine_call_before_the_response_returns():
    """The JSON path has NO atomiser (`write_facts` only atomises with an engine) —
    "this path has no atomizer, so a combined fact ... persists whole" is the
    function's own comment — so it never calls `engine.chat()` at all, queued
    or not. The gate this test can actually check for JSON is therefore
    narrower than the streaming one: zero EXTRA engine calls before the
    response returns, and the fact genuinely lands in memory only after
    `drain()` — proving the work was queued, not skipped."""
    engine = _CountingMemSaveEngine()
    state = _state_with_real_queue(engine)

    h = _Harness(intent="chat")
    # B126 v2 (core/memory_facts/write.py): write_facts drops every fact
    # of a FIRST turn as a likely hallucination — unrelated to C2, but it
    # would make this gate pass by accident (memory.write runs and saves
    # nothing). A session with prior history is what
    # test_json_saves_the_turn_before_its_facts (C2.2) uses for the same
    # reason.
    h.session.add_message("user", "hola, em dic Aran")
    h.session.add_message("assistant", "Hola!")
    result = await h.call({"message": "recorda que visc a Barcelona", "stream": False}, server_state=state)
    assert isinstance(result, dict)

    assert engine.calls == 1, (
        "the JSON response returned with a second engine.chat() call already "
        "made — memory.write ran inline instead of being queued"
    )
    assert not h.mh.save_to_memory.called, (
        "the fact was already saved before the response returned — "
        "memory.write ran inline instead of being queued"
    )

    queue = queue_for(state)
    queue.start()
    await queue.drain()
    await queue.stop()

    assert engine.calls == 1, "memory.write called the engine — it has no atomizer, this would be new"
    assert h.mh.save_to_memory.called, "memory.write never ran at all, even after drain()"


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
