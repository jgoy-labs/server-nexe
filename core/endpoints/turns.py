"""
────────────────────────────────────
Server Nexe
Author: Jordi Goy
Location: core/endpoints/turns.py
Description: GET /v1/turns/{turn_id}/trace — what a recent turn did, step by step
             (ADR-007 §9, C5 F).

The id is the `X-Nexe-Turn-Id` every chat response carries. The answer comes from
the in-memory `TurnStore` (the last 256 turns of this process); the durable record
is the log. 404 when the turn is unknown or has left the ring. Behind the API key,
like `/metrics`. It never carries the user's text.

www.jgoy.net · https://server-nexe.org
────────────────────────────────────
"""
from __future__ import annotations

import re

from fastapi import APIRouter, Depends, HTTPException, Request

from core.security.auth_dependencies import require_api_key
from core.turn.turn_store import TurnStore

router = APIRouter()

_TURN_ID = re.compile(r"^[A-Za-z0-9_-]{1,64}$")


def _store(request: Request) -> TurnStore | None:
    sinks = getattr(request.app.state, "trace_sinks", None)
    if isinstance(sinks, (tuple, list)):
        return next((s for s in sinks if isinstance(s, TurnStore)), None)
    return None


@router.get(
    "/turns/{turn_id}/trace",
    dependencies=[Depends(require_api_key)],
    summary="Step-by-step trace of a recent turn",
    operation_id="turn_trace",
)
async def turn_trace(turn_id: str, request: Request) -> dict:
    store = _store(request)
    record = store.get(turn_id) if store is not None and _TURN_ID.match(turn_id) else None
    if record is None:
        raise HTTPException(status_code=404, detail="Unknown turn (or no longer kept)")
    return record
