"""C2.0 (ADR-007, the pipeline plan): the GPS becomes readable.

`run_turn`/`stream_turn` already leave `ctx.outcomes` and `ctx.usage["steps"]`
per step (C1 §4) — this is the sink: exactly one `turn.trace` log line per
finished turn, sourced from those two fields. Fake adapters as in
`test_run_turn.py`; no route, no engine, no plugin is touched.

Mutation check (exercised by hand before merging C2.0, see the diari): drop
the `emit_turn_trace(ctx)` call from `stream_turn`'s `finally` →
`test_a_cancelled_stream_still_emits_exactly_one_trace_line` goes red (zero
lines instead of one).
"""
from __future__ import annotations

import json
import logging

import pytest

from core.turn.context import TurnContext
from core.turn.post_commit import queue_for
from core.turn.run import run_turn, stream_turn
from core.turn.steps import TURN_STEPS
from tests.core.turn.test_c2_done_gate import _CountingMemSaveEngine, _state_with_real_queue
from tests.plugins.web_ui_module.test_chat_inner_behavior import _Harness

pytestmark = pytest.mark.asyncio

ALL_IDS = tuple(step.id for step in TURN_STEPS)
TRACE_LOGGER = "nexe.turn.trace"


def _ctx(**kwargs) -> TurnContext:
    kwargs.setdefault("turn_id", "t-trace-1")
    kwargs.setdefault("entry", "test")
    kwargs.setdefault("message", "hola")
    return TurnContext(**kwargs)


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


def _trace_records(caplog):
    return [r for r in caplog.records if r.name == TRACE_LOGGER and r.message.startswith("turn.trace ")]


async def test_run_turn_emits_exactly_one_trace_line(caplog):
    caplog.set_level(logging.INFO, logger=TRACE_LOGGER)
    await run_turn(_ctx(), _fake_adapters())
    assert len(_trace_records(caplog)) == 1


async def test_stream_turn_emits_exactly_one_trace_line_when_consumed_to_completion(caplog):
    caplog.set_level(logging.INFO, logger=TRACE_LOGGER)
    ctx = _ctx()
    body = await stream_turn(ctx, _fake_adapters(generate=_streaming_generate(["a", "b"])))
    assert [c async for c in body] == ["a", "b"]
    assert len(_trace_records(caplog)) == 1


async def test_a_cancelled_stream_still_emits_exactly_one_trace_line(caplog):
    caplog.set_level(logging.INFO, logger=TRACE_LOGGER)
    ctx = _ctx()
    body = await stream_turn(ctx, _fake_adapters(generate=_streaming_generate(["Ho", "la"])))
    await body.__anext__()
    await body.aclose()  # the client went away
    assert len(_trace_records(caplog)) == 1
    # the trace must reflect the FINAL outcomes (after _commit_on_cancel ran),
    # not a snapshot taken mid-cancellation.
    logged = json.loads(_trace_records(caplog)[0].message.removeprefix("turn.trace "))
    assert logged["outcomes"]["generate"] == "cancelled"
    assert logged["outcomes"]["persist_assistant_turn"] == "ok"


async def test_trace_carries_every_step_outcome_and_identity(caplog):
    caplog.set_level(logging.INFO, logger=TRACE_LOGGER)
    ctx = _ctx(turn_id="t-trace-2", session_id="sess-9", entry="api")
    await run_turn(ctx, _fake_adapters())

    logged = json.loads(_trace_records(caplog)[0].message.removeprefix("turn.trace "))
    assert logged["turn_id"] == "t-trace-2"
    assert logged["session_id"] == "sess-9"
    assert logged["entry"] == "api"
    assert logged["streaming"] is False
    assert set(logged["outcomes"]) == set(ALL_IDS)
    assert all(outcome == "ok" for outcome in logged["outcomes"].values())
    assert set(logged["steps"]) == set(ALL_IDS)
    assert logged["partial"] is False


async def test_a_degraded_optional_step_is_visible_in_the_trace(caplog):
    caplog.set_level(logging.INFO, logger=TRACE_LOGGER)

    async def recall(ctx):
        raise RuntimeError("qdrant down")

    await run_turn(_ctx(), _fake_adapters(recall=recall))

    logged = json.loads(_trace_records(caplog)[0].message.removeprefix("turn.trace "))
    assert logged["outcomes"]["recall"] == "degraded"
    assert "error" in logged["steps"]["recall"]


async def test_the_engine_field_names_the_engine_at_both_doors(caplog):
    """`/v1` holds the engine's NAME in `ctx.engine` (`served_by`, a str) while
    the UI door holds the module. Reading `type().__name__` blindly logged the
    literal "str" for every API turn — seen live on 08/09.

    Mutation guard: drop the `isinstance(ctx.engine, str)` branch in
    `emit_turn_trace` and the API case goes RED — "str" instead of "mlx".
    """
    caplog.set_level(logging.INFO, logger=TRACE_LOGGER)

    class _EngineModule:
        pass

    api_ctx = _ctx(turn_id="t-engine-api", entry="api")
    api_ctx.engine = "mlx"
    await run_turn(api_ctx, _fake_adapters())

    ui_ctx = _ctx(turn_id="t-engine-ui", entry="ui")
    ui_ctx.engine = _EngineModule()
    await run_turn(ui_ctx, _fake_adapters())

    by_id = {
        json.loads(r.message.removeprefix("turn.trace "))["turn_id"]:
        json.loads(r.message.removeprefix("turn.trace "))
        for r in _trace_records(caplog)
    }
    assert by_id["t-engine-api"]["engine"] == "mlx"
    assert by_id["t-engine-ui"]["engine"] == "_EngineModule"


async def test_the_turn_line_bills_the_atomisers_call(caplog):
    """#1060 found the turn's trace line under-billed: `memory.write` ran on the
    queue AFTER the line was emitted, so its atomiser call was missing (a second
    line corrected it). Since 25/09 (#1098) `memory.write` runs inline before
    `emit`, so the turn's OWN line must already carry that call — compared
    against the engine's own counter, not a literal. The second-line mechanism
    stays for `compact`, the one step still queued.
    """
    caplog.set_level(logging.INFO, logger=TRACE_LOGGER)
    engine = _CountingMemSaveEngine()
    state = _state_with_real_queue(engine)

    h = _Harness(intent="chat")
    # History, so the opening-turn rule does not decide what gets written.
    h.session.add_message("user", "hola, em dic Aran")
    h.session.add_message("assistant", "Hola!")
    result = await h.call({"message": "em dic Aran", "stream": True}, server_state=state)
    async for _ in result.body_iterator:
        pass

    lines = _trace_records(caplog)
    first = json.loads(lines[0].message.removeprefix("turn.trace "))
    assert "memory.write" not in first.get("post_commit_pending", []), "memory.write is not queued any more"
    assert engine.calls == 2, "the atomiser never ran — there was no call to bill"
    assert first["llm"]["total_calls"] == engine.calls, "the turn's own line misses the atomiser's call"
    assert [c["step"] for c in first["llm"]["calls"]] == ["generate", "memory.write"]
