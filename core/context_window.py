"""
────────────────────────────────────
Server Nexe
Author: Jordi Goy
Location: core/context_window.py
Description: #965 — one place that answers how many tokens the live engine can
    hold. Asks the engine through its own `get_context_window()` contract rather
    than keeping a copy of each engine's memory story here.

www.jgoy.net · https://server-nexe.org
────────────────────────────────────
"""

import logging
from typing import Any, Optional

from core.endpoints.chat_engines.routing import get_engine_module
from core.endpoints.chat_sanitization import DEFAULT_CONTEXT_WINDOW

logger = logging.getLogger(__name__)


def ask_engine_window(engine_module: Any) -> Optional[int]:
    """What this engine module says its window is, in tokens, or None.

    None covers every "cannot answer" alike: no module, a module from before the
    contract, one with nothing loaded, one that raised, or one that returned
    something unusable (0, a negative, a string, a bool). Callers apply their own
    default — this never invents a number.

    Single home for the ask, so the compactor, the turn budget and the RAG
    budget cannot drift into three slightly different versions of it.
    """
    getter = getattr(engine_module, "get_context_window", None) if engine_module is not None else None
    if not callable(getter):
        return None
    try:
        value = getter()
    except Exception as exc:
        logger.warning("Engine failed to report its context window: %s", exc)
        return None
    if not isinstance(value, int) or isinstance(value, bool) or value <= 0:
        if value is not None:
            logger.warning("Engine reported an unusable context window: %r", value)
        return None
    return value


def resolve_context_window(engine: str, app_state: Any = None) -> int:
    """How many tokens the engine serving this turn can actually hold.

    Deliberately free of per-engine branches: each module knows its own memory
    story (Ollama sizes by RAM, MLX by RAM *and* real model weights, llama.cpp by
    RAM since #965) and answers for itself. Adding a fourth engine means teaching
    that engine, not editing this file.

    Falls back to ``DEFAULT_CONTEXT_WINDOW`` when there is nothing live to ask —
    no app_state, module not loaded, engine that predates the contract, or a
    module that raises. Detection is a convenience: it must never be the reason
    a chat turn fails.
    """
    module = get_engine_module(engine, app_state) if app_state is not None else None
    window = ask_engine_window(module)
    if window is None:
        logger.debug(
            "Engine %s could not report a context window, using default %d",
            engine, DEFAULT_CONTEXT_WINDOW,
        )
        return DEFAULT_CONTEXT_WINDOW
    return window
