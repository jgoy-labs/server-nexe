"""The metrics of a turn, written from its events (ADR-007 §9, C5 E).

Before C5 each door counted on its own: `/v1` wrote `core_chat_engine_*` when an
engine was tried (and again for the re-prompt), the web wrote nothing. This sink
is the one place that writes them, for both doors, from the `StepEvent`s the
engine of the turn publishes:

* `core_chat_engine_requests_total{engine,status}` and
  `core_chat_engine_duration_seconds{engine}`: one per ATTEMPT an event carries
  (`generate`'s engines, the re-prompt's), the duration being the time up to the
  first event of that engine;
* `core_turn_steps_total{step,outcome}` and `core_turn_step_duration_seconds{step}`:
  one per step event;
* `core_turn_tokens_total{engine,kind}`: the tokens the engines said their calls cost,
  once per turn, from the turn's line (what was not said adds nothing).

A failed write is a debug line, never the turn's problem.
"""
from __future__ import annotations

import logging
from typing import Any

from core.turn.trace import StepEvent

logger = logging.getLogger(__name__)


class MetricsSink:
    def on_step(self, event: StepEvent) -> None:
        try:
            from core.metrics.registry import (
                CHAT_ENGINE_DURATION, CHAT_ENGINE_REQUESTS, TURN_STEP_DURATION, TURN_STEPS_TOTAL,
            )
            TURN_STEPS_TOTAL.labels(step=event.step, outcome=event.outcome).inc()
            TURN_STEP_DURATION.labels(step=event.step).observe(event.duration_ms / 1000.0)
            for attempt in event.attempts:
                CHAT_ENGINE_REQUESTS.labels(
                    engine=attempt["engine"], status="success" if attempt["ok"] else "error").inc()
                CHAT_ENGINE_DURATION.labels(engine=attempt["engine"]).observe(attempt["ms"] / 1000.0)
        except Exception as exc:
            logger.debug("turn metrics update failed: %s", exc)

    def on_turn(self, ctx: Any, line: dict) -> None:
        """The tokens the turn's engines said their calls cost (pla-tokens-reals)."""
        try:
            from core.metrics.registry import TURN_TOKENS_TOTAL
            for call in (line.get("llm") or {}).get("calls", []):
                for kind, key in (("in", "tokens_in"), ("out", "tokens_out"), ("cached", "cached_in")):
                    if call.get(key):
                        TURN_TOKENS_TOTAL.labels(engine=call.get("engine") or "", kind=kind).inc(call[key])
        except Exception as exc:
            logger.debug("turn token metrics failed: %s", exc)
