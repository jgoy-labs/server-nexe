"""
────────────────────────────────────
Server Nexe
Author: Jordi Goy
Location: core/turn/lease.py
Description: A turn that fails lets go of its session (#1105, ADR-007 §11).

The `session` step takes the session's lease; until now only three places gave
it back — `emit` (the turn answered), the client-disconnect path and a memory
command's short-circuit. A turn that FAILED after `session` (the engine gate
busy → 429, no engine → 503, an engine error → 4xx) left it held for its whole
TTL (600 s), and the user's next message in that conversation was refused
with the 409 meant for "open on another device".

Both doors wrap their turn with these two helpers. `release_lease` is
turn-scoped, so releasing is harmless when the turn never took the lease, has
already released it, or was the one refused with a 409 (the lease is another
turn's, and stays).

www.jgoy.net · https://server-nexe.org
────────────────────────────────────
"""
from __future__ import annotations

from typing import Any, AsyncIterator

from core.turn.context import TurnContext


def release_turn_lease(session_mgr: Any, ctx: TurnContext) -> None:
    """Give back this turn's lease, if it holds one."""
    if session_mgr is None or not ctx.session_id:
        return
    session_mgr.release_lease(ctx.session_id, ctx.turn_id)


async def releasing(body: AsyncIterator[Any], session_mgr: Any, ctx: TurnContext) -> AsyncIterator[Any]:
    """The streamed body, with the lease given back however it ends.

    The steps from `generate` on run inside the body, after the response has
    been committed — a failure there raises out of this generator, not out of
    the door. The inner body is closed first, so its own cancel path (commit
    the partial answer) runs before the session is let go.
    """
    try:
        async for chunk in body:
            yield chunk
    finally:
        try:
            aclose = getattr(body, "aclose", None)
            if aclose is not None:
                await aclose()
        finally:
            release_turn_lease(session_mgr, ctx)
