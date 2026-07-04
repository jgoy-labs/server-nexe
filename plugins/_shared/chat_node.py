"""
────────────────────────────────────
Server Nexe
Author: Jordi Goy
Location: plugins/_shared/chat_node.py
Description: Composition helpers shared by every streaming ChatNode.execute()
            (DRY: MC-030). Helpers, NOT a base class — each engine keeps its
            own divergent generation core (MLX prefix cache vs llama.cpp pool);
            only the genuinely identical boilerplate (the thread-safe stream
            bridge and the common result envelope) is centralised here.

www.jgoy.net · https://server-nexe.org
────────────────────────────────────
"""
from __future__ import annotations

import asyncio
from typing import Any, Callable, Dict, Optional


def make_threadsafe_callback(
    loop: asyncio.AbstractEventLoop,
    stream_callback: Optional[Callable[[str], None]],
) -> Callable[[str], None]:
    """Bridge streaming tokens from a blocking worker thread to the async loop.

    Returns a callable that forwards each generated piece to ``stream_callback``
    via ``loop.call_soon_threadsafe``. If ``stream_callback`` is falsy or not
    callable the forward is skipped — the same guard both engines inlined.

    Centralising this keeps the thread→loop hand-off correct in one place: the
    worker thread must NEVER call ``stream_callback`` directly (it would run UI
    work off the event loop).
    """
    def threadsafe_callback(text: str) -> None:
        if stream_callback and callable(stream_callback):
            loop.call_soon_threadsafe(stream_callback, text)

    return threadsafe_callback


def base_chat_result(
    *,
    response: str,
    model_used: str,
    elapsed_ms: int,
    tokens: int,
    tokens_per_second: float,
    prompt_tokens: int,
    context_used: int,
    system_tokens: int,
    system_prompt: str,
) -> Dict[str, Any]:
    """The result keys the MLX and llama.cpp ChatNodes return identically.

    Scope is deliberately MLX + llama.cpp only. ``OllamaNode.execute`` keeps its
    own divergent envelope (truncated ``system_prompt[:200]``, float
    ``elapsed_ms``, no ``context_used``) and must NOT be migrated onto this
    helper — its shape is genuinely different, not shared boilerplate.

    Engine-specific keys (MLX prefix-cache metrics, llama session_id/cache_hit,
    each engine's ``timing`` shape) are merged by the caller via
    ``{**base_chat_result(...), ...engine_specific}``. Only ``tokens_per_second``
    is rounded here (to 1 decimal, so every engine reports the same precision);
    every other field is passed through unchanged (e.g. ``elapsed_ms`` stays int).
    """
    return {
        "response": response,
        "model_used": model_used,
        "elapsed_ms": elapsed_ms,
        "tokens": tokens,
        "tokens_per_second": round(tokens_per_second, 1),
        "prompt_tokens": prompt_tokens,
        "context_used": context_used,
        "system_tokens": system_tokens,
        "system_prompt": system_prompt,
    }
