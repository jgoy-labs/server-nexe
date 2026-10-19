"""Cancellation propagation shared by both doors (ADR-007, C2.5).

Extracted out of the web UI's `_start_disconnect_monitor`
(`plugins/web_ui_module/api/routes_chat.py`, 2026-09-06/C1.3), which had no
plugin dependency to begin with (FastAPI's `Request`, stdlib
threading/asyncio) — the only reason `/v1` never had a disconnect monitor,
or a way to arm a deadline (C2.5), was that the mechanism lived in a module
`core/turn/` cannot import. Since C4.8-d both doors start it through
`core/turn/engine_hold.py`.
"""
from __future__ import annotations

import asyncio
import logging
import threading

from fastapi import Request

logger = logging.getLogger(__name__)

#: Why a turn's cancel event was set (C4.8 N4). An engine reads only `is_set()`
#: and stops either way; the cascade reads the reason: a client that left is
#: asked nothing more, a turn that ran out of time is still the cascade's.
CLIENT_GONE = "client_gone"
DEADLINE = "deadline"


class TurnCancel(threading.Event):
    """The turn's cancel event, every reason it was set for, and its deadline.

    Still a `threading.Event` for the engines' worker threads. `cancel(reason)`
    records why and sets it; a plain `set()` (the stream byte cap) sets it
    for no recorded reason. Reasons accumulate: a client that leaves after the
    deadline fired is still a client that left.

    Each engine the cascade asks is handed an event of its own (`attempt()`),
    linked to the turn's: whatever sets the turn's (a client that leaves, the
    byte cap) reaches it. The deadline (#1165) is per engine and watches one
    that does not START: armed when that engine is asked, disarmed by its
    first byte. An engine that is answering runs to its own end — `max_tokens`,
    a Stop, a client that leaves — and the next engine is never handed a
    deadline the one before it used up (it would answer one token and stop)."""

    def __init__(self) -> None:
        super().__init__()
        self.reasons: set[str] = set()
        self._deadline: "asyncio.TimerHandle | None" = None
        #: Seconds each engine of this turn has to its first byte; None, no deadline.
        self.deadline_s: "float | None" = None
        self._attempts: list[TurnCancel] = []
        #: For an engine's event, the turn's it was handed out by; None for the turn's own.
        self.turn: "TurnCancel | None" = None

    def set(self) -> None:
        super().set()
        for attempt in list(self._attempts):
            attempt.set()

    def cancel(self, reason: str) -> None:
        self.reasons.add(reason)
        super().set()
        for attempt in list(self._attempts):
            attempt.cancel(reason)

    def attempt(self) -> "TurnCancel":
        """The event one engine of the cascade is handed: set already if the
        turn's is (with the same reasons), set later if the turn's is, and with
        a deadline of its own up to that engine's first byte."""
        child = TurnCancel()
        child.turn = self
        child.reasons |= self.reasons
        if self.is_set():
            child.set()
        elif self.deadline_s:
            child.arm_deadline(self.deadline_s)
        self._attempts.append(child)
        return child

    def arm_deadline(self, seconds: float) -> None:
        """Set this event for DEADLINE in `seconds`, unless a first byte comes first."""
        self.disarm_deadline()
        self._deadline = asyncio.get_running_loop().call_later(seconds, self.cancel, DEADLINE)

    def disarm_deadline(self) -> None:
        """The engine's first byte (or the end of the turn's hold): the deadline
        stops watching, this event's and every engine's it handed out. Once is
        enough; again is nothing."""
        if self._deadline is not None:
            self._deadline.cancel()
            self._deadline = None
        for attempt in self._attempts:
            attempt.disarm_deadline()

    @property
    def deadline_armed(self) -> bool:
        return self._deadline is not None or any(attempt.deadline_armed for attempt in self._attempts)


def first_byte(event) -> None:
    """An engine has started answering this turn: its deadline stops watching
    (#1165). Any event without a deadline (a plain Event, none) is left alone."""
    disarm = getattr(event, "disarm_deadline", None)
    if callable(disarm):
        disarm()


def client_gone(event) -> bool:
    """Has this turn's client left? Not the same question as «is the event set»:
    a deadline sets it too, and that is not a client that left."""
    return event is not None and CLIENT_GONE in getattr(event, "reasons", ())


def start_disconnect_monitor(request: Request) -> "tuple[TurnCancel, asyncio.Task]":
    """Cancellation propagation (Bug C handoff, fix 2026-05-14): when the HTTP
    client disconnects (UI Stop button → AbortController) the event is set so the
    MLX worker thread can break out of its streaming loop instead of running to
    max_tokens. Without this, the single-worker MLX executor stays busy ~100s
    after the user clicks Stop, blocking every subsequent request.

    The SAME event is also what a deadline timer (C2.5, `core.turn.deadline`)
    sets when a turn runs too long — the engine does not tell the two apart, and
    does not need to: either way it stops cooperatively and returns what it had.
    The cascade does (`client_gone`, N4), so the event says why it was set, and
    the monitor keeps watching after a deadline: the client may still leave.
    """
    cancel_event = TurnCancel()

    async def _monitor_disconnect() -> None:
        # Poll request.is_disconnected() every 0.5s. Starlette only knows
        # the client is gone after the next ASGI receive event, so a short
        # poll cadence keeps latency low without busy-waiting.
        try:
            while not client_gone(cancel_event):
                if await request.is_disconnected():
                    logger.info("Chat: client disconnected — signalling cancel to the in-process engine")
                    cancel_event.cancel(CLIENT_GONE)
                    return
                await asyncio.sleep(0.5)
        except asyncio.CancelledError:
            pass  # parent finishes normally before client disconnects

    return cancel_event, asyncio.create_task(_monitor_disconnect())
