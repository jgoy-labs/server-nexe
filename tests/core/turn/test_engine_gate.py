"""C2.1 (ADR-007 §7): one engine, N generation slots — not per-plugin locks.

Before this gate, the UI's `Semaphore(2)` (routes_chat.py) released when
`_chat_inner` returned the `StreamingResponse` OBJECT, before a single token
had been generated — it protected nothing. `/v1` had no guard at all. MLX and
llama.cpp run on independent single-worker executors, so two generations
could (and, once, did) run on Metal at once. `EngineGate` is the actual door:
a holder keeps its slot for as long as its BODY runs, and a waiting user turn
preempts any background (COMPACT/MEMORY_WRITE) holder.

No route, no plugin, no real engine is touched here — this is the gate's own
policy, exercised directly (the same posture as tests/core/turn/test_run_turn.py
for the engine's policy).

Mutation check (exercised by hand before merging C2.1, see the diari):
releasing the slot right after `acquire` (instead of holding it for the
simulated body) turns `test_a_second_user_turn_waits_for_the_first_bodys_slot`
red — with the slot free immediately, the second acquire never has to wait.
"""
from __future__ import annotations

import asyncio
import threading

import pytest

from core.turn.gate import EngineGate, GateBusy, Priority, gate_for

pytestmark = pytest.mark.asyncio


async def test_a_free_gate_grants_immediately():
    gate = EngineGate(slots=1)
    slot = await gate.acquire(Priority.USER_TURN, holder="t1")
    assert slot.holder == "t1"
    assert slot.priority is Priority.USER_TURN
    assert gate.snapshot()["free"] == 0


async def test_release_frees_the_slot_for_the_next_holder():
    gate = EngineGate(slots=1)
    slot = await gate.acquire(Priority.USER_TURN, holder="t1")
    await gate.release(slot)
    assert gate.snapshot()["free"] == 1
    slot2 = await gate.acquire(Priority.USER_TURN, holder="t2")
    assert slot2.holder == "t2"


async def test_release_is_idempotent():
    gate = EngineGate(slots=1)
    slot = await gate.acquire(Priority.USER_TURN, holder="t1")
    await gate.release(slot)
    await gate.release(slot)  # must not raise, must not free a second slot
    assert gate.snapshot()["free"] == 1


async def test_a_second_user_turn_waits_for_the_first_bodys_slot():
    """The exact fix: the slot is held for the BODY, not just until `acquire`
    returns — two user turns on a 1-slot gate cannot overlap."""
    gate = EngineGate(slots=1)
    order: list[str] = []

    async def simulated_turn(name: str, hold_s: float):
        slot = await gate.acquire(Priority.USER_TURN, holder=name, timeout=2.0)
        order.append(f"{name}:acquired")
        try:
            await asyncio.sleep(hold_s)
        finally:
            order.append(f"{name}:released")
            await gate.release(slot)

    await asyncio.gather(
        simulated_turn("first", 0.05),
        simulated_turn("second", 0.0),
    )
    # "second" cannot acquire until "first" has released — the whole point.
    assert order == ["first:acquired", "first:released", "second:acquired", "second:released"]


async def test_gate_busy_when_the_wait_times_out():
    gate = EngineGate(slots=1)
    await gate.acquire(Priority.USER_TURN, holder="holder")  # never released
    with pytest.raises(GateBusy):
        await gate.acquire(Priority.USER_TURN, holder="waiter", timeout=0.05)


async def test_a_waiting_user_turn_preempts_a_background_holder():
    gate = EngineGate(slots=1)
    cancel = threading.Event()
    bg_slot = await gate.acquire(Priority.COMPACT, holder="compact-job", cancel_event=cancel)
    assert not cancel.is_set()

    async def user_turn():
        return await gate.acquire(Priority.USER_TURN, holder="user", timeout=2.0)

    task = asyncio.create_task(user_turn())
    await asyncio.sleep(0.02)  # let acquire() start waiting and preempt
    assert cancel.is_set(), "the background holder must be signalled, not forced out"
    # The gate never revokes the slot itself — the background job must give it
    # back. Simulate that (a real job checks its own cancel_event).
    await gate.release(bg_slot)
    user_slot = await task
    assert user_slot.holder == "user"


async def test_a_user_turn_never_preempts_another_user_turn():
    gate = EngineGate(slots=1)
    cancel = threading.Event()
    await gate.acquire(Priority.USER_TURN, holder="first", cancel_event=cancel)
    with pytest.raises(GateBusy):
        await gate.acquire(Priority.USER_TURN, holder="second", timeout=0.05)
    assert not cancel.is_set(), "USER_TURN must not preempt another USER_TURN"


async def test_preempt_lower_ignores_a_holder_with_no_cancel_event():
    """A holder with no cancel_event (nothing safe to interrupt) is left
    alone — preemption is cooperative, never forced."""
    gate = EngineGate(slots=1)
    await gate.acquire(Priority.MEMORY_WRITE, holder="mem-job", cancel_event=None)
    preempted = gate.preempt_lower(Priority.USER_TURN)
    assert preempted == []


async def test_snapshot_reports_slots_free_and_holders():
    gate = EngineGate(slots=2)
    await gate.acquire(Priority.USER_TURN, holder="a")
    snap = gate.snapshot()
    assert snap["slots"] == 2
    assert snap["free"] == 1
    assert [h["holder"] for h in snap["holders"]] == ["a"]


class _FakeAppState:
    def __init__(self, gate=None):
        if gate is not None:
            self.engine_gate = gate


async def test_gate_for_returns_the_real_gate_when_attached():
    gate = EngineGate(slots=3)
    assert gate_for(_FakeAppState(gate)) is gate


async def test_gate_for_falls_back_when_missing_and_never_blocks():
    """A bare app_state (a pre-C2.1 test harness) must not make `generate`
    raise AttributeError, and the fallback must never itself be the reason a
    caller waits."""
    app_state = _FakeAppState()
    gate = gate_for(app_state)
    slot = await gate.acquire(Priority.USER_TURN, holder="x", timeout=0.01)
    assert slot.holder == "x"
    await gate.release(slot)
