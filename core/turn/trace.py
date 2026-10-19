"""One log line per turn — the GPS becomes readable (ADR-007, C2.0).

`run_turn`/`stream_turn` already leave `ctx.outcomes` and `ctx.usage["steps"]`
(C1 §4 of the pipeline plan) — every step's outcome and timing
is on the context, and nothing outside the process could ever see it. This is
the smallest possible sink: one structured line at INFO, sourced from exactly
those two fields plus the identity `TurnContext` already carries. C5 part A
makes it a port: `StepEvent` (one per step, published where the step gets its
outcome), `TraceSink` (`on_step`, `on_turn`) and `LogSink`, which writes the line
below and is the only sink a turn has until the others (the local query, the
metrics) are added. A sink that raises is logged by name and the turn never
hears of it.

Called when the turn's wire closes, always — including a cancelled or short-
circuited one, which is why `run.py` calls this from both `run_turn`'s return
and `stream_turn`'s `finally` (after `_commit_on_cancel`, so a cancelled turn's
outcomes are already final).

And called AGAIN by each post-commit job as it finishes (#1060): `memory.write`
and `compact` run after the wire is closed, against the same `ctx`, so their
LLM calls cannot be in the first line. One turn therefore logs one line plus
one per queued step, all under the same `turn_id`; the line whose
`post_commit_pending` is empty is the turn's final bill. The alternative was
holding the trace back until the queue drained, which is the critical path
C2.2 exists to keep clear.
"""
from __future__ import annotations

import json
import logging
import time
from dataclasses import dataclass
from typing import Any, Optional, Protocol, Sequence, runtime_checkable

from core.turn.context import TurnContext

_LOGGER_NAME = "nexe.turn.trace"
logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class StepEvent:
    """What one step did, said once, when it ended (C5 part A).

    `queued` is not an event: a post-commit step is published when its job ends.
    The text of the user is never a field of it.
    """
    turn_id: str
    entry: str
    streaming: bool
    step: str
    kind: str
    started_at: float
    duration_ms: float
    outcome: str
    cancelled: bool = False
    cancel_reason: Optional[str] = None
    error_code: Optional[str] = None
    degraded_reason: Optional[str] = None
    engine: Optional[str] = None
    model: Optional[str] = None
    tokens_in: Optional[int] = None
    tokens_out: Optional[int] = None
    cached_in: Optional[int] = None
    #: The engines the step asked, in order: `{engine, ok, ms}` with `ms` up to the first
    #: event of each (C5 E; what the engine metrics are made of).
    attempts: tuple = ()
    #: Said after the wire closed (a post-commit job ended): the log writes a short
    #: line for these, `calls` being the LLM calls it made (C5 G).
    late: bool = False
    calls: tuple = ()


@runtime_checkable
class TraceSink(Protocol):
    def on_step(self, event: StepEvent) -> None: ...

    def on_turn(self, ctx: TurnContext, line: dict[str, Any]) -> None: ...


class LogSink:
    """The sink every turn has: the structured line at INFO."""

    def __init__(self, log: Optional[logging.Logger] = None) -> None:
        self._log = log

    def on_step(self, event: StepEvent) -> None:
        """One short line per post-commit job that ends (D4): the turn's long line was
        said when its wire closed and is not said again."""
        if event.late:
            (self._log or logging.getLogger(_LOGGER_NAME)).info("turn.step %s", json.dumps({
                "turn_id": event.turn_id, "step": event.step, "outcome": event.outcome,
                "ms": event.duration_ms, "calls": list(event.calls),
            }, default=str))

    def on_turn(self, ctx: TurnContext, line: dict[str, Any]) -> None:
        (self._log or logging.getLogger(_LOGGER_NAME)).info("turn.trace %s", json.dumps(line, default=str))


_DEFAULT_SINKS: tuple[TraceSink, ...] = (LogSink(),)


def sinks_for(app_state: object) -> Sequence[TraceSink]:
    """The sinks on `app_state.trace_sinks`, or the log sink alone.

    Same defensive shape as `queue_for`: a bare or mocked `app_state` (many
    tests build one by hand) must not hand the turn a `MagicMock` to publish to.
    """
    sinks = getattr(app_state, "trace_sinks", None)
    if isinstance(sinks, (tuple, list)) and sinks:
        return sinks
    return _DEFAULT_SINKS


def _engine_name(ctx: TurnContext) -> Optional[str]:
    return ctx.engine_name


def _cancel_reasons(ctx: TurnContext) -> list[str]:
    token = ctx.cancel_token
    event = token[0] if isinstance(token, (tuple, list)) and token else token
    reasons = getattr(event, "reasons", None)
    return sorted(reasons) if isinstance(reasons, (set, frozenset, list, tuple)) else []


def _error_code(ctx: TurnContext, step_id: str, error: "BaseException | str | None") -> Optional[str]:
    if isinstance(error, BaseException):
        status = getattr(error, "status_code", None)
        if isinstance(status, int):
            return f"http_{status}"
        if step_id in ("engine", "generate"):
            from core.endpoints.chat_engines.routing import classify  # deferred: endpoints → turn
            return classify(error)
        return type(error).__name__
    if ctx.error and ctx.error.get("step") == step_id:
        return ctx.error.get("class")
    return None


def note_attempt(ctx: TurnContext, step: str, engine: str, ok: bool, ms: float) -> None:
    """One engine asked by `step`, said once: the next event of that step carries it."""
    ctx.usage.setdefault("engine_attempts", []).append(
        {"step": step, "engine": engine, "ok": ok, "ms": round(ms, 3)})


def _take_attempts(ctx: TurnContext, step_id: str) -> tuple:
    pending = ctx.usage.get("engine_attempts") or []
    mine = tuple({k: v for k, v in a.items() if k != "step"} for a in pending if a.get("step") == step_id)
    if mine:
        ctx.usage["engine_attempts"] = [a for a in pending if a.get("step") != step_id]
    return mine


def _call_tokens(ctx: TurnContext, step_id: str) -> dict:
    """What the step's own LLM call cost, as the registry (`record_llm_call`) holds it.

    The latest call of the step: the step event says it once, when the step ends. A call that
    is billed after the step ended (a stream says its count at its end) is not here yet: its
    numbers are in `llm.calls` of the turn line, and the event keeps `None`.
    """
    for call in reversed((ctx.usage.get("llm") or {}).get("calls", [])):
        if call.get("step") == step_id:
            return {key: call.get(key) for key in ("tokens_in", "tokens_out", "cached_in")}
    return {}


def step_event(
    ctx: TurnContext, step_id: str, kind: str, outcome: str, duration_ms: float, *,
    error: "BaseException | str | None" = None, started_at: Optional[float] = None,
) -> StepEvent:
    reasons = _cancel_reasons(ctx)
    degraded = next((d.get("error") for d in ctx.degradations if d.get("step") == step_id), None)
    if degraded is None and outcome in ("degraded", "failed") and error is not None:
        # The engine appends to `ctx.degradations` AFTER it records the step.
        degraded = error if isinstance(error, str) else f"{type(error).__name__}: {error}"
    return StepEvent(
        turn_id=ctx.turn_id, entry=ctx.entry, streaming=ctx.streaming, step=step_id, kind=kind,
        started_at=started_at if started_at is not None else time.time() - duration_ms / 1000.0,
        duration_ms=duration_ms, outcome=outcome,
        cancelled=outcome == "cancelled" or bool(reasons), cancel_reason=",".join(reasons) or None,
        error_code=_error_code(ctx, step_id, error), degraded_reason=degraded,
        engine=_engine_name(ctx), attempts=_take_attempts(ctx, step_id), **_call_tokens(ctx, step_id),
    )


def publish_step(ctx: TurnContext, event: StepEvent) -> None:
    """Hand `event` to every sink; one that raises is named in a warning and
    the turn goes on."""
    for sink in sinks_for(ctx.app_state):
        try:
            sink.on_step(event)
        except Exception as exc:
            logger.warning("trace sink %s failed on step %s: %s", type(sink).__name__, event.step, exc)


def turn_line(ctx: TurnContext) -> dict[str, Any]:
    """The line of one finished turn (a running total while `post_commit_pending` is not empty)."""
    return {
        "turn_id": ctx.turn_id,
        "entry": ctx.entry,
        "streaming": ctx.streaming,
        "session_id": ctx.session_id,
        "engine": _engine_name(ctx),
        "engine_fallback_from": ctx.engine_fallback_from,
        # Did the turn's content go to a hosted engine (the API)? The `engine`
        # step says so, and so does any single call (`llm.calls[*].left_machine`):
        # an internal step runs on the same engine, so it counts for the turn too.
        "left_machine": bool(ctx.left_machine) or any(
            call.get("left_machine") is True for call in (ctx.usage.get("llm") or {}).get("calls", [])
        ),
        "outcomes": dict(ctx.outcomes),
        "steps": dict(ctx.usage.get("steps", {})),
        "folded": dict(ctx.usage.get("folded", {})),
        "llm": dict(ctx.usage.get("llm", {})),
        # #1060: the steps handed to the post-commit queue that have not run
        # yet. Their LLM calls land in the bucket above AFTER this line is
        # written, so while this list is non-empty `llm` is a running total,
        # not the turn's bill. Each job emits the line again when it finishes;
        # the one where this is empty is the final word on the turn.
        "post_commit_pending": list(ctx.usage.get("post_commit_pending") or []),
        "partial": bool(getattr(ctx, "partial", False)),
    }


def emit_turn_trace(ctx: TurnContext, *, log: logging.Logger | None = None) -> dict[str, Any]:
    """Build the line for one finished turn and give it to the sinks. Returns
    the dict, so a caller (or a test) can inspect it without re-parsing JSON.
    `log` writes it to that logger alone (tests)."""
    line = turn_line(ctx)
    sinks: Sequence[TraceSink] = (LogSink(log),) if log is not None else sinks_for(ctx.app_state)
    for sink in sinks:
        try:
            sink.on_turn(ctx, line)
        except Exception as exc:
            logger.warning("trace sink %s failed on turn %s: %s", type(sink).__name__, ctx.turn_id, exc)
    return line
