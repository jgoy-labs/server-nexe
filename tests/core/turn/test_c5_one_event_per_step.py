"""C5 part A — the `TraceSink` port: one `StepEvent` per step, said once.

Every step of `TURN_STEPS` ends with exactly one event, in the order the turn ran
them (the post-commit ones last, when their job ends), whatever shape the turn
had; a sink that raises changes nothing of what the turn answers.
"""
from __future__ import annotations

import asyncio
import json
import logging

import pytest

from core.turn.context import TurnContext
from core.turn.gate import EngineGate
from core.turn.post_commit import PostCommitQueue
from core.turn.run import POST_COMMIT, TurnShortCircuit, run_turn, stream_turn
from core.turn.steps import TURN_STEPS
from core.turn.trace import LogSink, StepEvent, TraceSink, sinks_for

from ._c48_p0_lab import DOORS, build_world, run_door

pytestmark = pytest.mark.asyncio

ALL_IDS = tuple(step.id for step in TURN_STEPS)


class Recorder:
    def __init__(self) -> None:
        self.steps: list[StepEvent] = []
        self.turns: list[dict] = []

    def on_step(self, event: StepEvent) -> None:
        self.steps.append(event)

    def on_turn(self, ctx, line) -> None:
        self.turns.append(line)


class Broken:
    def on_step(self, event) -> None:
        raise RuntimeError("sink down")

    def on_turn(self, ctx, line) -> None:
        raise RuntimeError("sink down")


class _State:
    def __init__(self, *sinks) -> None:
        self.trace_sinks = tuple(sinks)


def _ctx(state=None, **kwargs) -> TurnContext:
    kwargs.setdefault("turn_id", "t-c5a")
    kwargs.setdefault("entry", "test")
    kwargs.setdefault("message", "hola")
    return TurnContext(app_state=state, **kwargs)


def _table(**overrides):
    async def noop(ctx):
        return None

    table = {step_id: noop for step_id in ALL_IDS}
    table.update(overrides)
    return table


def _ids(rec: Recorder) -> list[str]:
    return [e.step for e in rec.steps]


async def test_a_plain_turn_ends_every_step_with_one_event_in_order():
    rec = Recorder()
    await run_turn(_ctx(_State(rec)), _table())
    assert _ids(rec) == list(ALL_IDS)
    assert {e.outcome for e in rec.steps} == {"ok"}
    assert all(e.turn_id == "t-c5a" and e.entry == "test" for e in rec.steps)


async def test_a_streamed_turn_says_every_step_once():
    rec = Recorder()

    async def generate(ctx):
        yield "x"

    body = await stream_turn(_ctx(_State(rec)), _table(generate=generate))
    async for _ in body:
        pass
    assert _ids(rec) == list(ALL_IDS)


async def test_a_short_circuit_skips_are_events_too():
    rec = Recorder()

    async def intent(ctx):
        raise TurnShortCircuit("fet", reason="memory_intent")

    await run_turn(_ctx(_State(rec)), _table(intent=intent))
    assert sorted(_ids(rec)) == sorted(ALL_IDS), "one event per id, none twice"
    by = {e.step: e.outcome for e in rec.steps}
    assert by["intent"] == "short_circuit" and by["generate"] == "skipped" and by["emit"] == "ok"


async def test_a_degraded_step_carries_its_reason_and_a_failed_one_its_code():
    rec = Recorder()

    async def recall(ctx):
        raise RuntimeError("qdrant down")

    await run_turn(_ctx(_State(rec)), _table(recall=recall))
    event = next(e for e in rec.steps if e.step == "recall")
    assert event.outcome == "degraded" and "qdrant down" in event.degraded_reason
    assert event.error_code == "RuntimeError"


async def test_an_http_error_is_its_status():
    from fastapi import HTTPException

    rec = Recorder()

    async def validate(ctx):
        raise HTTPException(status_code=400, detail="no")

    with pytest.raises(HTTPException):
        await run_turn(_ctx(_State(rec)), _table(validate=validate))
    first = rec.steps[0]
    assert (first.step, first.outcome, first.error_code) == ("validate", "failed", "http_400")


async def test_the_reason_a_client_left_travels_with_the_event():
    class _Event:
        reasons = {"client_gone"}

    rec = Recorder()
    ctx = _ctx(_State(rec))
    ctx.cancel_token = (_Event(), None)
    await run_turn(ctx, _table())
    assert all(e.cancelled and e.cancel_reason == "client_gone" for e in rec.steps), \
        "a step that ended ok after the client left still says so (45b71783)"


async def test_a_sink_that_raises_changes_nothing_and_is_named(caplog):
    rec = Recorder()
    caplog.set_level(logging.WARNING, logger="core.turn.trace")
    ctx = _ctx(_State(Broken(), rec))
    await run_turn(ctx, _table())
    assert _ids(rec) == list(ALL_IDS), "the sink after the broken one still hears everything"
    assert "Broken" in caplog.text


async def test_without_sinks_on_the_state_there_is_the_log_alone():
    sinks = sinks_for(None)
    assert len(sinks) == 1 and isinstance(sinks[0], LogSink) and isinstance(sinks[0], TraceSink)
    from unittest.mock import MagicMock
    assert sinks_for(MagicMock()) == sinks, "a mocked app_state is not a list of sinks"


async def test_the_post_commit_steps_say_themselves_when_their_job_ends():
    rec = Recorder()
    queue = PostCommitQueue(EngineGate(slots=1))
    queue.start()
    ctx = _ctx(_State(rec))
    try:
        await run_turn(ctx, _table(), post_commit=queue)
        queued_ids = [i for i in _ids(rec) if i in POST_COMMIT]
        assert queued_ids == [], "`queued` is not an event"
        await queue.drain()
    finally:
        await queue.stop()
    ids = _ids(rec)
    assert sorted(ids) == sorted(ALL_IDS), "each id once, the queued ones when their job ended"
    assert set(ids[-len(POST_COMMIT):]) == set(POST_COMMIT), "post-commit events come last"
    assert {e.outcome for e in rec.steps if e.step in POST_COMMIT} == {"ok"}


async def test_a_superseded_job_says_superseded():
    rec = Recorder()
    queue = PostCommitQueue(EngineGate(slots=1))
    first = _ctx(_State(rec), turn_id="t-1", session_id="s")
    second = _ctx(_State(rec), turn_id="t-2", session_id="s")
    # Queued before the worker starts: the second replaces the first.
    await run_turn(first, _table(), post_commit=queue)
    await run_turn(second, _table(), post_commit=queue)
    queue.start()
    try:
        await queue.drain()
    finally:
        await queue.stop()
    gone = [(e.turn_id, e.step) for e in rec.steps if e.outcome == "superseded"]
    assert sorted(gone) == [("t-1", "compact"), ("t-1", "describe_image")]


@pytest.mark.parametrize("door", DOORS)
async def test_a_real_turn_at_each_door_ends_every_step_once(turn_lab, door):
    rec = Recorder()
    turn_lab.app_state.trace_sinks = (rec, LogSink())
    world = build_world({}, live=["mlx", "llama_cpp"])
    await run_door(turn_lab, world, door, backend="mlx", sid=f"c5a-{door}")
    ids = _ids(rec)
    assert sorted(ids) == sorted(ALL_IDS)
    assert ids == [i for i in ALL_IDS if i in ids], "in TURN_STEPS order"
    assert len(rec.turns) == 1


async def test_a_turn_that_ends_in_an_exception_still_leaves_its_line(caplog):
    caplog.set_level(logging.INFO, logger="nexe.turn.trace")

    async def generate(ctx):
        raise RuntimeError("engine gone")

    with pytest.raises(RuntimeError):
        await run_turn(_ctx(), _table(generate=generate))
    lines = [r for r in caplog.records if r.name == "nexe.turn.trace" and r.message.startswith("turn.trace ")]
    assert len(lines) == 1
    assert json.loads(lines[0].message.removeprefix("turn.trace "))["outcomes"]["generate"] == "failed"
