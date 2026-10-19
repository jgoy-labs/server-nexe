"""I8 (ADR-007 §6, C2.5): every LLM call of a turn, counted.

Before this, `ctx.usage["steps"]` (C0/C1) knew how long each STEP of the
pipeline took, but a single step can spend more than one LLM call —
`generate`'s cascade retries, a background `memory.write` atomizing several
facts, a `compact` summarisation, a re-prompt when the reply was only
`[MEM_SAVE: ...]`. None of that showed up anywhere. This module only
MEASURES (like the GPS, C0 §4): no limit is imposed here, because there is
no data yet to size one against. A budget enforced on guessed numbers would
either block legitimate long turns or let runaway ones through by accident —
C2.0's own lesson for the deadline default.
"""
from __future__ import annotations

import time
from typing import Any, Optional

from core.turn.context import TurnContext


def record_llm_call(
    ctx: TurnContext, *, step: str, engine: str, model: Optional[str] = None,
    ms: float, tokens_in: Optional[int] = None, tokens_out: Optional[int] = None,
    cached_in: Optional[int] = None, outcome: str = "ok",
) -> None:
    """Append one LLM call to `ctx.usage["llm"]`.

    Called from every place a turn actually pays for an inference: `generate`
    (both doors), the re-prompt (`core.turn.policy.reprompt_chunks`, both doors
    since C4.5 — and only when an engine was really asked),
    per-fact atomization (`_atomize_fact_llm`) and `compact_session` — the
    last two run inside a post-commit job (C2.2), against the SAME `ctx` the
    turn built, so their calls land in the same bucket as the inline ones.
    `outcome` is `ok`, or `cancelled` for a call a client stopped.
    """
    bucket: dict[str, Any] = ctx.usage.setdefault(
        "llm", {"calls": [], "total_ms": 0.0, "total_calls": 0},
    )
    from core.endpoints.chat_engines.routing import engine_is_cloud  # deferred: endpoints → turn

    bucket["calls"].append({
        "step": step, "engine": engine, "model": model, "ms": round(ms, 3),
        "tokens_in": tokens_in, "tokens_out": tokens_out, "cached_in": cached_in, "at": time.time(),
        # `cancelled` (C5 C): the engine was asked and the client stopped it; the call
        # still cost what it cost up to there (I8: the bill is whole).
        "outcome": outcome,
        # Whether what this call was sent left the machine: every internal step
        # (compaction, re-prompt, description) is its own call to the provider.
        "left_machine": engine_is_cloud(engine),
    })
    bucket["total_ms"] = round(bucket["total_ms"] + ms, 3)
    bucket["total_calls"] += 1


def note_usage(ctx: TurnContext, usage: Optional[dict], *, step: str = "generate") -> None:
    """Fill in what the engine said once it said it (a stream says it at the end).

    The call is recorded when the engine takes it, long before a stream is over,
    so the numbers arrive after the fact: they go on the LATEST call of `step`
    that has none yet. Nothing said (`None`) leaves the call as it is; a number
    already there is never overwritten.
    """
    if not usage:
        return
    for call in reversed((ctx.usage.get("llm") or {}).get("calls", [])):
        if call.get("step") != step:
            continue
        for key in ("tokens_in", "tokens_out", "cached_in"):
            if call.get(key) is None and usage.get(key) is not None:
                call[key] = usage[key]
        return


def footer_usage(ctx: TurnContext, usage: Optional[dict]) -> Optional[dict]:
    """The count that belongs to the text the client was shown, or None.

    A re-prompt replaces the answer (the first reply was only memory tags) and a
    resume (Continue) generates only the tail: the first call's tokens, or the
    tail's, are not the shown answer's, so the footer estimates instead.
    """
    if ctx.resume:
        return None
    calls = (ctx.usage.get("llm") or {}).get("calls", [])
    return None if any(c.get("step") == "reprompt" for c in calls) else usage
