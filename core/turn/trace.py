"""One log line per turn — the GPS becomes readable (ADR-007, C2.0).

`run_turn`/`stream_turn` already leave `ctx.outcomes` and `ctx.usage["steps"]`
(C1 §4 of the pipeline plan) — every step's outcome and timing
is on the context, and nothing outside the process could ever see it. This is
the smallest possible sink: one structured line at INFO, sourced from exactly
those two fields plus the identity `TurnContext` already carries. It is not
the `TraceSink` port C5 will build (a port needs more than one consumer to be
worth abstracting); it is what makes the columns' own data readable TODAY, and
what C5 formalises once there is a second sink to justify a port.

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
from typing import Any

from core.turn.context import TurnContext

_LOGGER_NAME = "nexe.turn.trace"


def emit_turn_trace(ctx: TurnContext, *, log: logging.Logger | None = None) -> dict[str, Any]:
    """Build and log the trace line for one finished turn. Returns the dict
    logged, so a caller (or a test) can inspect it without re-parsing JSON."""
    trace: dict[str, Any] = {
        "turn_id": ctx.turn_id,
        "entry": ctx.entry,
        "streaming": ctx.streaming,
        "session_id": ctx.session_id,
        # The two doors hold different things in `ctx.engine`: the UI door the
        # engine module, `/v1` its NAME (`served_by`, a str). `type().__name__`
        # on the second one logged the literal "str" for every API turn — the
        # field is meant to name the engine, so a name is passed through.
        "engine": (
            ctx.engine if isinstance(ctx.engine, str)
            else type(ctx.engine).__name__ if ctx.engine is not None
            else None
        ),
        "engine_fallback_from": ctx.engine_fallback_from,
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
    (log or logging.getLogger(_LOGGER_NAME)).info("turn.trace %s", json.dumps(trace, default=str))
    return trace
