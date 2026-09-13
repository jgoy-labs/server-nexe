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
) -> None:
    """Append one LLM call to `ctx.usage["llm"]`.

    Called from every place a turn actually pays for an inference: `generate`
    (both doors), the re-prompt (`_yield_reprompt`/`_reprompt_nonstreaming`),
    per-fact atomization (`_atomize_fact_llm`) and `compact_session` — the
    last two run inside a post-commit job (C2.2), against the SAME `ctx` the
    turn built, so their calls land in the same bucket as the inline ones.
    """
    bucket: dict[str, Any] = ctx.usage.setdefault(
        "llm", {"calls": [], "total_ms": 0.0, "total_calls": 0},
    )
    bucket["calls"].append({
        "step": step, "engine": engine, "model": model, "ms": round(ms, 3),
        "tokens_in": tokens_in, "tokens_out": tokens_out, "at": time.time(),
    })
    bucket["total_ms"] = round(bucket["total_ms"] + ms, 3)
    bucket["total_calls"] += 1
