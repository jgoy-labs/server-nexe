"""The turn's envelope (ADR-007 §3, D2 of the workflow-engine plan).

`TurnContext` is what a door fills with identity + payload before the turn
starts, and what every step of `core.turn.steps.TURN_STEPS` reads from and
writes to. It replaces, once C1 builds `run_turn()`, the 18-odd values each
door assembles by hand today (`StreamingChatContext` at
`plugins/web_ui_module/api/routes_chat.py:2158`, and the loose locals
`chat_completions` builds at `core/endpoints/chat.py`).

This module has no behaviour: no method does I/O, no field is validated here.
The engine is `core.turn.run`; this is only the shape.

Two groups of fields are transitional and say so: the door hands over the raw
`body`/`request`/`app_state` it received because the functions the C1 adapters
wrap (`_validate_chat_request(body)`, `derive_session_id(request, …)`,
`resolve_engine_cascade(…, app_state)`) take exactly those today. As blocks
move into `core/` for real (C3, C4) the adapters stop needing them and they go.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Optional


@dataclass
class TurnContext:
    # --- Identity: filled by the door, read-only from here on ---
    turn_id: str
    session_id: Optional[str] = None
    entry: str = ""  # "ui" | "api" — the DOOR, not the wire format (streaming
    # vs JSON is an `emit`-time detail, not a different turn: ADR-007 rule #2
    # of the pipeline plan §3).
    principal: Optional[str] = None
    pipeline_version: int = 1
    streaming: bool = False  # set by run_turn/stream_turn, not by the door
    # C4.6: this turn RESUMES the session's last (truncated) assistant answer
    # instead of answering a new user message (FD-S6, the web door's
    # Continue). A property of the turn, not of the door: the steps read it.
    resume: bool = False

    # --- Given by the door, transitional (see module docstring) ---
    body: Any = None        # the request body as received (pydantic model or dict)
    request: Any = None     # the framework request (only for functions that still take it)
    app_state: Any = None   # `request.app.state`: config, modules, session_manager

    # --- Turn state: built up step by step, in the order of TURN_STEPS ---
    message: str = ""
    attachments: dict = field(default_factory=dict)
    session: Any = None     # the live session object (written by the `session` step)
    lang: Optional[str] = None  # the turn's reply language, sticky per session (written by `session`)
    intent: Optional[str] = None
    recall: list = field(default_factory=list)          # [(collection, score), ...]
    recall_text: str = ""                                # the retrieved text the model was GIVEN ("" if none/dropped)
    history: list = field(default_factory=list)
    clock_line: str = ""
    system_prompt: str = ""
    prompt: list = field(default_factory=list)
    response: str = ""
    facts: list = field(default_factory=list)

    # --- Control ---
    cancel_token: Optional[Any] = None
    deadline: Optional[float] = None
    trace_id: Optional[str] = None

    # --- Resources ---
    engine: Optional[Any] = None                 # the engine that serves (name today; a port handle later)
    gpu_slot: Optional[Any] = None
    context_window: Optional[int] = None         # the serving engine's window, sizes the budget
    engine_fallback_from: Optional[str] = None   # the engine asked for, when another one answered
    engine_fallback_reason: str = "preferred_unavailable"

    # --- Result: what run_turn fills and TraceSink (C5) will read ---
    wire: Any = None        # the door's payload built by `emit` (non-streaming)
    outcomes: dict = field(default_factory=dict)      # step id -> ok|degraded|failed|skipped|short_circuit|cancelled
    degradations: list = field(default_factory=list)  # [{"step": id, "error": "..."}]
    usage: dict = field(default_factory=dict)         # {"steps": {id: {"ms", "outcome", "kind"}}, ...}
    # #1040 (C2.4): an error mid-stream, after tokens already reached the
    # client, cannot be retried (the wire is committed) — it ends the turn
    # PARTIAL rather than complete. `error` classifies it (ADR-007 §8):
    # {"step", "class", "message"} with class in {UserFixable, Retryable,
    # Fatal}. A partial turn is persisted as such and queues no memory.write
    # (facts extracted from a broken reply are not trustworthy).
    partial: bool = False
    error: Optional[dict] = None

    # --- What this turn has actually written, field by field (C4.3-c) ---
    # `TURN_STEPS` declares what each step writes. Until now nothing checked
    # it: `FOLDED_BASELINE` counted a bucket (`usage["folded"]`) that no
    # production line ever wrote to, so a step could be folded back into a
    # no-op and the contract test stayed green. The engine now compares the
    # fields a step REALLY wrote against the ones it declares, and for that it
    # needs writes recorded as they happen — not values sampled before and
    # after, which cannot tell "wrote the empty string" from "wrote nothing"
    # (`clock_line` is `""` on most turns, and that IS the step doing its job).
    #
    # Populated by `__post_init__`, so the door's own constructor arguments are
    # NOT counted: those are given, not written by a step.

    def __post_init__(self) -> None:
        object.__setattr__(self, "_written", set())

    def __setattr__(self, name: str, value: Any) -> None:
        object.__setattr__(self, name, value)
        written = self.__dict__.get("_written")
        if written is not None and not name.startswith("_"):
            written.add(name)

    def begin_step(self) -> None:
        """Start recording afresh for the step about to run.

        The record is per step, not cumulative: `sanitize` rewriting `message`
        after `validate` already wrote it has to count as a write, and a
        running total cannot see that — the field is already in the set.
        """
        written = self.__dict__.get("_written")
        if written is None:
            object.__setattr__(self, "_written", set())
        else:
            written.clear()

    @property
    def written_fields(self) -> frozenset:
        """The context fields assigned since the last `begin_step()`.

        A step that mutates a field in place (`ctx.usage[...] = x`) does not
        appear here — only rebinding does. That is why `steps.py` declares a
        field in `writes` only when the step assigns it.
        """
        return frozenset(self.__dict__.get("_written", ()))
