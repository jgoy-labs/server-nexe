"""Who writes the question: the server or the model (pla-comportament-segons-mida-model, B).

Two levels, named without a «small»: the 9B is not a small model.

- `acompanyat`: the server writes the question that waits for the user's yes
  (a changed fact: «vols que ho canviï?»), because this model has not shown it
  does so reliably (9B MLX, live 16/10: it did not ask, or asked and emitted no tag).
- `autonom`: the model asks; the server only arms the change and waits.

Live matrix 17-18/10 (pla §8.9): no model asks on its own reliably — not the 27B,
not the Gemma 31B, not DeepSeek, not Claude (it asks sometimes, and says «deleted»
when nothing was). So by default EVERY model is `acompanyat`, and the API, the CLI
and the web behave the same. The cut stays as a knob: under `acompanyat_per_sota_de_b`
billion (the ACTIVE ones, for a mixture of experts) the server accompanies; from
there up, and for a cloud API, the model is `autonom`. A size nobody can read is
`acompanyat`. Configurable in `[models]` of server.toml, or `NEXE_ASSISTED_BELOW_B`.
"""
from __future__ import annotations

import logging
import os
from typing import Any, Optional

from core.turn.model_size import ModelSize, model_size

logger = logging.getLogger(__name__)

ASSISTED = "acompanyat"
AUTONOMOUS = "autonom"

#: No cut: every model is accompanied (F4, decided by Jordi 18/10).
DEFAULT_BELOW_B = float("inf")
_CONFIG_KEY = "acompanyat_per_sota_de_b"


def threshold_b(config: Optional[dict] = None) -> float:
    """The cut in billions: server.toml `[models]`, then the environment, then the default."""
    configured = ((config or {}).get("models") or {}).get(_CONFIG_KEY)
    for raw in (configured, os.getenv("NEXE_ASSISTED_BELOW_B")):
        try:
            value = float(raw)
        except (TypeError, ValueError):
            continue
        if value > 0:
            return value
    return DEFAULT_BELOW_B


def tier_of(size: ModelSize, below_b: float = DEFAULT_BELOW_B) -> str:
    if below_b == float("inf"):
        return ASSISTED
    if size.source == "api":
        return AUTONOMOUS
    weight = size.effective_b()
    if weight is None:
        return ASSISTED
    return AUTONOMOUS if weight >= below_b else ASSISTED


async def resolve(ctx: Any, engine: Optional[str], model: Optional[str], config: Optional[dict] = None) -> str:
    """The tier of the model answering this turn, worked out once and kept on the
    turn (`ctx.usage["model_tier"]`) so the log says why the server did what it did."""
    kept = ctx.usage.get("model_tier")
    if kept:
        return kept["tier"]
    size = await model_size(engine, model)
    below = threshold_b(config)
    tier = tier_of(size, below)
    ctx.usage["model_tier"] = {
        "tier": tier, "params_b": size.params_b, "active_b": size.active_b,
        "source": size.source, "below_b": below,
    }
    logger.info(
        "model tier: %s (%s %s, %s B via %s, cut %s B)",
        tier, engine, model, size.params_b, size.source, below,
    )
    return tier
