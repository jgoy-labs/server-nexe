"""The last turns' traces, in memory, by `turn_id` (ADR-007 §9, C5 F).

A sink of the TraceSink port. A turn is in it from its FIRST event, so one that
hangs is seen while it hangs; the post-commit jobs of the same turn are added to
the same record when they end; the record is `final` when nothing is pending any
more (a job that a fresher turn superseded stops being pending). A ring of
`CAPACITY` turns: the oldest goes out first. The durable record is the log; this
is the answer to «what is that turn doing?», for the API (`GET /v1/turns/{id}/trace`)
and for tests.

What it holds is what the events and the line say: ids, steps, outcomes, times,
engines. Never the text of the user, nor the answer.
"""
from __future__ import annotations

import threading
from collections import OrderedDict
from dataclasses import asdict
from typing import Any, Optional

from core.turn.trace import StepEvent

CAPACITY = 256


class TurnStore:
    def __init__(self, capacity: int = CAPACITY) -> None:
        self._capacity = capacity
        self._turns: "OrderedDict[str, dict[str, Any]]" = OrderedDict()
        self._lock = threading.Lock()

    def _record(self, turn_id: str, entry: str, streaming: bool) -> dict[str, Any]:
        record = self._turns.get(turn_id)
        if record is None:
            record = {
                "turn_id": turn_id, "entry": entry, "streaming": streaming, "final": False,
                "steps": [], "pending": [], "engine": None, "engine_fallback_from": None,
                "left_machine": False, "partial": False, "llm": {},
            }
            self._turns[turn_id] = record
            while len(self._turns) > self._capacity:
                self._turns.popitem(last=False)
        return record

    def on_step(self, event: StepEvent) -> None:
        with self._lock:
            if event.late and event.turn_id not in self._turns:
                return  # a job of a turn that has left the ring does not bring it back
            record = self._record(event.turn_id, event.entry, event.streaming)
            shown = asdict(event)
            # The reason says WHAT failed, not the exception's words: those can repeat what the
            # user wrote (a validation error quotes its input). The log keeps them, as before.
            shown["degraded_reason"] = (event.degraded_reason or "").split(":", 1)[0] or None
            record["steps"] = [s for s in record["steps"] if s["step"] != event.step] + [shown]
            if event.step in record["pending"]:
                record["pending"].remove(event.step)
            record["engine"] = event.engine or record["engine"]
            if event.late and event.calls:  # the job's calls arrive after the turn's line
                self._add_late_calls(record, event.calls)
            record["final"] = self._done(record)

    @staticmethod
    def _add_late_calls(record: dict, calls: tuple) -> None:
        llm = record["llm"] = dict(record["llm"] or {"calls": [], "total_ms": 0.0, "total_calls": 0})
        known = {(c.get("step"), c.get("at")) for c in llm.get("calls", [])}
        new = [c for c in calls if (c.get("step"), c.get("at")) not in known]  # the turn's line may have them
        llm["calls"] = [*llm.get("calls", []), *new]
        llm["total_calls"] = llm.get("total_calls", 0) + len(new)
        llm["total_ms"] = round(llm.get("total_ms", 0.0) + sum(c.get("ms", 0.0) for c in new), 3)

    def on_turn(self, ctx: Any, line: dict) -> None:
        with self._lock:
            record = self._record(line["turn_id"], line["entry"], line["streaming"])
            for key in ("engine", "engine_fallback_from", "left_machine", "partial"):
                record[key] = line[key]
            record["llm"] = {**line["llm"], "calls": list((line["llm"] or {}).get("calls", []))}
            # What the line says is still pending, minus what already ended here.
            ended = {s["step"] for s in record["steps"]}
            record["pending"] = [s for s in line["post_commit_pending"] if s not in ended]
            record["final"] = self._done(record)

    @staticmethod
    def _done(record: dict) -> bool:
        if not record["steps"] or record["pending"]:
            return False
        # A turn that fell at a step it could not do without never reaches `emit`.
        return "emit" in {s["step"] for s in record["steps"]} or any(s["outcome"] == "failed" for s in record["steps"])

    def get(self, turn_id: str) -> Optional[dict[str, Any]]:
        with self._lock:
            record = self._turns.get(turn_id)
            return None if record is None else {**record, "steps": list(record["steps"]), "pending": list(record["pending"])}
