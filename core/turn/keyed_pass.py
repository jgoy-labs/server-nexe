"""
────────────────────────────────────
Server Nexe
Author: Jordi Goy
Location: core/turn/keyed_pass.py
Description: The second pass of `memory.write`: read the user's message for keyed
facts (core.memory_facts.keyed) with the engine that answered, for either door.

The model's own [MEM_SAVE] tags are the fallback, not the rule: when this pass
found facts they replace the tags of the turn; when it found none (or could not
run) the tags go through the old path untouched.

www.jgoy.net · https://server-nexe.org
────────────────────────────────────
"""

from __future__ import annotations

import inspect
import logging
import os
import time
from typing import Any

from core.env_utils import parse_truthy
from core.turn.budget import record_llm_call
from core.turn.gate import GateBusy, Priority, _gate_wait_s, gate_for

logger = logging.getLogger(__name__)


def _keyed():
    from core.memory_facts import keyed  # deferred: core.memory_facts reaches the doors (circle)

    return keyed


def enabled() -> bool:
    """One global switch for both doors. Default on."""
    return parse_truthy(os.environ.get("NEXE_MEMORY_KEYED", "true"))


def _signature(engine: Any):
    try:
        return inspect.signature(engine.chat)
    except (TypeError, ValueError):
        return None


def _should_run(ctx, engine, port, rag_collections) -> bool:
    from core.memory_facts.write import memory_saves_enabled  # deferred, as `_keyed`

    if not enabled() or engine is None or not hasattr(engine, "chat") or port is None:
        return False
    if getattr(ctx, "resume", False) or ctx.usage.get("saved_by_intent"):
        return False  # a resumed answer has no new message; D6 already saved this one
    return memory_saves_enabled(rag_collections)


async def _read(ctx, engine, engine_name: str, model_name: str, port):
    """The model's reading of the message: (facts, ran). `ran` is False when the engine
    was busy and nothing was asked."""
    keyed = _keyed()
    gate = gate_for(ctx.app_state, engine)
    try:
        slot = await gate.acquire(Priority.USER_TURN, holder=ctx.turn_id, timeout=_gate_wait_s())
    except GateBusy:
        return None, False  # busy: the tags still work
    started = time.monotonic()
    try:
        from core.endpoints.chat_engines.routing import engine_is_cloud  # deferred: endpoints → turn

        known = await keyed.stored_keyed(port)
        if engine_is_cloud(engine_name):
            # The names of what is stored help the model keep one name per thing; the
            # values stay home — and so do facts about other people: the provider gets
            # the user's message, not the profile.
            known = [{**row, "value": ""} for row in known if row.get("entity") == "user"]
        facts = await keyed.extract(engine, model_name, _signature(engine), ctx.message, known)
    finally:
        await gate.release(slot)
    record_llm_call(
        ctx, step="memory.write", engine=engine_name, model=model_name or None,
        ms=(time.monotonic() - started) * 1000.0,
    )
    return facts, True


async def run(
    ctx, *, engine, engine_name: str, model_name: str, session, port, rag_collections=None,
):
    """The keyed facts of this turn's message, applied. `handled=False` when the
    pass did not run or found nothing to keep — the caller then uses the tags."""
    keyed = _keyed()
    if not _should_run(ctx, engine, port, rag_collections):
        return keyed.KeyedOutcome()
    facts, ran = await _read(ctx, engine, engine_name, model_name, port)
    if not ran:
        return keyed.KeyedOutcome()
    usable = [f for f in (facts or []) if f.intent != "delete"]
    logger.info(
        "keyed pass (%s): %s fact(s) kept of the message, %d to apply",
        engine_name, "no" if facts is None else len(facts), len(usable),
    )
    if not usable:
        return keyed.KeyedOutcome()
    outcome = await keyed.apply(usable, session, port, rag_collections=rag_collections)
    # The model's tags that these facts do not account for still go the old way.
    ctx.facts = keyed.uncovered(list(ctx.facts or []), usable)
    return outcome
