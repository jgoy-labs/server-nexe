"""I8 (ADR-007 §6, C2.5): every LLM call of a turn, counted — measurement
only, no limit imposed yet (there is no data to size one against).

`record_llm_call` itself is a pure unit (its own tests below); the
integration test drives a REAL UI turn (the same `_Harness`/`_MemSaveEngine`
`test_turn_adapters_ui.py` already uses) and captures the finished
`TurnContext` off `emit_turn_trace` — the one place every door already
converges on a single `ctx` at the end of the turn, streaming or not.

Mutation (exercised by hand before merging, see the diari): removing the
`record_llm_call` call from `turn_adapters.py::generate_stream` turns both
turn tests below red (`generate` disappears from the counted steps).

#1061: the two turn tests bill against the fake engine's OWN call counter, not
against a number written here. Counting `memory.write` whenever a fact survived
billed an inference that never happened — a fact is only atomised when it holds
a conjunction, and this door may hold no engine at all.
"""
from __future__ import annotations

from unittest.mock import patch

import pytest

from core.turn.budget import record_llm_call
from core.turn.context import TurnContext
from tests.plugins.web_ui_module.test_chat_inner_behavior import _Harness, _make_server_state
from tests.plugins.web_ui_module.test_turn_adapters_ui import _MemSaveEngine

pytestmark = pytest.mark.asyncio


class TestRecordLlmCall:

    async def test_accumulates_calls_and_totals(self):
        ctx = TurnContext(turn_id="t", entry="test")
        record_llm_call(ctx, step="generate", engine="mlx", model="m1", ms=120.0)
        record_llm_call(ctx, step="memory.write", engine="mlx", ms=30.0, tokens_in=10, tokens_out=5)

        bucket = ctx.usage["llm"]
        assert bucket["total_calls"] == 2
        assert bucket["total_ms"] == pytest.approx(150.0)
        assert [c["step"] for c in bucket["calls"]] == ["generate", "memory.write"]
        assert bucket["calls"][1]["tokens_in"] == 10

    async def test_a_fresh_ctx_has_no_llm_bucket_until_the_first_call(self):
        ctx = TurnContext(turn_id="t", entry="test")
        assert "llm" not in ctx.usage
        record_llm_call(ctx, step="generate", engine="ollama", ms=1.0)
        assert "llm" in ctx.usage


class _SplittableMemSaveEngine:
    """Same shape as `_MemSaveEngine`, but the fact it marks holds a
    conjunction, so `atomize_fact_llm` really does come back for a second call.

    Counts its own calls: the tests compare the bill against THIS number, which
    is what makes them measure inferences instead of restating the fixture.
    """

    def __init__(self) -> None:
        self.calls = 0

    def chat(self, model, messages, stream=False, images=None, thinking_enabled=False, **_):
        self.calls += 1
        if self.calls == 1:
            return self._astream("Molt bé. [MEM_SAVE: es diu Aran i viu a Manresa]")
        # Every later call is the atomiser's: it answers one fact per line.
        return self._astream("es diu Aran\nviu a Manresa")

    async def _astream(self, text: str):
        yield {"message": {"content": text}}

    async def is_model_loaded(self, model_name):
        return True


async def _turn_with_fact(engine) -> TurnContext:
    """Drive one real streaming UI turn that writes a fact, and return the
    finished context. The opening turn stores nothing (C3.3's first-turn
    guard), hence the two messages seeded first."""
    captured: list[TurnContext] = []
    with patch("core.turn.run.emit_turn_trace", side_effect=lambda ctx, **_: captured.append(ctx)):
        h = _Harness(intent="chat")
        h.session.add_message("user", "hola")
        h.session.add_message("assistant", "hey")
        result = await h.call(
            {"message": "em dic Aran", "stream": True},
            server_state=_make_server_state(engine=engine),
        )
        async for _ in result.body_iterator:
            pass

    assert captured, "emit_turn_trace was never called — the turn did not finish"
    return captured[-1]


async def test_a_fact_that_costs_no_inference_is_not_billed_as_one():
    """#1061: "es diu Aran" holds no conjunction, so the atomiser hands it back
    without ever reaching the engine. The turn spent ONE call — `generate` — and
    the bill has to say one. Before this, `memory.write` was counted whenever a
    fact survived the filters, which is a different question entirely."""
    engine = _MemSaveEngine()
    ctx = await _turn_with_fact(engine)

    bucket = ctx.usage["llm"]
    assert [c["step"] for c in bucket["calls"]] == ["generate"]
    assert bucket["total_calls"] == 1
    assert ctx.facts, "the fact was still stored — this is about the bill, not the write"


async def test_a_fact_the_atomiser_splits_is_billed():
    """The other half, and the one that stops the fix from being "never count
    memory.write": a fact WITH a conjunction does reach the engine a second
    time, and that call is on the bill. The engine's own counter is the source
    of truth — the assertion compares against it, not against a literal."""
    engine = _SplittableMemSaveEngine()
    ctx = await _turn_with_fact(engine)

    bucket = ctx.usage["llm"]
    assert engine.calls == 2, "the atomiser never reached the engine — nothing to bill"
    assert [c["step"] for c in bucket["calls"]] == ["generate", "memory.write"]
    assert bucket["total_calls"] == engine.calls
    assert all(c["ms"] >= 0 for c in bucket["calls"])


async def test_the_bill_names_the_model_that_answered_at_v1(turn_lab):
    """#1054: the UI door has always recorded `model=ui["model_name"]` here and
    /v1 recorded nothing, so every API turn in the trace read `model: null`.
    Only the engine hop is faked: the real door, the real `run_turn`, the real
    cascade.

    Mutation guard: drop `model=served_model` from `record_llm_call` in
    `adapters_api.py::generate` and this goes red — `None` instead of the name.
    """
    from core.endpoints.chat_engines._common import build_openai_response

    reply = build_openai_response({"response": "hola"}, "gemma-4-e4b-it-4bit", "mlx")

    async def _dispatch(*_args, **_kwargs):
        return reply

    with patch("core.endpoints.chat._dispatch_to_engine", _dispatch):
        ctx = await turn_lab.api(session_id="s-model-name")

    calls = ctx.usage["llm"]["calls"]
    assert [c["step"] for c in calls] == ["generate"]
    assert calls[0]["engine"] == "ollama", "the engine that answered, as before"
    assert calls[0]["model"] == "gemma-4-e4b-it-4bit", "and now the model it loaded"
