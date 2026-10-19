"""C5 part E (B5) — one record of the engine metrics, the same at both doors.

`core_chat_engine_*` used to be written by `/v1` alone (when an engine was tried,
and again for the re-prompt); the web wrote nothing. The `MetricsSink` writes them
from the events of the turn, for both doors, and writes the two series per step.
"""
from __future__ import annotations

import pytest

from core.metrics.registry import (
    CHAT_ENGINE_DURATION, CHAT_ENGINE_REQUESTS, TURN_STEP_DURATION, TURN_STEPS_TOTAL, REGISTRY,
)
from core.turn.context import TurnContext
from core.turn.metrics_sink import MetricsSink
from core.turn.trace import LogSink, StepEvent, note_attempt, step_event, sinks_for

from ._c48_p0_lab import DOORS, build_world, run_door


def _value(name: str, **labels) -> float:
    return REGISTRY.get_sample_value(name, labels) or 0.0


def _event(**kw) -> StepEvent:
    base = dict(turn_id="t", entry="api", streaming=False, step="generate", kind="llm",
                started_at=0.0, duration_ms=250.0, outcome="ok")
    base.update(kw)
    return StepEvent(**base)


def test_an_event_writes_its_step_series_and_one_row_per_attempt():
    sink = MetricsSink()
    before_steps = _value("core_turn_steps_total", step="c5e-x", outcome="ok")
    before_req = _value("core_chat_engine_requests_total", engine="c5e-eng", status="error")
    before_ok = _value("core_chat_engine_requests_total", engine="c5e-eng", status="success")
    sink.on_step(_event(step="c5e-x", attempts=(
        {"engine": "c5e-eng", "ok": False, "ms": 40.0}, {"engine": "c5e-eng", "ok": True, "ms": 60.0})))
    assert _value("core_turn_steps_total", step="c5e-x", outcome="ok") == before_steps + 1
    assert _value("core_chat_engine_requests_total", engine="c5e-eng", status="error") == before_req + 1
    assert _value("core_chat_engine_requests_total", engine="c5e-eng", status="success") == before_ok + 1
    assert _value("core_turn_step_duration_seconds_count", step="c5e-x") >= 1
    assert _value("core_chat_engine_duration_seconds_count", engine="c5e-eng") >= 2


def test_a_metrics_failure_never_reaches_the_turn(monkeypatch):
    import core.metrics.registry as registry

    monkeypatch.setattr(registry, "TURN_STEPS_TOTAL", None)
    MetricsSink().on_step(_event())  # raises inside, is swallowed


def test_an_attempt_is_carried_by_the_next_event_of_its_step_once():
    ctx = TurnContext(turn_id="t", entry="api")
    note_attempt(ctx, "generate", "mlx", False, 30.0)
    note_attempt(ctx, "postprocess", "mlx", True, 10.0)
    first = step_event(ctx, "generate", "llm", "ok", 5.0)
    again = step_event(ctx, "generate", "llm", "ok", 5.0)
    assert [(a["engine"], a["ok"]) for a in first.attempts] == [("mlx", False)]
    assert again.attempts == (), "said once"
    assert [(a["engine"], a["ok"]) for a in step_event(ctx, "postprocess", "compute", "ok", 1.0).attempts] == [("mlx", True)]


def test_without_app_state_sinks_the_default_is_the_log_alone():
    """The metrics are wired at the lifespan (`app.state.trace_sinks`), not by default: a test
    that builds a turn by hand must not move the process-wide counters."""
    assert [type(s) for s in sinks_for(None)] == [LogSink]


@pytest.mark.parametrize("door", DOORS)
async def test_a_fall_back_counts_both_attempts_at_every_door(turn_lab, door):
    turn_lab.app_state.trace_sinks = (MetricsSink(),)
    mlx_err = _value("core_chat_engine_requests_total", engine="mlx", status="error")
    llama_ok = _value("core_chat_engine_requests_total", engine="llama_cpp", status="success")
    world = build_world({"mlx": "pre_byte"}, live=["mlx", "llama_cpp"])
    await run_door(turn_lab, world, door, backend="mlx", sid=f"c5e-{door}")
    assert _value("core_chat_engine_requests_total", engine="mlx", status="error") == mlx_err + 1
    assert _value("core_chat_engine_requests_total", engine="llama_cpp", status="success") == llama_ok + 1
    assert _value("core_turn_steps_total", step="generate", outcome="ok") >= 1


@pytest.mark.parametrize("door", DOORS)
async def test_an_engine_that_answers_first_time_counts_once_at_every_door(turn_lab, door):
    """The old `/v1` count AND the sink's would have said two."""
    turn_lab.app_state.trace_sinks = (MetricsSink(),)
    before = _value("core_chat_engine_requests_total", engine="mlx", status="success")
    world = build_world({}, live=["mlx", "llama_cpp"])
    await run_door(turn_lab, world, door, backend="mlx", sid=f"c5e-one-{door}")
    assert _value("core_chat_engine_requests_total", engine="mlx", status="success") == before + 1


async def test_the_re_prompt_says_its_attempt_the_same_at_both_doors_and_a_failure_is_an_error():
    """The old `/v1` re-prompt wrote its own counter (`ask_again`); the web wrote none. The
    policy that both run says the attempt on the turn, ok or not (C5 E: «per llm.calls»)."""
    from starlette.datastructures import State

    from core.turn import policy
    from core.turn.gate import EngineGate

    async def ok():
        yield "hola"

    async def broken():
        raise RuntimeError("engine died")
        yield  # pragma: no cover

    for entry in ("ui", "api"):
        for make, expected in ((ok, True), (broken, False)):
            state = State()
            state.engine_gate = EngineGate(slots=1)
            ctx = TurnContext(turn_id=f"t-{entry}", entry=entry, app_state=state, system_prompt="s", lang="ca")
            out = [c async for c in policy.reprompt_chunks(
                ctx, ["f"], call=lambda system, make=make: make(), engine_name="mlx", model=None)]
            assert [(a["step"], a["engine"], a["ok"]) for a in ctx.usage["engine_attempts"]] == [
                ("postprocess", "mlx", expected)], (entry, expected, out)


def test_the_tokens_the_engines_said_are_counted_and_what_they_did_not_say_is_not():
    """pla-tokens-reals: one series per engine and kind; a call with nothing said adds nothing."""
    before = {k: _value("core_turn_tokens_total", engine="tok-eng", kind=k) for k in ("in", "out", "cached")}
    line = {"llm": {"calls": [
        {"engine": "tok-eng", "tokens_in": 40, "tokens_out": 9, "cached_in": 30},
        {"engine": "tok-eng", "tokens_in": None, "tokens_out": None, "cached_in": None},
        {"engine": "tok-eng", "tokens_in": 5, "tokens_out": 1, "cached_in": 0},
    ]}}
    MetricsSink().on_turn(None, line)
    assert _value("core_turn_tokens_total", engine="tok-eng", kind="in") == before["in"] + 45
    assert _value("core_turn_tokens_total", engine="tok-eng", kind="out") == before["out"] + 10
    assert _value("core_turn_tokens_total", engine="tok-eng", kind="cached") == before["cached"] + 30
