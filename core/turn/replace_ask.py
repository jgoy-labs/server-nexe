"""The door-side half of «the server asks» (pla-comportament-segons-mida-model, C).

Both doors call this at `emit`, after `memory.write` has armed the change:
it works out the model's tier (and logs it, every turn) and returns the
question to append — empty when there is nothing waiting or the model asks by itself.
"""
from __future__ import annotations

from typing import Any, Optional

from core.turn import model_tier


async def question_for(
    ctx: Any, session: Any, engine: Optional[str], model: Optional[str], config: Optional[dict] = None,
) -> str:
    from core.memory_facts import intents  # deferred: core.memory_facts pulls the /v1 door, which imports this

    tier = await model_tier.resolve(ctx, engine, model, config)
    return intents.replace_question(session, accompany=tier == model_tier.ASSISTED, lang=getattr(ctx, "lang", None))
