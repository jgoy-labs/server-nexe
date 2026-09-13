"""Cancellation propagation shared by both doors (ADR-007, C2.5).

Extracted out of the web UI's `_start_disconnect_monitor`
(`plugins/web_ui_module/api/routes_chat.py`, 2026-09-06/C1.3), which had no
plugin dependency to begin with (FastAPI's `Request`, stdlib
threading/asyncio) — the only reason `/v1` never had a disconnect monitor,
or a way to arm a deadline (C2.5), was that the mechanism lived in a module
`core/turn/` cannot import. `routes_chat.py` keeps `_start_disconnect_monitor`
as a re-export for the FD-S6 `continue` path, which still calls it directly.
"""
from __future__ import annotations

import asyncio
import logging
import threading

from fastapi import Request

logger = logging.getLogger(__name__)


def start_disconnect_monitor(request: Request) -> "tuple[threading.Event, asyncio.Task]":
    """Cancellation propagation (Bug C handoff, fix 2026-05-14): when the HTTP
    client disconnects (UI Stop button → AbortController) the event is set so the
    MLX worker thread can break out of its streaming loop instead of running to
    max_tokens. Without this, the single-worker MLX executor stays busy ~100s
    after the user clicks Stop, blocking every subsequent request.

    The SAME event is also what a deadline timer (C2.5, `core.turn.deadline`)
    sets when a turn runs too long — the engine cannot tell the two apart, and
    does not need to: either way it stops cooperatively and returns what it had.
    """
    cancel_event = threading.Event()

    async def _monitor_disconnect() -> None:
        # Poll request.is_disconnected() every 0.5s. Starlette only knows
        # the client is gone after the next ASGI receive event, so a short
        # poll cadence keeps latency low without busy-waiting.
        try:
            while not cancel_event.is_set():
                if await request.is_disconnected():
                    logger.info("Chat: client disconnected — signalling cancel to the in-process engine")
                    cancel_event.set()
                    return
                await asyncio.sleep(0.5)
        except asyncio.CancelledError:
            pass  # parent finishes normally before client disconnects

    return cancel_event, asyncio.create_task(_monitor_disconnect())
