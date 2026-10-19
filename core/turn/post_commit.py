"""Post-commit work — memory.write and compact leave the critical path
(ADR-007 §6/§7, C2.2).

Before C2.2, both steps ran INLINE: the atomizer (an LLM call per fact) kept
the stream open after the answer was already complete, and compaction (a full
LLM summarisation, ~100 s measured in 8 GB — CHANGELOG #965) ran BEFORE
generation, inside the per-engine retry loop, so a fallback could trigger it
twice (#1042, closed at C1). `run_turn`/`stream_turn` (`core/turn/run.py`)
enqueue a `POST_COMMIT` step here instead of calling its adapter; the turn's
wire closes the moment `emit` is done.

One process-wide queue, one worker, the SAME `EngineGate` (core/turn/gate.py)
the doors use for `generate` — `Priority.USER_TURN` always wins a slot over
`COMPACT`/`MEMORY_WRITE`. A job that calls a hosted engine (the API) holds a
slot of the hosted engines' gate instead (`Job.cloud`): a summary written by a
provider must not hold the one local slot while it waits for the network. A background job's `cancel` is a `threading.Event`
handed to its `run` callable; the gate's `preempt_lower` sets it when a user
turn has to wait, but SETTING it is not STOPPING it — the job's own `run`
must notice and give up, same cooperative contract as `generate`'s
`cancel_event` today.
"""
from __future__ import annotations

import asyncio
import itertools
import logging
import time
from dataclasses import dataclass, field
from typing import Any, Awaitable, Callable, Optional

from core.turn.gate import EngineGate, GateBusy, Priority, _cloud_gate_slots

logger = logging.getLogger(__name__)

#: A job whose `run` reports this is put back on the queue instead of being
#: recorded as done — up to this many times, so a job perpetually preempted
#: by a busy engine does not spin forever.
MAX_ATTEMPTS = 3

RunFn = Callable[["object"], Awaitable[dict]]  # object = threading.Event, kept loose to avoid the import here


@dataclass(order=True)
class Job:
    """One unit of post-commit work. Only `priority`/`seq` are compared —
    `@dataclass(order=True)` needs every field ordered otherwise, and `run`/
    `cancel` are not orderable."""

    priority: Priority
    seq: int
    turn_id: str = field(compare=False)
    session_id: Optional[str] = field(compare=False)
    step_id: str = field(compare=False)
    run: RunFn = field(compare=False)
    cancel: Optional[Any] = field(compare=False)
    attempts: int = field(default=0, compare=False)
    #: The job calls a hosted engine: it runs under that engine's gate.
    cloud: bool = field(default=False, compare=False)
    #: Called once with the job's final word (`outcome`, `ms`, `at`): the turn's
    #: trace publishes the step's event from it (C5). A superseded job says
    #: `{"outcome": "superseded"}`.
    finish: Optional[Callable[[dict], None]] = field(default=None, compare=False)


class PostCommitQueue:
    """FIFO-within-priority queue of post-commit jobs, drained by one worker
    task under the shared `EngineGate` — and by a second one, with its own queue,
    for the jobs that call a hosted engine (`Job.cloud`): they wait on the hosted
    engines' gate, for as long as a provider takes, and one worker for both would
    make every local job wait behind a provider that is slow or whose gate is full.
    The two workers can therefore run two jobs of the SAME session at once (a hosted
    compaction of turn N, a local job of turn N+1): the next user turn's `preempt`
    signals the running job of either kind, so neither outlives the turn it was
    queued by without being told."""

    def __init__(self, gate: EngineGate, *, cloud_gate: Optional[EngineGate] = None,
                 log: Optional[logging.Logger] = None) -> None:
        self._gate = gate
        #: Its own, never the local one: a queue built without it still keeps a hosted job off the local slot.
        self._cloud_gate = cloud_gate if cloud_gate is not None else EngineGate(slots=_cloud_gate_slots())
        self._log = log or logger
        self._queue: "asyncio.PriorityQueue[Job]" = asyncio.PriorityQueue()
        self._cloud_queue: "asyncio.PriorityQueue[Job]" = asyncio.PriorityQueue()
        self._seq = itertools.count()
        # The one job still queued per (session_id, step_id) — a fresher
        # enqueue for the same pair replaces it; the stale one, if the worker
        # dequeues it later, is dropped silently (identity check below).
        self._pending: dict[tuple[Optional[str], str], Job] = {}
        self._running: dict[tuple[str, bool], Job] = {}  # (session_id, cloud) -> the job it is running
        self._results: dict[str, dict[str, dict]] = {}  # session_id -> {step_id: result}
        self._task: Optional[asyncio.Task] = None
        self._cloud_task: Optional[asyncio.Task] = None
        self._stopped = False

    def _queue_of(self, job: Job) -> "asyncio.PriorityQueue[Job]":
        return self._cloud_queue if job.cloud else self._queue

    def enqueue(
        self, priority: Priority, *, turn_id: str, session_id: Optional[str],
        step_id: str, run: RunFn, cancel: Optional[Any] = None, cloud: bool = False,
        finish: Optional[Callable[[dict], None]] = None,
    ) -> Job:
        """Queue one job. Superseding by (session_id, step_id) means: if the
        SAME step for the SAME session is already waiting (not yet picked up
        by the worker), the older entry is replaced — the turn that queued it
        is gone, only the newest data is worth running."""
        job = Job(
            priority=priority, seq=next(self._seq), turn_id=turn_id,
            session_id=session_id, step_id=step_id, run=run, cancel=cancel, cloud=cloud, finish=finish,
        )
        self._pending[(session_id, step_id)] = job
        self._queue_of(job).put_nowait(job)
        return job

    def start(self) -> asyncio.Task:
        """Idempotent: calling it again while the workers are alive is a no-op.
        Returns the local worker's task."""
        if self._task is None or self._task.done():
            self._stopped = False
            self._task = asyncio.create_task(self._worker_loop(self._queue))
        if self._cloud_task is None or self._cloud_task.done():
            self._cloud_task = asyncio.create_task(self._worker_loop(self._cloud_queue))
        return self._task

    async def stop(self) -> None:
        self._stopped = True
        for task in (self._task, self._cloud_task):
            if task is not None:
                task.cancel()
                try:
                    await task
                except asyncio.CancelledError:
                    pass
        self._task = self._cloud_task = None

    async def drain(self, *, timeout: float = 30.0) -> None:
        """Block until every job queued so far (including ones re-queued after
        a preemption) has been recorded. For tests: deterministic instead of
        `asyncio.sleep`-and-hope. Requires the worker to be running."""
        await asyncio.wait_for(asyncio.gather(self._queue.join(), self._cloud_queue.join()), timeout=timeout)

    def pending(self, session_id: Optional[str]) -> set[str]:
        return {step for (sid, step) in self._pending if sid == session_id}

    def running(self, session_id: Optional[str]) -> Optional[str]:
        if session_id is None:
            return None
        job = self._running.get((session_id, False)) or self._running.get((session_id, True))
        return job.step_id if job is not None else None

    def take_last_results(self, session_id: Optional[str]) -> dict[str, dict]:
        """Pop and return this session's finished results — read once, by the
        next turn's `emit`/headers, so the same news is never repeated."""
        if session_id is None:
            return {}
        return self._results.pop(session_id, {})

    def preempt(self, session_id: Optional[str]) -> None:
        """Signal (never force) every job — queued or running — for this
        session. A queued job that has not started yet has nothing to
        interrupt; setting its `cancel` early is harmless (its `run` sees it
        as already-cancelled and can skip its own work on entry)."""
        if session_id is None:
            return
        for job in self._pending.values():
            if job.session_id == session_id and job.cancel is not None:
                job.cancel.set()
        for cloud in (False, True):
            running = self._running.get((session_id, cloud))
            if running is not None and running.cancel is not None:
                running.cancel.set()

    def _record(self, job: Job, result: dict, started: float) -> None:
        entry = {**result, "ms": round((time.monotonic() - started) * 1000.0, 3), "at": time.time()}
        if job.session_id is not None:
            self._results.setdefault(job.session_id, {})[job.step_id] = entry
        self._log.info(
            "post_commit.job session=%s step=%s outcome=%s ms=%.1f",
            job.session_id, job.step_id, entry.get("outcome"), entry["ms"],
        )
        self._finish(job, entry)

    def _finish(self, job: Job, result: dict) -> None:
        if job.finish is None:
            return
        try:
            job.finish(result)
        except Exception as exc:
            self._log.warning("post_commit finish step=%s raised: %s", job.step_id, exc)

    async def _worker_loop(self, queue: "asyncio.PriorityQueue[Job]") -> None:
        while True:
            job = await queue.get()
            try:
                await self._run_one(job)
            finally:
                queue.task_done()

    async def _run_one(self, job: Job) -> None:
        key = (job.session_id, job.step_id)
        current = self._pending.get(key)
        if current is not job:
            # Superseded by a fresher enqueue for the same (session, step),
            # or already handled by a previous pass — drop. Only the first
            # has something to say (C5: the step's event is `superseded`).
            if current is not None:
                self._finish(job, {"outcome": "superseded"})
            return
        del self._pending[key]
        running_key = (job.session_id or "", job.cloud)
        self._running[running_key] = job
        started = time.monotonic()
        try:
            gate = self._cloud_gate if job.cloud else self._gate
            try:
                slot = await gate.acquire(job.priority, holder=job.turn_id, cancel_event=job.cancel)
            except GateBusy:
                # No timeout is ever passed for a background job — this is
                # defensive, not an expected path.
                self._record(job, {"outcome": "gate_busy"}, started)
                return
            if job.attempts and job.cancel is not None:
                # A preempted job runs again with the event the user turn set
                # still set: it gave the slot back and would give it back again
                # at once — or, on MLX, read its whole prompt (#1127) and then
                # throw the result away (review 04/10). This run is a new one.
                job.cancel.clear()
            try:
                result = await job.run(job.cancel)
            except Exception as exc:
                self._log.warning(
                    "post_commit job session=%s step=%s raised: %s",
                    job.session_id, job.step_id, exc, exc_info=True,
                )
                result = {"outcome": "failed", "error": f"{type(exc).__name__}: {exc}"}
            finally:
                await gate.release(slot)
        finally:
            self._running.pop(running_key, None)

        if result.get("outcome") == "preempted" and job.attempts + 1 < MAX_ATTEMPTS:
            job.attempts += 1
            self._pending[key] = job
            self._queue_of(job).put_nowait(job)
            return
        self._record(job, result, started)


def attach_post_commit_queue(
    server_state, *, gate: Optional[EngineGate] = None, cloud_gate: Optional[EngineGate] = None,
) -> PostCommitQueue:
    """Attach (or return the existing) PostCommitQueue — same idempotent-attach
    shape as `core.sessions.attach.attach_session_manager` / `core.turn.gate.
    attach_engine_gate`."""
    existing = getattr(server_state, "post_commit_queue", None)
    if existing is not None:
        return existing
    from core.turn.gate import attach_cloud_gate, attach_engine_gate
    queue = PostCommitQueue(
        gate if gate is not None else attach_engine_gate(server_state),
        cloud_gate=cloud_gate if cloud_gate is not None else attach_cloud_gate(server_state),
    )
    server_state.post_commit_queue = queue
    return queue


def queue_for(app_state: object) -> Optional[PostCommitQueue]:
    """The queue on `app_state.post_commit_queue`, or `None` when it is not a
    real one.

    Same defensive shape as `core.turn.gate.gate_for`, but the opposite
    fallback on purpose: the gate always needs a REAL one (an unlimited gate
    that never blocks), while here `None` is exactly right — `run_turn`/
    `stream_turn` run `memory.write`/`compact` INLINE when `post_commit` is
    `None`, which is the pre-C2.2 behaviour every existing test already
    expects. A bare `app_state` (many pre-C2.2 test files build one by hand)
    must not silently swallow these steps into a `MagicMock().enqueue(...)`
    that calls nothing — `isinstance` is what tells a real queue from that.
    """
    queue = getattr(app_state, "post_commit_queue", None)
    return queue if isinstance(queue, PostCommitQueue) else None
