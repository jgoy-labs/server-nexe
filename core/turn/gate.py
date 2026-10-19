"""The engine has one door — a slot-based gate, not per-plugin locks
(ADR-007 §7, C2.1).

Two LLM calls in parallel on the same GPU crashed Metal once (the autosave/
MLX incident that motivated §7's "single engine semaphore"). Today's guard —
`Semaphore(2)` in `routes_chat.py` — releases when `_chat_inner` returns the
`StreamingResponse` OBJECT, before its body has generated a single token, so
it protects nothing; `/v1` has no guard at all; MLX and llama.cpp run on
independent single-worker executors, so both can generate at once. This gate
is the actual door: a user turn holds a slot for as long as its body is being
driven, on both doors, in both wire shapes.

Priority (lower number = more important): a USER_TURN that has to wait
signals every current background holder (COMPACT, MEMORY_WRITE — the queue
C2.2 builds) to give up its slot. The gate never revokes a slot itself — it
only sets the holder's own `cancel_event`; the holder must notice and give
the slot back (`release`). Two USER_TURNs queue FIFO within their priority
(`asyncio.Condition` wakes them in wait order).

Two gates, not one (phase 3 of the API providers). The slot exists because two
generations in parallel on the SAME GPU crashed Metal; an answer that comes from
an external provider uses no GPU of this machine and can take as long as the
provider takes. Sharing the single local slot would make a cloud answer block
every local engine for its whole duration, and the other way round. So a
hosted engine (`engine_is_cloud`) has a gate of its own, with its own number of
slots (`NEXE_CLOUD_ENGINE_SLOTS`), and `gate_for(app_state, engine)` hands out
the right one. The wait budget is shared.
"""
from __future__ import annotations

import asyncio
import itertools
import logging
import os
import threading
import time
from dataclasses import dataclass
from enum import IntEnum
from typing import Optional

logger = logging.getLogger(__name__)

#: How many turns/jobs may hold the engine at once. The Metal incident this
#: gate exists for was two concurrent generations — default stays at one
#: until measured otherwise.
ENV_GATE_SLOTS = "NEXE_ENGINE_SLOTS"
DEFAULT_GATE_SLOTS = 1

#: The slots of the gate of the hosted engines (the API). No GPU is involved, so
#: more than one: a web tab and a `/v1` client may each be waiting for the
#: provider at once. A bound, not a target: it keeps a runaway client from
#: opening unlimited paid requests.
ENV_CLOUD_GATE_SLOTS = "NEXE_CLOUD_ENGINE_SLOTS"
DEFAULT_CLOUD_GATE_SLOTS = 4

#: How long a user turn waits for a slot before the door answers 429 — the
#: same 5s `_chat_semaphore` used, now honoured by both doors.
ENV_GATE_WAIT_S = "NEXE_ENGINE_GATE_WAIT_S"
DEFAULT_GATE_WAIT_S = 5.0


class Priority(IntEnum):
    """Lower value wins. A waiting USER_TURN preempts any COMPACT or
    MEMORY_WRITE holder; it never preempts another USER_TURN."""

    USER_TURN = 0
    COMPACT = 1
    MEMORY_WRITE = 2


class GateBusy(TimeoutError):
    """No slot became free for `holder` within its wait budget — the 429 case."""


@dataclass
class Slot:
    """A held ticket. `cancel` is the HOLDER's own cancellation signal, handed
    in at `acquire` time — `preempt_lower` only sets it; giving the slot back
    is still the holder's job (there is no way to force it mid-generation)."""

    priority: Priority
    holder: str
    cancel: Optional[threading.Event]
    acquired_at: float
    id: int


def _gate_slots() -> int:
    try:
        return max(1, int(os.environ.get(ENV_GATE_SLOTS, DEFAULT_GATE_SLOTS)))
    except ValueError:
        return DEFAULT_GATE_SLOTS


def _cloud_gate_slots() -> int:
    try:
        return max(1, int(os.environ.get(ENV_CLOUD_GATE_SLOTS, DEFAULT_CLOUD_GATE_SLOTS)))
    except ValueError:
        return DEFAULT_CLOUD_GATE_SLOTS


def _gate_wait_s() -> float:
    try:
        return float(os.environ.get(ENV_GATE_WAIT_S, DEFAULT_GATE_WAIT_S))
    except ValueError:
        return DEFAULT_GATE_WAIT_S


class EngineGate:
    """`slots` generation slots, shared by every door and every background job."""

    def __init__(self, slots: int = 1) -> None:
        self._slots = slots
        self._condition = asyncio.Condition()
        self._holders: dict[int, Slot] = {}
        self._counter = itertools.count()

    def _free(self) -> int:
        return self._slots - len(self._holders)

    async def acquire(
        self,
        priority: Priority,
        *,
        holder: str,
        cancel_event: Optional[threading.Event] = None,
        timeout: Optional[float] = None,
    ) -> Slot:
        """Block until a slot is free (or `timeout` elapses → `GateBusy`).

        A USER_TURN preempts current background holders BEFORE waiting and
        again after every wake-up — a holder may ignore its `cancel_event`
        for a little while (it is cooperative, not forced), so re-signalling
        on every loop costs nothing and closes that gap.
        """
        deadline = None if timeout is None else time.monotonic() + timeout
        async with self._condition:
            if priority is Priority.USER_TURN:
                self._preempt_lower_locked(Priority.USER_TURN)
            while self._free() <= 0:
                remaining = None if deadline is None else deadline - time.monotonic()
                if remaining is not None and remaining <= 0:
                    raise GateBusy(f"no engine slot free for {holder!r} within {timeout}s")
                try:
                    if remaining is None:
                        await self._condition.wait()
                    else:
                        await asyncio.wait_for(self._condition.wait(), timeout=remaining)
                except asyncio.TimeoutError:
                    raise GateBusy(f"no engine slot free for {holder!r} within {timeout}s") from None
                if priority is Priority.USER_TURN:
                    self._preempt_lower_locked(Priority.USER_TURN)
            slot = Slot(
                priority=priority, holder=holder, cancel=cancel_event,
                acquired_at=time.monotonic(), id=next(self._counter),
            )
            self._holders[slot.id] = slot
            return slot

    async def release(self, slot: Slot) -> None:
        """Idempotent: releasing an already-released (or never-held) slot is
        a no-op — a caller unwinding from more than one exit path (a normal
        finish AND a cancellation handler) must not have to track which one
        already released it."""
        async with self._condition:
            if self._holders.pop(slot.id, None) is None:
                return
            self._condition.notify_all()

    def preempt_lower(self, than: Priority) -> list[Slot]:
        """Signal every current holder whose priority is lower (numerically
        greater) than `than`. Best-effort and synchronous — safe to call
        without holding the condition (worst case: a holder that released in
        the same instant is signalled for nothing, which is harmless)."""
        return self._preempt_lower_locked(than)

    def _preempt_lower_locked(self, than: Priority) -> list[Slot]:
        preempted = []
        for slot in self._holders.values():
            if slot.priority > than and slot.cancel is not None and not slot.cancel.is_set():
                slot.cancel.set()
                preempted.append(slot)
        if preempted:
            logger.info(
                "engine gate: preempted %d background holder(s) for a %s waiting",
                len(preempted), than.name,
            )
        return preempted

    def snapshot(self) -> dict:
        """For a trace line or a status endpoint — never for control flow."""
        now = time.monotonic()
        return {
            "slots": self._slots,
            "free": self._free(),
            "holders": [
                {"priority": s.priority.name, "holder": s.holder, "held_s": round(now - s.acquired_at, 3)}
                for s in self._holders.values()
            ],
        }


def attach_engine_gate(server_state, *, slots: Optional[int] = None) -> EngineGate:
    """Attach (or return the existing) EngineGate on `server_state` — same
    idempotent-attach shape as `core.sessions.attach.attach_session_manager`."""
    existing = getattr(server_state, "engine_gate", None)
    if existing is not None:
        return existing
    gate = EngineGate(slots=slots if slots is not None else _gate_slots())
    server_state.engine_gate = gate
    return gate


def attach_cloud_gate(server_state, *, slots: Optional[int] = None) -> EngineGate:
    """Attach (or return the existing) gate of the hosted engines on `server_state`."""
    existing = getattr(server_state, "cloud_engine_gate", None)
    if existing is not None:
        return existing
    gate = EngineGate(slots=slots if slots is not None else _cloud_gate_slots())
    server_state.cloud_engine_gate = gate
    return gate


#: A practically-unlimited gate for `gate_for` below — never the real door,
#: only what a caller gets when there is no real one to find.
_FALLBACK_GATE = EngineGate(slots=1_000_000)
_warned_fallback = False


def gate_for(app_state: object, engine: object = None) -> EngineGate:
    """The gate for the engine this turn runs on: the hosted engines' own
    (`app_state.cloud_engine_gate`) when `engine` is one, the local one
    (`app_state.engine_gate`) otherwise.

    `engine` is the engine's name (`/v1` carries it) or its live module (the web
    door does); None is a local engine. A hosted engine never falls back to the
    LOCAL gate when its own is missing: that would make it block the local
    engines, which is what having its own is for.

    Production always has real ones: the lifespan attaches them (`attach_
    engine_gate`, `attach_cloud_gate`) before any request can reach a door — same
    shape as `session_manager`'s "attach once in lifespan, mirror onto app.state"
    (core/lifespan_sessions.py). A bare `app_state` only happens in the ~20
    test files that build their own minimal FastAPI app/request by hand and
    predate C2.1; making every one of them grow an EngineGate is not worth it
    when NONE of them drives two real concurrent generations against a real
    GPU — the one thing this gate exists to prevent. Logs once, not per call,
    so those suites do not flood their output; this must never fire against a
    real server.
    """
    from core.endpoints.chat_engines.routing import engine_is_cloud  # deferred: endpoints → turn

    attr = "cloud_engine_gate" if engine_is_cloud(engine) else "engine_gate"
    gate = getattr(app_state, attr, None)
    if isinstance(gate, EngineGate):
        return gate
    global _warned_fallback
    if not _warned_fallback:
        _warned_fallback = True
        logger.warning(
            "%s missing on app_state — generation running UNGUARDED "
            "for this request (expected only in a pre-C2.1 test harness)", attr,
        )
    return _FALLBACK_GATE
