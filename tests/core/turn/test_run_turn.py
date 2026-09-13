"""C1.1 (ADR-007, the pipeline plan): the engine, alone.

Every adapter here is a fake: a coroutine (or async generator) that appends its
step id to `ctx.usage["trace"]` and does nothing else, unless a test swaps one
in that raises, short-circuits or writes a field. No route, no engine, no
plugin is touched — this proves the ENGINE's policy, which is what C1.1 is.

Mutation checks (exercised by hand before merging C1.1, see the diari):
  * drop the `finally` that commits the partial answer in `stream_turn` →
    `test_stream_turn_commits_partial_answer_when_client_disconnects` is red;
  * skip `_mark_skipped` after a short-circuit → `..._skips_to_persist_and_emit`
    is red on the outcomes.
"""
from __future__ import annotations

import pytest

from core.turn.context import TurnContext
from core.turn.run import (
    AFTER_CANCEL,
    AFTER_SHORT_CIRCUIT,
    MissingAdapters,
    TurnShortCircuit,
    run_turn,
    stream_turn,
)
from core.turn.steps import TURN_STEPS

ALL_IDS = tuple(step.id for step in TURN_STEPS)
BEFORE_GENERATE = ALL_IDS[: ALL_IDS.index("generate")]
FROM_GENERATE = ALL_IDS[ALL_IDS.index("generate"):]


def _ctx() -> TurnContext:
    return TurnContext(turn_id="t-1", entry="test", message="hola")


def _tracer(step_id: str):
    async def adapter(ctx: TurnContext) -> None:
        ctx.usage.setdefault("trace", []).append(step_id)
    adapter.__name__ = f"fake_{step_id}"
    return adapter


def _fake_adapters(**overrides):
    table = {step_id: _tracer(step_id) for step_id in ALL_IDS}
    table.update(overrides)
    return table


def _streaming_generate(chunks):
    async def generate(ctx: TurnContext):
        ctx.usage.setdefault("trace", []).append("generate")
        for chunk in chunks:
            ctx.response += chunk
            yield chunk
    return generate


# ---------------------------------------------------------------- run_turn


async def test_run_turn_runs_every_step_in_the_frozen_order():
    ctx = await run_turn(_ctx(), _fake_adapters())
    assert tuple(ctx.usage["trace"]) == ALL_IDS
    assert all(ctx.outcomes[i] == "ok" for i in ALL_IDS)
    assert ctx.streaming is False


async def test_a_write_is_visible_to_the_next_step():
    seen = {}

    async def clock(ctx):
        ctx.clock_line = "[Hora: 05:31]"

    async def system_prompt(ctx):
        seen["clock_line"] = ctx.clock_line

    await run_turn(_ctx(), _fake_adapters(clock=clock, system_prompt=system_prompt))
    assert seen["clock_line"] == "[Hora: 05:31]"


async def test_must_have_failure_stops_the_turn_and_reraises_the_original():
    boom = ValueError("bad input")

    async def sanitize(ctx):
        raise boom

    ctx = _ctx()
    with pytest.raises(ValueError) as excinfo:
        await run_turn(ctx, _fake_adapters(sanitize=sanitize))
    assert excinfo.value is boom  # untouched, not wrapped
    assert ctx.outcomes["sanitize"] == "failed"
    assert ctx.usage["trace"] == ["validate", "authorize"]  # nothing after
    assert "session" not in ctx.outcomes


async def test_optional_failure_degrades_and_the_turn_goes_on():
    async def recall(ctx):
        raise RuntimeError("qdrant down")

    ctx = await run_turn(_ctx(), _fake_adapters(recall=recall))
    assert ctx.outcomes["recall"] == "degraded"
    assert ctx.degradations == [{"step": "recall", "error": "RuntimeError: qdrant down"}]
    assert ctx.usage["trace"][-1] == "compact"  # ran to the end
    assert ctx.outcomes["compact"] == "ok"


async def test_short_circuit_skips_to_persist_and_emit():
    async def intent(ctx):
        raise TurnShortCircuit("Tens 3 records.", reason="memory_intent:list")

    ctx = await run_turn(_ctx(), _fake_adapters(intent=intent))
    assert ctx.response == "Tens 3 records."
    assert ctx.outcomes["intent"] == "short_circuit"
    after = ctx.usage["trace"][ctx.usage["trace"].index("persist_user_turn") + 1:]
    assert after == ["persist_assistant_turn", "emit"]
    for step_id in ("recall", "clock", "system_prompt", "budget", "engine", "generate",
                    "postprocess", "memory.write", "compact"):
        assert ctx.outcomes[step_id] == "skipped", step_id
    assert AFTER_SHORT_CIRCUIT == {"persist_assistant_turn", "emit"}


async def test_missing_adapter_is_refused_before_any_step_runs():
    table = _fake_adapters()
    del table["budget"]
    ctx = _ctx()
    with pytest.raises(MissingAdapters) as excinfo:
        await run_turn(ctx, table)
    assert excinfo.value.missing == ("budget",)
    assert "trace" not in ctx.usage


async def test_run_turn_refuses_generator_adapters():
    with pytest.raises(TypeError):
        await run_turn(_ctx(), _fake_adapters(generate=_streaming_generate(["a"])))


async def test_every_executed_step_leaves_a_timing():
    ctx = await run_turn(_ctx(), _fake_adapters())
    for step_id in ALL_IDS:
        entry = ctx.usage["steps"][step_id]
        assert entry["ms"] >= 0.0
        assert entry["outcome"] == "ok"
        assert entry["kind"] in ("compute", "llm")


# ------------------------------------------------------------- stream_turn


async def test_stream_turn_runs_the_prefix_once_and_yields_the_body():
    ctx = _ctx()
    body = await stream_turn(ctx, _fake_adapters(generate=_streaming_generate(["Ho", "la", "!"])))
    # the prefix has already run, before a single chunk is consumed
    assert tuple(ctx.usage["trace"]) == BEFORE_GENERATE
    assert ctx.streaming is True
    chunks = [c async for c in body]
    assert chunks == ["Ho", "la", "!"]
    assert ctx.response == "Hola!"
    assert tuple(ctx.usage["trace"]) == ALL_IDS  # each step exactly once
    assert ctx.outcomes["generate"] == "ok"
    assert ctx.outcomes["compact"] == "ok"


async def test_stream_turn_prefix_failure_raises_before_the_body_exists():
    async def validate(ctx):
        raise ValueError("400 material")

    ctx = _ctx()
    with pytest.raises(ValueError):
        await stream_turn(ctx, _fake_adapters(validate=validate, generate=_streaming_generate(["x"])))
    assert ctx.outcomes["validate"] == "failed"
    assert "generate" not in ctx.outcomes


async def test_stream_turn_commits_partial_answer_when_client_disconnects():
    ctx = _ctx()
    body = await stream_turn(ctx, _fake_adapters(generate=_streaming_generate(["Ho", "la", "!"])))
    first = await body.__anext__()
    assert first == "Ho"
    await body.aclose()  # the client went away
    assert ctx.outcomes["generate"] == "cancelled"
    assert ctx.response == "Ho"  # what was generated so far
    assert ctx.outcomes["persist_assistant_turn"] == "ok"  # committed
    for step_id in ("postprocess", "emit", "memory.write", "compact"):
        assert ctx.outcomes[step_id] == "skipped", step_id  # no LLM call, no memory write
    assert AFTER_CANCEL == {"persist_assistant_turn"}


async def test_stream_turn_short_circuit_in_prefix_yields_only_emit():
    async def intent(ctx):
        raise TurnShortCircuit("Fet: 2 records esborrats.")

    async def emit(ctx):
        ctx.usage.setdefault("trace", []).append("emit")
        yield ctx.response

    ctx = _ctx()
    body = await stream_turn(ctx, _fake_adapters(intent=intent, emit=emit, generate=_streaming_generate(["never"])))
    chunks = [c async for c in body]
    assert chunks == ["Fet: 2 records esborrats."]
    assert ctx.outcomes["generate"] == "skipped"
    assert ctx.outcomes["persist_assistant_turn"] == "ok"
    assert ctx.usage["trace"][-2:] == ["persist_assistant_turn", "emit"]


async def test_stream_turn_generator_adapters_after_generate_yield_too():
    async def memory_write(ctx):
        ctx.usage.setdefault("trace", []).append("memory.write")
        yield "\x00[MEM:1]\x00"

    ctx = _ctx()
    body = await stream_turn(ctx, _fake_adapters(**{"generate": _streaming_generate(["Hola"]), "memory.write": memory_write}))
    chunks = [c async for c in body]
    assert chunks == ["Hola", "\x00[MEM:1]\x00"]
    # order on the wire follows TURN_STEPS: the sentinel comes after persist
    trace = ctx.usage["trace"]
    assert trace.index("persist_assistant_turn") < trace.index("memory.write")


async def test_stream_turn_refuses_a_generator_before_the_boundary():
    async def recall(ctx):
        yield "too early"

    with pytest.raises(TypeError):
        await stream_turn(_ctx(), _fake_adapters(recall=recall, generate=_streaming_generate(["x"])))
