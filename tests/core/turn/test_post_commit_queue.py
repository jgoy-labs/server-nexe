"""C2.2 (ADR-007 §6/§7): post-commit steps leave the critical path.

`memory.write` and `compact` used to run inline — an LLM call per fact, a full
summarisation before generation (#1042, closed at C1). With a `PostCommitQueue`
passed to `run_turn`/`stream_turn`, they are handed to the queue instead of
awaited: the turn's wire closes at `emit`, and the two steps finish later,
under the SAME `EngineGate` a user turn's `generate` uses (so a user turn
always wins a slot over background work).

Fake adapters and a fake `run` callable throughout — no route, no plugin, no
real engine. Mirrors the posture of test_run_turn.py / test_engine_gate.py.

25/09 (ADR-007 §6 amended, #1098): `memory.write` left the queue and runs
inline, before `emit`; only `compact` is post-commit. Mutation: putting
`memory.write` back into `POST_COMMIT` turns
`test_post_commit_steps_are_queued_not_run_inline` and
`test_memory_write_runs_inline_before_emit_even_with_a_queue` red.
"""
from __future__ import annotations

import asyncio
import threading

import pytest

from core.turn.context import TurnContext
from core.turn.gate import EngineGate, Priority
from core.turn.post_commit import PostCommitQueue
from core.turn.run import TurnShortCircuit, run_turn, stream_turn
from core.turn.steps import TURN_STEPS

pytestmark = pytest.mark.asyncio

ALL_IDS = tuple(step.id for step in TURN_STEPS)
# 25/09 (ADR-007 §6 amended, #1098): only `compact` is post-commit now —
# `memory.write` runs inline, before `emit`.
INLINE_IDS = tuple(sid for sid in ALL_IDS if sid != "compact")


def _ctx(**kwargs) -> TurnContext:
    kwargs.setdefault("turn_id", "t-pc-1")
    kwargs.setdefault("entry", "test")
    kwargs.setdefault("session_id", "sess-pc-1")
    kwargs.setdefault("message", "hola")
    return TurnContext(**kwargs)


def _tracer(step_id: str, calls: list[str]):
    async def adapter(ctx: TurnContext) -> None:
        calls.append(step_id)
    adapter.__name__ = f"fake_{step_id}"
    return adapter


def _fake_adapters(calls: list[str], **overrides):
    table = {sid: _tracer(sid, calls) for sid in ALL_IDS}
    table.update(overrides)
    return table


def _streaming_generate(chunks: list[str], calls: list[str]):
    async def generate(ctx: TurnContext):
        calls.append("generate")
        for chunk in chunks:
            ctx.response += chunk
            yield chunk
    return generate


# --------------------------------------------------------- run.py wiring


async def test_post_commit_steps_are_queued_not_run_inline():
    calls: list[str] = []
    q = PostCommitQueue(EngineGate(slots=1))
    ctx = await run_turn(_ctx(), _fake_adapters(calls), post_commit=q)

    assert list(calls) == list(INLINE_IDS), "compact must not run before drain()"
    assert ctx.outcomes["memory.write"] == "ok", "memory.write is inline since 25/09"
    assert ctx.outcomes["compact"] == "queued"

    q.start()
    await q.drain()
    await q.stop()
    assert set(calls) == set(ALL_IDS)


async def test_memory_write_runs_inline_before_emit_even_with_a_queue():
    """#1098: the turn that saved must be the turn that says so — memory.write
    runs before `emit` (which sends the note) and never reaches the queue."""
    calls: list[str] = []
    q = PostCommitQueue(EngineGate(slots=1))
    await run_turn(_ctx(), _fake_adapters(calls), post_commit=q)
    assert calls.index("persist_assistant_turn") < calls.index("memory.write") < calls.index("emit")
    assert "memory.write" not in q.pending(_ctx().session_id)


async def test_cancelled_stream_queues_nothing():
    calls: list[str] = []
    q = PostCommitQueue(EngineGate(slots=1))
    ctx = _ctx()
    body = await stream_turn(
        ctx, _fake_adapters(calls, generate=_streaming_generate(["Ho", "la"], calls)), post_commit=q,
    )
    await body.__anext__()
    await body.aclose()  # client went away
    assert ctx.outcomes["memory.write"] == "skipped"
    assert ctx.outcomes["compact"] == "skipped"
    assert q.pending(ctx.session_id) == set()
    assert "memory.write" not in calls and "compact" not in calls


async def test_short_circuit_queues_nothing():
    calls: list[str] = []
    q = PostCommitQueue(EngineGate(slots=1))

    async def intent(ctx: TurnContext) -> None:
        raise TurnShortCircuit("Tens 3 records.", reason="memory_intent:list")

    ctx = await run_turn(_ctx(), _fake_adapters(calls, intent=intent), post_commit=q)
    assert ctx.outcomes["memory.write"] == "skipped"
    assert ctx.outcomes["compact"] == "skipped"
    assert q.pending(ctx.session_id) == set()


async def test_partial_turn_queues_no_memory_write_but_still_queues_compact():
    """#1040 (C2.4): a turn marked PARTIAL (an engine error surfaced mid-
    stream, already committed to the wire) never queues memory.write — facts
    atomized from a broken reply are not trustworthy. `compact` is unrelated
    to this turn's own outcome (it summarises the session's history) and
    queues exactly as it would for a clean turn."""
    calls: list[str] = []

    def _mark_partial(step_id: str):
        async def generate(ctx: TurnContext) -> None:
            calls.append(step_id)
            ctx.partial = True
            ctx.error = {"step": "generate", "class": "Retryable", "message": "boom"}
        return generate

    q = PostCommitQueue(EngineGate(slots=1))
    ctx = await run_turn(_ctx(), _fake_adapters(calls, generate=_mark_partial("generate")), post_commit=q)
    assert ctx.outcomes["generate"] == "degraded", "a step that signals ctx.error on itself is degraded, not ok"
    assert ctx.outcomes["memory.write"] == "skipped"
    assert ctx.outcomes["compact"] == "queued"
    assert q.pending(ctx.session_id) == {"compact"}

    q.start()
    await q.drain()
    await q.stop()
    assert "memory.write" not in calls
    assert "compact" in calls


async def test_no_queue_means_inline_exactly_as_before():
    """post_commit=None (the default) must be unchanged from pre-C2.2 — the
    two steps run inline, same as every existing caller expects."""
    calls: list[str] = []
    ctx = await run_turn(_ctx(), _fake_adapters(calls))
    assert list(calls) == list(ALL_IDS)
    assert ctx.outcomes["memory.write"] == "ok"
    assert ctx.outcomes["compact"] == "ok"


# --------------------------------------------------------- PostCommitQueue


async def test_dedupe_keeps_only_the_latest_job_per_session_and_step():
    q = PostCommitQueue(EngineGate(slots=1))
    calls: list[str] = []

    async def run1(cancel):
        calls.append("first")
        return {"outcome": "ok"}

    async def run2(cancel):
        calls.append("second")
        return {"outcome": "ok"}

    q.enqueue(Priority.COMPACT, turn_id="t1", session_id="s1", step_id="compact", run=run1)
    q.enqueue(Priority.COMPACT, turn_id="t2", session_id="s1", step_id="compact", run=run2)
    q.start()
    await q.drain()
    await q.stop()
    assert calls == ["second"]


async def test_preempted_job_is_requeued_until_it_succeeds():
    q = PostCommitQueue(EngineGate(slots=1))
    attempts: list[int] = []

    async def flaky(cancel):
        attempts.append(1)
        if len(attempts) < 2:
            return {"outcome": "preempted"}
        return {"outcome": "ok"}

    q.enqueue(Priority.MEMORY_WRITE, turn_id="t1", session_id="s1", step_id="memory.write", run=flaky)
    q.start()
    await q.drain()
    await q.stop()
    assert len(attempts) == 2
    assert q.take_last_results("s1")["memory.write"]["outcome"] == "ok"


async def test_a_job_that_keeps_failing_stops_after_max_attempts():
    q = PostCommitQueue(EngineGate(slots=1))
    attempts: list[int] = []

    async def always_preempted(cancel):
        attempts.append(1)
        return {"outcome": "preempted"}

    q.enqueue(Priority.MEMORY_WRITE, turn_id="t1", session_id="s1", step_id="memory.write", run=always_preempted)
    q.start()
    await q.drain()
    await q.stop()
    from core.turn.post_commit import MAX_ATTEMPTS
    assert len(attempts) == MAX_ATTEMPTS
    assert q.take_last_results("s1")["memory.write"]["outcome"] == "preempted"


async def test_worker_survives_a_failing_job_and_records_it():
    q = PostCommitQueue(EngineGate(slots=1))
    done: list[str] = []

    async def boom(cancel):
        raise RuntimeError("kaboom")

    async def fine(cancel):
        done.append("fine")
        return {"outcome": "ok"}

    q.enqueue(Priority.MEMORY_WRITE, turn_id="t1", session_id="s1", step_id="memory.write", run=boom)
    q.enqueue(Priority.COMPACT, turn_id="t2", session_id="s2", step_id="compact", run=fine)
    q.start()
    await q.drain()
    await q.stop()
    assert done == ["fine"], "a failing job must not take the worker down with it"
    result = q.take_last_results("s1")["memory.write"]
    assert result["outcome"] == "failed"
    assert "kaboom" in result["error"]


async def test_take_last_results_pops_not_peeks():
    q = PostCommitQueue(EngineGate(slots=1))

    async def ok(cancel):
        return {"outcome": "ok"}

    q.enqueue(Priority.COMPACT, turn_id="t1", session_id="s1", step_id="compact", run=ok)
    q.start()
    await q.drain()
    await q.stop()
    first = q.take_last_results("s1")
    assert "compact" in first
    assert q.take_last_results("s1") == {}, "results are consumed once, not accumulated forever"


async def test_preempt_signals_a_running_jobs_cancel_event():
    q = PostCommitQueue(EngineGate(slots=1))
    picked_up = asyncio.Event()
    seen: list[bool] = []

    async def slow(cancel):
        picked_up.set()
        await asyncio.sleep(0.03)
        seen.append(cancel.is_set())
        return {"outcome": "ok"}

    q.enqueue(Priority.COMPACT, turn_id="t1", session_id="s1", step_id="compact", run=slow, cancel=threading.Event())
    q.start()
    await picked_up.wait()
    q.preempt("s1")
    await q.drain()
    await q.stop()
    assert seen == [True]


async def test_drain_is_deterministic_no_sleep_needed():
    """Ten jobs, no asyncio.sleep in the test itself — drain() must not
    return until every one of them has actually finished."""
    q = PostCommitQueue(EngineGate(slots=1))
    done: list[int] = []

    def make(i):
        async def run(cancel):
            done.append(i)
            return {"outcome": "ok"}
        return run

    for i in range(10):
        q.enqueue(Priority.MEMORY_WRITE, turn_id=f"t{i}", session_id=f"s{i}", step_id="memory.write", run=make(i))
    q.start()
    await q.drain()
    await q.stop()
    assert sorted(done) == list(range(10))
