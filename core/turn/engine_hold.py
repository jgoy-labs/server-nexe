"""
------------------------------------
Server Nexe
Location: core/turn/engine_hold.py
Description: What a turn holds while its engine runs: a slot of the engine
             gate, the disconnect monitor and the deadline timer. C4.8-d: one
             context manager where there used to be four copies of the same
             acquire-and-release (the web door's `generate_json` and
             `generate_stream`, the API door's `generate` and
             `_open_stream_call`). The monitor and the timer set the SAME
             cancel event, so an engine cannot tell a client that left from a
             turn that ran out of time.

www.jgoy.net · https://server-nexe.org
------------------------------------
"""

import asyncio
import logging
from typing import Any, Awaitable, Callable, Optional

from fastapi import HTTPException

from core.turn.cancel import start_disconnect_monitor
from core.turn.context import TurnContext
from core.turn.gate import GateBusy, Priority, _gate_wait_s, gate_for

logger = logging.getLogger(__name__)

#: The 429 a turn gets when no slot frees up within the gate's wait budget.
BUSY_DETAIL = "Server busy, try again in a moment"


def cancel_monitor(ctx: TurnContext) -> None:
    """Stop the turn's disconnect monitor, if it has one and it is still running."""
    token = ctx.cancel_token
    if token is None:
        return
    _event, task = token
    if task is not None and not task.done():
        task.cancel()


class EngineHold:
    """The gate slot, the disconnect monitor and the deadline timer of one turn.

    `async with EngineHold(ctx) as hold:` when the hold ends where the block
    does. A caller whose hold outlives its own frame (a streamed body that is
    drained after the step returned) uses `await hold.open()` and calls
    `await hold.release()` itself, or takes `hold.hand_over()` out of an
    `async with` block so the block no longer releases.

    `keep_monitor=True` leaves the monitor running when the hold is released:
    the web door's stream hands it to the turn's persistence, which stops it
    (`cancel_monitor`). The deadline timer and the slot are always given back.

    Busy gate: monitor and timer are stopped (the turn never starts) and the
    caller gets the 429.
    """

    def __init__(self, ctx: TurnContext, *, keep_monitor: bool = False) -> None:
        self._ctx = ctx
        self._keep_monitor = keep_monitor
        self._gate: Any = None
        self._slot: Any = None
        self._deadline: Optional[asyncio.TimerHandle] = None
        self._released = False
        self._handed = False
        self.cancel_event: Any = None
        self.monitor: Any = None

    async def open(self) -> "EngineHold":
        ctx = self._ctx
        self._gate = gate_for(ctx.app_state)
        self.cancel_event, self.monitor = start_disconnect_monitor(ctx.request)
        ctx.cancel_token = (self.cancel_event, self.monitor)
        if ctx.deadline:
            self._deadline = asyncio.get_running_loop().call_later(ctx.deadline, self.cancel_event.set)
        try:
            self._slot = await self._gate.acquire(
                Priority.USER_TURN, holder=ctx.turn_id, cancel_event=self.cancel_event, timeout=_gate_wait_s(),
            )
        except GateBusy:
            self._stop(monitor=True)
            raise HTTPException(status_code=429, detail=BUSY_DETAIL)
        except BaseException:
            # A cancel while waiting for the slot (the client left): there is
            # no hold to release, and nothing else would stop these two.
            self._stop(monitor=True)
            raise
        ctx.gpu_slot = self._slot
        return self

    def _stop(self, *, monitor: bool) -> None:
        if self._deadline is not None:
            self._deadline.cancel()
        if monitor and not self.monitor.done():
            self.monitor.cancel()

    async def release(self) -> None:
        """Stop the timer (and the monitor unless it is kept) and give the slot back. Once."""
        if self._released:
            return
        self._stop(monitor=not self._keep_monitor)
        await self._gate.release(self._slot)
        # After the await: a cancel while giving the slot back must leave a
        # second call free to try again (the gate's own release is idempotent).
        self._released = True

    def hand_over(self) -> Callable[[], Awaitable[None]]:
        """The caller now owns the release: the `async with` block will not do it."""
        self._handed = True
        return self.release

    async def __aenter__(self) -> "EngineHold":
        return await self.open()

    async def __aexit__(self, *_exc: object) -> None:
        if not self._handed:
            await self.release()
