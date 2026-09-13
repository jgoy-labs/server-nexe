"""run_turn / stream_turn — the one engine that drives TURN_STEPS (ADR-007, C1.1).

C0 wrote the map (`core.turn.steps.TURN_STEPS`). This module is the engine
that walks it: one ordered pass over the steps, one failure policy, one place
that records what each step did and how long it took. A door (`/ui/chat`,
`/v1/chat/completions`) builds a `TurnContext`, hands over a table of adapters
— one callable per step id — and calls either

  * `run_turn(ctx, adapters)`     — the whole turn, no streaming: every adapter
    is awaited in order and the finished `ctx` comes back (the answer is in
    `ctx.response`, the door's wire payload in `ctx.wire`); or
  * `await stream_turn(ctx, adapters)` — the steps BEFORE `generate` run right
    away (so validation and auth errors still become proper HTTP statuses,
    before any byte of the body is committed), and what comes back is an async
    generator the door wraps in `StreamingResponse`. That generator drives the
    remaining steps in order; an adapter written as an async generator yields
    wire chunks as it works (the model's tokens, a trailing sentinel), a plain
    coroutine adapter just runs.

Failure policy (ADR-007 §8), the same in both:
  * a `must_have` step that raises stops the turn and the ORIGINAL exception
    propagates untouched — an `HTTPException` from `validate` must still reach
    FastAPI as the 400 it is;
  * an optional step that raises is recorded as degraded and the turn goes on;
  * a step may raise `TurnShortCircuit(response)` when it has answered the turn
    without generating (a memory command resolved by `intent`): the engine keeps
    the answer, skips everything that presumes a generation, and still runs
    `persist_assistant_turn` and `emit` (`AFTER_SHORT_CIRCUIT`);
  * if the client goes away mid-stream, the engine commits what was generated
    (`persist_assistant_turn`, with `outcomes["generate"] == "cancelled"` so the
    adapter can mark it partial) and runs nothing that spends an LLM call or
    writes memory (`AFTER_CANCEL`).

Post-commit steps (ADR-007 §6, C2.2): `memory.write` and `compact` never run
INLINE when a `post_commit` queue is passed in — the engine hands the adapter
to the queue instead of calling it, records "queued", and moves on. `emit`
(and the wire it built) is unaffected: the turn's answer never waited on
these two steps, only on generating it. With `post_commit=None` (the default)
they run exactly as before — every existing caller is unchanged.

The GPS is born here (ADR-007 §9, C1 §4 of the pipeline plan): every step
leaves `ctx.outcomes[id]` and `ctx.usage["steps"][id]` (ms, outcome, kind).
The `TraceSink` port (C5) will read these; nothing else is needed now.

This module imports only from `core/`. It knows nothing about plugins, memory,
FastAPI or any engine — the adapters do (C1.2 for the API, C1.3 for the UI).
"""
from __future__ import annotations

import asyncio
import inspect
import threading
import time
from typing import (
    Any, AsyncIterator, Awaitable, Callable, Iterable, Mapping, Optional,
    Sequence, TYPE_CHECKING, Union,
)

from core.turn.context import TurnContext
from core.turn.gate import Priority
from core.turn.steps import TURN_STEPS, Step
from core.turn.trace import emit_turn_trace

if TYPE_CHECKING:
    from core.turn.post_commit import PostCommitQueue

StepAdapter = Callable[[TurnContext], Awaitable[None]]
StreamingStepAdapter = Callable[[TurnContext], AsyncIterator[Any]]
Adapter = Union[StepAdapter, StreamingStepAdapter]
Adapters = Mapping[str, Adapter]

#: The first step that may put bytes on the wire. `stream_turn` runs everything
#: before it eagerly and everything from it on inside the returned generator.
STREAM_BOUNDARY = "generate"

#: Steps that still run once a step has answered the turn by itself: the answer
#: is committed to the session and sent; nothing that presumes a generation runs.
AFTER_SHORT_CIRCUIT: frozenset[str] = frozenset({"persist_assistant_turn", "emit"})

#: Steps that run when the client disconnects mid-stream: commit the partial
#: answer, spend no LLM call, write no memory.
AFTER_CANCEL: frozenset[str] = frozenset({"persist_assistant_turn"})

#: Steps that move to the background queue (ADR-007 §6, C2.2) instead of
#: running inline — never reached by AFTER_SHORT_CIRCUIT or AFTER_CANCEL, so a
#: cancelled or short-circuited turn queues neither (unchanged from before).
POST_COMMIT: frozenset[str] = frozenset({"memory.write", "compact"})


class TurnShortCircuit(Exception):
    """Raised by a step that has answered the turn without a generation.

    Not an error: a control signal. `response` is the text to persist and send;
    `reason` names why (e.g. ``"memory_intent:list"``) for the trace.
    """

    def __init__(self, response: str, *, reason: str = "") -> None:
        super().__init__(reason or "turn answered before generation")
        self.response = response
        self.reason = reason


class MissingAdapters(LookupError):
    """A door handed over a table with no adapter for one or more steps. Raised
    BEFORE any step runs: a door cannot silently "forget" a step of the turn."""

    def __init__(self, missing: Iterable[str]) -> None:
        self.missing = tuple(missing)
        super().__init__(f"no adapter for step(s): {', '.join(self.missing)}")


def _check_adapters(adapters: Adapters, steps: Sequence[Step], *, streaming: bool) -> None:
    missing = [s.id for s in steps if s.id not in adapters]
    if missing:
        raise MissingAdapters(missing)
    if not streaming:
        generators = [s.id for s in steps if inspect.isasyncgenfunction(adapters[s.id])]
        if generators:
            raise TypeError(
                "run_turn() awaits its adapters; these are async generators and "
                f"belong to stream_turn(): {generators}"
            )


def _record(ctx: TurnContext, step: Step, outcome: str, started: float, *, error: Optional[BaseException] = None) -> None:
    entry: dict[str, Any] = {
        "ms": round((time.perf_counter() - started) * 1000.0, 3),
        "outcome": outcome,
        "kind": step.kind.value,
    }
    if error is not None:
        entry["error"] = f"{type(error).__name__}: {error}"
    ctx.outcomes[step.id] = outcome
    ctx.usage.setdefault("steps", {})[step.id] = entry


def _should_queue(ctx: TurnContext, step: Step) -> bool:
    """#1040 (C2.4): a PARTIAL turn's `memory.write` is skipped, never queued —
    facts atomized from a reply that broke mid-generation are not trustworthy.
    `compact` is independent of this turn's own outcome (it summarises the
    session's history, not this reply) and always queues regardless."""
    return not (step.id == "memory.write" and ctx.partial)


def _finish_ok(ctx: TurnContext, step: Step, started: float) -> None:
    """Record a step that raised nothing. Usually "ok" — but a streaming
    `generate` step converts a mid-stream engine error into wire text instead
    of raising (the wire is already committed, so there is nothing left to
    catch), and signals it out-of-band via `ctx.error` instead (#1040, C2.4).
    A step that leaves that signal for ITSELF is recorded degraded, exactly
    like a step whose adapter raised."""
    if ctx.error is not None and ctx.error.get("step") == step.id:
        _record(ctx, step, "degraded", started)
        ctx.degradations.append({"step": step.id, "error": ctx.error.get("message", "")})
    else:
        _record(ctx, step, "ok", started)


def _mark_skipped(ctx: TurnContext, steps: Iterable[Step]) -> None:
    for step in steps:
        if step.id in ctx.outcomes:
            continue
        ctx.outcomes[step.id] = "skipped"
        ctx.usage.setdefault("steps", {})[step.id] = {"ms": 0.0, "outcome": "skipped", "kind": step.kind.value}


def _enqueue_post_commit(ctx: TurnContext, step: Step, adapter: Adapter, queue: "PostCommitQueue") -> None:
    """Hand `step`'s adapter to the post-commit queue instead of calling it.

    The adapter (coroutine or async generator, either shape) is wrapped in a
    plain callable the queue can run later, against the SAME `ctx` — safe
    because by the time the queue's worker picks this up, the turn that built
    `ctx` has already reached `emit` and nothing touches it from the door's
    side any more. The wrapper's own `cancel_event` is exposed on
    `ctx.usage["post_commit_cancel"][step.id]` — the one channel an adapter
    needs to check whether it has been asked to give up (compact/memory-write
    adapters read it; see turn_adapters.py).
    """
    cancel_event = threading.Event()
    ctx.usage.setdefault("post_commit_cancel", {})[step.id] = cancel_event
    # #1060: what this turn still owes its own trace. The line emitted when the
    # wire closes carries this list, so nobody reads its LLM totals as final.
    ctx.usage.setdefault("post_commit_pending", []).append(step.id)

    async def _run(_cancel: threading.Event) -> dict:
        try:
            if inspect.isasyncgenfunction(adapter):
                async for _ in adapter(ctx):  # type: ignore[arg-type]
                    pass
            else:
                await adapter(ctx)  # type: ignore[misc]
        except Exception as exc:
            return {"outcome": "failed", "error": f"{type(exc).__name__}: {exc}"}
        # C3.3: what the adapter did, so the NEXT turn can say it (the news of
        # a background save reaches the user one turn later — decision of
        # 06/09). `take_last_results` pops it there.
        else:
            return {
                "outcome": "preempted" if cancel_event.is_set() else "ok",
                **(ctx.usage.get("post_commit_result", {}).get(step.id) or {}),
            }
        finally:
            # #1060: this step's LLM calls landed in `ctx.usage["llm"]` AFTER
            # the turn's trace was already serialised, so that line under-
            # reported `total_calls`/`total_ms` every time in production —
            # `generate` was the only call that ever arrived on time. The trace
            # is emitted again now, same `turn_id`, and the one with an empty
            # `post_commit_pending` is the turn's final word. In the `finally`
            # so a job that failed still empties the list; a job SUPERSEDED by
            # a fresher turn never runs at all, and then the first line — which
            # names what is still pending — stays the last thing said.
            pending = ctx.usage.get("post_commit_pending") or []
            if step.id in pending:
                pending.remove(step.id)
            emit_turn_trace(ctx)

    priority = Priority.COMPACT if step.id == "compact" else Priority.MEMORY_WRITE
    queue.enqueue(
        priority, turn_id=ctx.turn_id, session_id=ctx.session_id,
        step_id=step.id, run=_run, cancel=cancel_event,
    )


async def _run_awaitable(ctx: TurnContext, step: Step, adapter: Adapter) -> Optional[TurnShortCircuit]:
    """Run one coroutine adapter under the failure policy. Returns the short-
    circuit if the step raised one; re-raises a must_have failure untouched."""
    started = time.perf_counter()
    try:
        await adapter(ctx)  # type: ignore[misc]
    except TurnShortCircuit as sc:
        ctx.response = sc.response
        _record(ctx, step, "short_circuit", started)
        return sc
    except (asyncio.CancelledError, GeneratorExit):
        _record(ctx, step, "cancelled", started)
        raise
    except Exception as exc:
        if step.must_have:
            _record(ctx, step, "failed", started, error=exc)
            raise
        _record(ctx, step, "degraded", started, error=exc)
        ctx.degradations.append({"step": step.id, "error": f"{type(exc).__name__}: {exc}"})
        return None
    _finish_ok(ctx, step, started)
    return None


async def _drive_generator(ctx: TurnContext, step: Step, adapter: StreamingStepAdapter) -> AsyncIterator[Any]:
    """Drive one async-generator adapter under the failure policy, re-yielding
    its wire chunks.

    The adapter's generator is closed explicitly on every exit. `async for`
    does NOT close an inner async generator when the loop is left early (PEP
    525): without the `aclose()` a cancelled stream would leave the engine's
    generator suspended, its own cleanup never run, and this step never
    recorded — the client would be gone and the trace would say "skipped".
    """
    started = time.perf_counter()
    agen = adapter(ctx)
    try:
        async for chunk in agen:
            yield chunk
    except TurnShortCircuit as sc:
        # A generating step that decides there is nothing to generate: keep its
        # answer; the tail (persist, emit) still runs from the caller's loop.
        ctx.response = sc.response
        _record(ctx, step, "short_circuit", started)
        return
    except (asyncio.CancelledError, GeneratorExit):
        _record(ctx, step, "cancelled", started)
        raise
    except Exception as exc:
        if step.must_have:
            _record(ctx, step, "failed", started, error=exc)
            raise
        _record(ctx, step, "degraded", started, error=exc)
        ctx.degradations.append({"step": step.id, "error": f"{type(exc).__name__}: {exc}"})
        return
    else:
        _finish_ok(ctx, step, started)
    finally:
        await agen.aclose()


def _split_on_short_circuit(remaining: Sequence[Step]) -> tuple[list[Step], list[Step]]:
    """(steps to run, steps to skip) after a short-circuit."""
    run = [s for s in remaining if s.id in AFTER_SHORT_CIRCUIT]
    skip = [s for s in remaining if s.id not in AFTER_SHORT_CIRCUIT]
    return run, skip


async def run_turn(
    ctx: TurnContext, adapters: Adapters, *,
    steps: Sequence[Step] = TURN_STEPS, post_commit: Optional["PostCommitQueue"] = None,
) -> TurnContext:
    """The whole turn, no streaming. Every adapter is a coroutine; the finished
    context comes back with `response`, `wire`, `outcomes` and `usage` filled.

    `post_commit`, when given, diverts `POST_COMMIT` steps (memory.write,
    compact) to the queue instead of awaiting them here — AFTER_SHORT_CIRCUIT
    never includes them, so the tail loop below never has to check.
    """
    _check_adapters(adapters, steps, streaming=False)
    ctx.streaming = False
    steps = list(steps)
    for index, step in enumerate(steps):
        if post_commit is not None and step.id in POST_COMMIT:
            if not _should_queue(ctx, step):
                _mark_skipped(ctx, [step])
                continue
            started = time.perf_counter()
            _enqueue_post_commit(ctx, step, adapters[step.id], post_commit)
            _record(ctx, step, "queued", started)
            continue
        sc = await _run_awaitable(ctx, step, adapters[step.id])
        if sc is None:
            continue
        run, skip = _split_on_short_circuit(steps[index + 1:])
        _mark_skipped(ctx, skip)
        for tail_step in run:
            await _run_awaitable(ctx, tail_step, adapters[tail_step.id])
        break
    emit_turn_trace(ctx)
    return ctx


async def stream_turn(
    ctx: TurnContext, adapters: Adapters, *,
    steps: Sequence[Step] = TURN_STEPS, post_commit: Optional["PostCommitQueue"] = None,
) -> AsyncIterator[Any]:
    """Run the steps before `generate` now; return the body generator.

    Everything up to (not including) `STREAM_BOUNDARY` is awaited here, so a
    failing `validate`/`authorize`/`sanitize` raises out of THIS call, before
    the door has committed a 200. The returned async generator drives the rest
    in order — awaiting coroutine adapters, re-yielding what generator adapters
    yield — and, if the consumer goes away, commits the partial answer and
    nothing else. `post_commit` is threaded through to `_run_steps`, which is
    where memory.write/compact actually live in the tail.
    """
    _check_adapters(adapters, steps, streaming=True)
    ctx.streaming = True
    steps = list(steps)
    boundary = next((i for i, s in enumerate(steps) if s.id == STREAM_BOUNDARY), len(steps))
    prefix, body_steps = steps[:boundary], steps[boundary:]

    generators_in_prefix = [s.id for s in prefix if inspect.isasyncgenfunction(adapters[s.id])]
    if generators_in_prefix:
        raise TypeError(
            "steps before the stream boundary cannot yield to the wire "
            f"(the response is not committed yet): {generators_in_prefix}"
        )

    tail: list[Step] = body_steps
    for index, step in enumerate(prefix):
        sc = await _run_awaitable(ctx, step, adapters[step.id])
        if sc is not None:
            run, skip = _split_on_short_circuit(prefix[index + 1:] + body_steps)
            _mark_skipped(ctx, skip)
            tail = run
            break

    async def _body() -> AsyncIterator[Any]:
        done: set[str] = set()
        cancelled = False
        runner: Optional[AsyncIterator[Any]] = None
        try:
            runner = _run_steps(ctx, adapters, tail, done, post_commit=post_commit)
            async for chunk in runner:
                yield chunk
            pending = [s for s in tail if s.id not in done]
            if pending:
                # A step inside the body answered the turn by itself (a
                # generator that found nothing to generate): commit and emit,
                # skip what presumes a generation.
                run, skip = _split_on_short_circuit(pending)
                _mark_skipped(ctx, skip)
                runner = _run_steps(ctx, adapters, run, done, post_commit=post_commit)
                async for chunk in runner:
                    yield chunk
        except (asyncio.CancelledError, GeneratorExit):
            cancelled = True
            if runner is not None:
                # Close the runner so the step being driven records
                # "cancelled" and the engine's own generator cleans up now,
                # not at GC time.
                await runner.aclose()  # type: ignore[union-attr]
            raise
        finally:
            if cancelled:
                await _commit_on_cancel(ctx, adapters, tail, done)
            emit_turn_trace(ctx)

    return _body()


async def _commit_on_cancel(ctx: TurnContext, adapters: Adapters, tail: Sequence[Step], done: set[str]) -> None:
    """The consumer is gone mid-stream. No `yield` is allowed any more;
    awaiting is. Commit the partial answer (`AFTER_CANCEL`), skip everything
    that would spend an LLM call or write memory."""
    pending = [s for s in tail if s.id not in done]
    for step in pending:
        if step.id in AFTER_CANCEL:
            await _run_tail_step(ctx, step, adapters[step.id])
            done.add(step.id)
    _mark_skipped(ctx, [s for s in pending if s.id not in done])


async def _run_steps(
    ctx: TurnContext, adapters: Adapters, steps: Sequence[Step], done: set[str], *,
    post_commit: Optional["PostCommitQueue"] = None,
) -> AsyncIterator[Any]:
    """Run `steps` in order inside the streamed body: a coroutine adapter is
    awaited, a generator adapter has its wire chunks re-yielded, and a
    POST_COMMIT step (when `post_commit` is given) is handed to the queue
    instead — no wire chunk, no LLM call, `done` gets it immediately. Each
    finished step is added to `done`. Stops right after a step that
    short-circuits (the caller sees it as steps left out of `done`). On
    cancel, the generator being driven is closed explicitly before the
    exception moves on (PEP 525: an interrupted `async for` closes nothing by
    itself)."""
    inner: Optional[AsyncIterator[Any]] = None
    try:
        for step in steps:
            if post_commit is not None and step.id in POST_COMMIT:
                if not _should_queue(ctx, step):
                    _mark_skipped(ctx, [step])
                    done.add(step.id)
                    continue
                started = time.perf_counter()
                _enqueue_post_commit(ctx, step, adapters[step.id], post_commit)
                _record(ctx, step, "queued", started)
                done.add(step.id)
                continue
            adapter = adapters[step.id]
            if inspect.isasyncgenfunction(adapter):
                inner = _drive_generator(ctx, step, adapter)  # type: ignore[arg-type]
                async for chunk in inner:
                    yield chunk
                inner = None
            else:
                await _run_awaitable(ctx, step, adapter)
            done.add(step.id)
            if ctx.outcomes.get(step.id) == "short_circuit":
                return
    except (asyncio.CancelledError, GeneratorExit):
        if inner is not None:
            await inner.aclose()  # type: ignore[union-attr]
        raise


async def _run_tail_step(ctx: TurnContext, step: Step, adapter: Adapter) -> None:
    """Run a tail step when its chunks cannot be forwarded (after a client
    cancel, or a short-circuit inside a generator): a coroutine adapter is
    awaited; a generator adapter is drained with its output dropped."""
    if inspect.isasyncgenfunction(adapter):
        async for _ in _drive_generator(ctx, step, adapter):  # type: ignore[arg-type]
            pass
        return
    await _run_awaitable(ctx, step, adapter)
