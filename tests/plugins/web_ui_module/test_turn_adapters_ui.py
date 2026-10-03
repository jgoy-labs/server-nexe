"""C1.3 (ADR-007): the web UI door walks TURN_STEPS through the turn engine.

What the 26 existing UI test files cannot say, because they never needed to:

* I3, by behaviour, at this door: the user's turn reaches disk BEFORE retrieval
  touches memory, and (decision of 06/09/2026) the assistant's turn reaches
  disk BEFORE the turn's facts go to memory — in both wire formats.
* The two adapter tables are complete and honest: every step has an adapter,
  the streaming one yields where the wire needs it, and the steps whose
  behaviour is folded into another function say where.

Mutation (exercised by hand before merging, see the diari): swapping the
streaming `persist_assistant_turn` and `memory.write` adapters back to today's
order turns `test_stream_saves_the_turn_before_its_facts` red.

C3 review (08/09), same file: dropping `saved_by_intent=` from the `write_facts`
call in `turn_adapters.memory_write` turns both
`test_json_d6_turn_stores_the_literal_once_not_the_paraphrase` and its stream
twin red — the fact the model repeats is saved a second time, paraphrased.
"""
from __future__ import annotations

import inspect
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi.responses import StreamingResponse

from core.turn.context import TurnContext
from core.turn.folded import FOLDED_BASELINE
from core.turn.steps import TURN_STEPS
from plugins.web_ui_module.api.turn_adapters import ui_adapters
from tests.plugins.web_ui_module.test_chat_inner_behavior import (
    _Harness,
    _make_server_state,
)

pytestmark = pytest.mark.asyncio

# C3.3: memory.write left this set — it is a coroutine at both doors now,
# because on the post-commit queue there is no wire to yield into.
STREAM_STEPS = {"generate", "postprocess", "emit"}

#: Nothing is folded at this door since C4.2. `compact` left the set at C2.2,
#: `authorize`/`sanitize` at C4.1, `system_prompt` was already real here, and
#: `recall`/`clock` left at C4.2 — retrieval was folded inside
#: `_build_turn_context` and the on-demand clock inside
#: `_assemble_engine_messages`, both of which `budget` called.
FOLDED_AT_THIS_DOOR: tuple[str, ...] = ()


class _MemSaveEngine:
    """Ollama-shaped engine whose answer carries a fact to remember."""

    def chat(self, model, messages, stream=False, images=None, thinking_enabled=False, **_):
        if stream:
            return self._astream()
        return {"message": {"content": "Encantat, Aran. [MEM_SAVE: es diu Aran]"}, "done": True}

    async def _astream(self):
        yield {"message": {"content": "Encantat, Aran. "}}
        yield {"message": {"content": "[MEM_SAVE: es diu Aran]"}}

    async def is_model_loaded(self, model_name):
        return True


class _ParrotEngine:
    """The behaviour every model showed in the 08/09 live test: after D6 has
    already saved "recorda que el meu peix es diu Bombolla", the model answers
    AND marks its own paraphrase of the same fact.

    The paraphrase deliberately does not quote the user's message: the echo
    guard (`extract.py`) drops a literal echo, and this test is about the guard
    that comes after it.
    """

    PARAPHRASE = "[MEM_SAVE: L'usuari té un peix que es diu Bombolla]"

    def chat(self, model, messages, stream=False, images=None, thinking_enabled=False, **_):
        if stream:
            return self._astream()
        return {"message": {"content": f"D'acord. {self.PARAPHRASE}"}, "done": True}

    async def _astream(self):
        yield {"message": {"content": "D'acord. "}}
        yield {"message": {"content": self.PARAPHRASE}}

    async def is_model_loaded(self, model_name):
        return True


def _d6_harness() -> _Harness:
    """A conversation (not an opening turn) whose next message is a D6 save."""
    h = _Harness(intent="save", mem_content="el meu peix es diu Bombolla")
    h.session.add_message("user", "hola")
    h.session.add_message("assistant", "hey")
    return h


def _ordered(h: _Harness) -> list[str]:
    """Spy the two writers the invariant is about; return the shared log."""
    order: list[str] = []
    h.session_mgr._save_session_to_disk = MagicMock(side_effect=lambda *_: order.append("disk"))
    h.mh.save_to_memory = AsyncMock(side_effect=lambda *a, **k: order.append("memory") or {"success": True, "document_id": "d"})
    return order


class _NoDocSession:
    """A session with nothing attached: what `recall` asks before retrieving."""

    rag_collections = None

    def has_attached_document(self) -> bool:
        return False


async def test_adapter_tables_cover_every_step():
    for streaming in (False, True):
        table = ui_adapters(MagicMock(), streaming=streaming)
        assert set(table) == {step.id for step in TURN_STEPS}
        for step_id, adapter in table.items():
            if streaming and step_id in STREAM_STEPS:
                assert inspect.isasyncgenfunction(adapter), (streaming, step_id)
            else:
                assert inspect.iscoroutinefunction(adapter), (streaming, step_id)


async def test_no_step_is_folded_at_this_door():
    """C4.2: every step of the table does its own work.

    Run, not looped over: an assertion about an empty list is an assertion
    about nothing, and would stay green the day a step is folded again.
    """
    assert len(FOLDED_AT_THIS_DOOR) == FOLDED_BASELINE["ui"] == 0, (
        "this door's folded list and core/turn/folded.py disagree"
    )
    table = ui_adapters(MagicMock(), streaming=False)

    async def _no_rag(_message, **_kwargs):
        return "", 0, []

    with patch("plugins.web_ui_module.api.turn_adapters._build_rag_context", new=_no_rag):
        for step_id in ("authorize", "sanitize", "recall", "clock", "system_prompt"):
            ctx = TurnContext(
                turn_id="t", entry="ui", principal="a-real-key", lang="ca",
                message="hola", body={"message": "hola"}, session=_NoDocSession(),
            )
            await table[step_id](ctx)
            assert step_id not in ctx.usage.get("folded", {}), (
                f"{step_id} is folded again at /ui/chat"
            )


async def test_the_two_steps_c42_unfolded_do_their_work():
    """`recall` fills the turn's retrieval and `clock` its time line. A step
    that returned early would leave the turn as empty as a folded one did."""
    table = ui_adapters(MagicMock(), streaming=False)

    async def _found(_message, **_kwargs):
        return "un fet recuperat", 1, [("personal_memory", 0.9)]

    ctx = TurnContext(
        turn_id="t", entry="ui", lang="ca", message="quina hora és?",
        body={"message": "quina hora és?"}, session=_NoDocSession(),
    )
    with patch("plugins.web_ui_module.api.turn_adapters._build_rag_context", new=_found):
        await table["recall"](ctx)
    await table["clock"](ctx)

    assert ctx.recall_text == "un fet recuperat"
    assert ctx.recall == [("personal_memory", 0.9)]
    assert ctx.usage["ui"]["rag_count"] == 1
    # #1125: the time the message was sent, every turn — not only when asked.
    assert ctx.clock_line.startswith("[Hora del missatge: ")


async def test_user_turn_is_on_disk_before_memory_is_asked_json():
    h = _Harness(intent="chat")
    order = _ordered(h)

    async def fake_rag(*args, **kwargs):
        order.append("recall")
        return "", []

    with patch("core.endpoints.chat_rag.build_rag_context", new=fake_rag):
        result = await h.call({"message": "hola", "stream": False}, server_state=_make_server_state())
    assert isinstance(result, dict) and result["response"]
    assert order[0] == "disk", order
    assert "recall" in order and order.index("disk") < order.index("recall"), order


async def test_json_saves_the_turn_before_its_facts():
    """The JSON path, on a conversation that is NOT its first turn.

    `write_facts` drops every fact of a first turn as a likely
    hallucination (B126 v2, routes_chat.py) — a guard the streaming path does
    not have, one of the divergences measured on 2026-09-05. C1.3 preserves
    both behaviours as they are; what this pins is the ORDER, which is what
    changed: disk, then memory.
    """
    h = _Harness(intent="chat")
    h.session.add_message("user", "hola, em dic Aran")
    h.session.add_message("assistant", "Hola!")
    order = _ordered(h)
    result = await h.call({"message": "recorda com em dic", "stream": False},
                          server_state=_make_server_state(engine=_MemSaveEngine()))
    assert result["memory_action"] == "mem_save_inline"
    assert "[MEM_SAVE" not in result["response"]
    # the new user turn to disk, the assistant turn to disk, THEN the fact
    assert "memory" in order, order
    assert order.index("memory") > order.index("disk"), order
    # The only disk write after "memory" is the stats update (mem_saved), so
    # the sequence still ends the way it did before C3.3: nothing but that.
    assert order[order.index("memory") + 1:] == ["disk"], order


async def test_json_first_turn_keeps_a_fact_in_the_users_words():
    """25/09 (Jordi): an opening "em dic Aran" is the user's own word, so the
    model's `[MEM_SAVE: es diu Aran]` is kept — and the reply says so itself.
    Until then every opening-turn fact was dropped (the JSON path's old guard,
    extended to both doors by C3.3)."""
    h = _Harness(intent="chat")
    order = _ordered(h)
    result = await h.call({"message": "em dic Aran", "stream": False},
                          server_state=_make_server_state(engine=_MemSaveEngine()))
    assert "memory" in order, order
    assert result["memory_facts"] == ["es diu Aran"]


async def test_stream_saves_the_turn_before_its_facts():
    h = _Harness(intent="chat")
    # C3.3: the first-turn guard (the JSON path's, now both paths') drops every
    # fact of an opening turn, so this gate needs a conversation to measure the
    # order of a real save — the JSON twin below already worked this way.
    h.session.add_message("user", "hola")
    h.session.add_message("assistant", "hey")
    order = _ordered(h)
    result = await h.call({"message": "em dic Aran", "stream": True},
                          server_state=_make_server_state(engine=_MemSaveEngine()))
    assert isinstance(result, StreamingResponse)
    body = ""
    async for chunk in result.body_iterator:
        body += chunk if isinstance(chunk, str) else chunk.decode()
    # 25/09 (#1098): memory.write runs inline before `emit`, so THIS turn's
    # wire says what memory kept — the fact itself, after the answer.
    assert "\x00[MEM:1:es diu Aran]\x00" in body
    assert body.index("Encantat, Aran.") < body.index("\x00[MEM:1:"), body
    # the assistant turn is on disk before the fact reaches memory; the stats
    # of that turn are then completed with the count (a second save)
    assert order.index("memory") > order.index("disk"), order
    # the two seeded turns plus this one
    assert [m["role"] for m in h.session.messages] == ["user", "assistant", "user", "assistant"]
    assert h.session.messages[-1]["stats"]["mem_saved"] == 1


# ═══════════════════════════════════════════════════════════════
# C3 review (08/09): a D6 turn owns its fact — the model repeating
# it must not become a second, paraphrased entry
# ═══════════════════════════════════════════════════════════════

async def test_json_d6_turn_stores_the_literal_once_not_the_paraphrase(caplog):
    """Live-tested on 08/09 with a 4B and a 27B model: both parrot the tag.
    The literal the user asked for is saved by `intent`; the model's paraphrase
    of the same fact is dropped by `memory.write`.
    """
    import logging

    h = _d6_harness()
    with caplog.at_level(logging.INFO):
        result = await h.call(
            {"message": "Recorda que el meu peix es diu Bombolla", "stream": False},
            server_state=_make_server_state(engine=_ParrotEngine()),
        )

    assert h.mh.save_to_memory.await_count == 1, (
        "the model's paraphrase was written as a second entry for the same fact"
    )
    assert h.mh.save_to_memory.await_args.kwargs["content"] == "el meu peix es diu Bombolla"
    assert result["memory_saved"] == 1
    assert result["memory_action"] == "save"
    assert "[MEM_SAVE" not in result["response"]
    assert any("intent step already saved" in r.getMessage() for r in caplog.records)


async def test_stream_d6_turn_stores_the_literal_once_not_the_paraphrase(caplog):
    """The stream twin: same turn, the other wire format, same one entry."""
    import logging

    h = _d6_harness()
    with caplog.at_level(logging.INFO):
        result = await h.call(
            {"message": "Recorda que el meu peix es diu Bombolla", "stream": True},
            server_state=_make_server_state(engine=_ParrotEngine()),
        )
        assert isinstance(result, StreamingResponse)
        body = ""
        async for chunk in result.body_iterator:
            body += chunk if isinstance(chunk, str) else chunk.decode()

    assert h.mh.save_to_memory.await_count == 1
    assert h.mh.save_to_memory.await_args.kwargs["content"] == "el meu peix es diu Bombolla"
    # NOT asserted: that the raw tag is absent from the stream. It passes
    # through by design at this door — `nexe-chat.js:345` says so and strips it
    # at final render (:824), and the sentinel FSM that would strip it live is
    # C4's job. Pinning it here would be pinning a limit as if it were a
    # guarantee (any non-browser client of /ui/chat still sees it — separate
    # fitxa).
    # D6's own save is what the user is told about, in this turn's stream —
    # the literal it stored, once (no second [MEM] for the dropped paraphrase).
    assert "\x00[MEM:1:el meu peix es diu Bombolla]\x00" in body
    assert body.count("\x00[MEM:") == 1, body
    # Nothing else was written, so the assistant turn's stats stay untouched.
    assert h.session.messages[-1].get("stats", {}).get("mem_saved") in (None, 0)
    assert any("intent step already saved" in r.getMessage() for r in caplog.records)


async def test_a_plain_turn_still_stores_the_models_fact():
    """The control: with no D6 save the model's tag is a normal save, and the
    guard must not swallow it.

    Mutation guard: make the `saved_by_intent` check in `write_facts`
    unconditional and this goes RED — nothing is ever saved from a model tag.
    """
    h = _Harness(intent="chat")
    h.session.add_message("user", "hola")
    h.session.add_message("assistant", "hey")

    await h.call({"message": "el meu peix es diu Bombolla", "stream": False},
                 server_state=_make_server_state(engine=_ParrotEngine()))

    assert h.mh.save_to_memory.await_count == 1
    assert h.mh.save_to_memory.await_args.kwargs["content"] == (
        "L'usuari té un peix que es diu Bombolla"
    )


async def test_a_recall_turn_still_stores_the_models_fact():
    """A recall sets `memory_action` without saving anything, so the flag must
    not be read off `memory_action`.

    Mutation guard: derive the signal from `bool(outcome.memory_action)` and
    this goes RED — the model's fact is dropped on a recall turn.
    """
    h = _Harness(intent="recall", mem_content="què saps de mi")
    # The name in the model's fact has to appear in the user's own words or the
    # name guard (B126 v2) drops it for an unrelated reason and this would pass
    # without exercising anything.
    h.session.add_message("user", "el meu peix es diu Bombolla")
    h.session.add_message("assistant", "hey")

    result = await h.call({"message": "què saps de mi", "stream": False},
                          server_state=_make_server_state(engine=_ParrotEngine()))

    assert result["memory_action"] == "recall"
    assert h.mh.save_to_memory.await_count == 1
    assert h.mh.save_to_memory.await_args.kwargs["content"] == (
        "L'usuari té un peix que es diu Bombolla"
    )


async def test_a_dedup_refused_d6_save_still_blocks_the_paraphrase():
    """A refused duplicate means the fact IS already in memory — so the model's
    paraphrase of it must be dropped just the same.

    Mutation guard: derive the signal from `outcome.mem_saved > 0` and this
    goes RED — the paraphrase slips in as a near-duplicate, which is exactly
    what the 0.80 dedup cannot catch.
    """
    h = _d6_harness()
    h.mh.save_to_memory = AsyncMock(return_value={
        "success": False, "duplicate": True, "document_id": None,
    })

    result = await h.call(
        {"message": "Recorda que el meu peix es diu Bombolla", "stream": False},
        server_state=_make_server_state(engine=_ParrotEngine()),
    )

    assert h.mh.save_to_memory.await_count == 1
    assert result["memory_saved"] == 0


class _CrashMidStreamEngine:
    """Ollama-shaped engine whose stream crashes after two chunks (#1040)."""

    def chat(self, model, messages, stream=False, images=None, thinking_enabled=False, **_):
        if stream:
            return self._astream()
        return {"message": {"content": "won't be used"}, "done": True}

    async def _astream(self):
        yield {"message": {"content": "Hola, "}}
        yield {"message": {"content": "com "}}
        raise RuntimeError("engine crashed mid-stream")

    async def is_model_loaded(self, model_name):
        return True


async def test_error_mid_stream_persists_a_partial_turn():
    """#1040 (C2.4): an engine error mid-stream (client still connected, some
    tokens already on the wire) is a DIFFERENT broken-turn case from a client
    disconnect, but gets the SAME treatment: the partial reply is persisted,
    never as if it were the complete answer.

    `post_commit=None` here (no PostCommitQueue attached to this harness's
    server_state — `queue_for` only returns a real one when it finds an
    ISINSTANCE of PostCommitQueue, see its own docstring) means memory.write
    still runs inline exactly as every pre-C2.2 caller does — the "a partial
    turn's memory.write is SKIPPED rather than queued" half of #1040 only
    applies when a real queue is attached, and is covered at the run.py level
    in test_post_commit_queue.py::test_partial_turn_queues_no_memory_write_but_still_queues_compact.
    """
    h = _Harness(intent="chat")
    result = await h.call({"message": "hola", "stream": True},
                          server_state=_make_server_state(engine=_CrashMidStreamEngine()))
    assert isinstance(result, StreamingResponse)
    body = ""
    async for chunk in result.body_iterator:
        body += chunk if isinstance(chunk, str) else chunk.decode()
    assert "Hola, " in body and "com " in body
    assert "⚠️" in body, "the curated error notice reached the wire"
    assert [m["role"] for m in h.session.messages] == ["user", "assistant"]
    assert h.session.messages[-1]["stats"]["interrupted"] is True, (
        "a mid-stream error persists through the SAME partial-turn path as a "
        "client disconnect (MC-116), never as a complete answer"
    )


async def test_memory_command_short_circuits_and_streams_char_by_char():
    h = _Harness(intent="list")
    result = await h.call({"message": "què saps de mi?", "stream": True},
                          server_state=_make_server_state())
    assert isinstance(result, StreamingResponse)
    chunks = [c async for c in result.body_iterator]
    assert all(len(c) == 1 for c in chunks), "a memory command's answer streams one character at a time"
    text = "".join(chunks)
    assert text
    assert [m["role"] for m in h.session.messages] == ["user", "assistant"]
    assert h.session.messages[-1]["content"] == text


# ═══════════════════════════════════════════════════════════════
# C3.1 / D6 — the "saved" note rides with the answer, not instead of it
# ═══════════════════════════════════════════════════════════════

async def test_stream_emits_the_saved_note_after_the_answer():
    """D6: a save no longer answers the turn, so the only thing that tells the
    user their fact was stored is this sentinel. Without it the feature is
    silent — the decision of 06/09 was wired but never actually sent."""
    from plugins.web_ui_module.api.turn_adapters import ui_adapters

    table = ui_adapters(MagicMock(), streaming=True)
    ctx = TurnContext(turn_id="t", entry="ui")
    ctx.session_id = "s-1"
    ctx.response = "El teu gat es diu Mite, doncs!"
    ctx.usage["memory_saved"] = 1
    stream_ctx = MagicMock()
    stream_ctx.session.needs_compaction.return_value = False
    ctx.usage.setdefault("ui", {})["stream_ctx"] = stream_ctx

    chunks = [c async for c in table["emit"](ctx)]

    assert "\x00[MEM:1]\x00" in chunks, f"the saved note never reached the wire: {chunks}"


async def test_stream_says_nothing_when_nothing_was_saved():
    from plugins.web_ui_module.api.turn_adapters import ui_adapters

    table = ui_adapters(MagicMock(), streaming=True)
    ctx = TurnContext(turn_id="t", entry="ui")
    ctx.session_id = "s-1"
    ctx.response = "Hola!"
    stream_ctx = MagicMock()
    stream_ctx.session.needs_compaction.return_value = False
    ctx.usage.setdefault("ui", {})["stream_ctx"] = stream_ctx

    chunks = [c async for c in table["emit"](ctx)]

    assert not any("[MEM:" in c for c in chunks)
