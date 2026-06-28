"""
------------------------------------
Server Nexe
Author: Jordi Goy
Location: core/endpoints/chat_engines/_common.py
Description: Shared helpers for engine forwarding (MLX, Llama.cpp).

Extracts duplicated logic: message parsing, session ID derivation,
OpenAI response formatting, and Ollama fallback.

www.jgoy.net · https://server-nexe.org
------------------------------------
"""

import hashlib
import logging
import time
import uuid
from pathlib import Path
from typing import Dict, List, Optional, Tuple

from fastapi import Request

from ..chat_sanitization import _sanitize_sse_token

logger = logging.getLogger(__name__)


def extract_last_user_msg(messages: List[Dict]) -> Optional[str]:
    """Return the content of the last user message, or None."""
    return next(
        (m.get("content") for m in reversed(messages) if m.get("role") == "user"),
        None,
    )


def separate_messages(messages: List[Dict]) -> Tuple[str, List[Dict]]:
    """Split messages into (system_msg, user_messages).

    System messages are concatenated into a single string; all other
    messages are returned unchanged in order.
    """
    system_msg = ""
    user_messages = []
    for msg in messages:
        if msg.get("role") == "system":
            system_msg = msg.get("content", "")
        else:
            user_messages.append(msg)
    return system_msg, user_messages


def derive_session_id(req: Request) -> str:
    """Derive session_id from X-Session-Id header or API key hash."""
    _api_key = (req.headers.get("x-api-key") or req.headers.get("authorization", "")).encode()
    return req.headers.get("x-session-id") or f"sess_{hashlib.sha256(_api_key).hexdigest()[:16]}"


def resolve_loaded_model_name(module, fallback: str) -> str:
    """Return the basename of the model actually loaded by a single-model engine.

    MLX and llama.cpp run one fixed model (NEXE_MLX_MODEL / NEXE_LLAMA_CPP_MODEL)
    and ignore the per-request ``model`` field. Echoing ``request.model`` back
    would lie about which model answered (B075-C3): a client asking for
    ``"gpt-4"`` would see ``"gpt-4"`` while a local Qwen/Gemma actually ran.

    This returns the real loaded model's *basename* — never the absolute
    ``model_path``, which leaks the home directory (see the warnings in each
    engine's ``config.py``). When no model is loaded (e.g. ``_node`` is ``None``
    pre-onboarding) it falls back to the stable engine literal, matching the
    previous behaviour for the unconfigured case.
    """
    node = getattr(module, "_node", None)
    model_path = getattr(getattr(node, "config", None), "model_path", "")
    if isinstance(model_path, str) and model_path:
        return Path(model_path).name
    return fallback


def build_openai_response(result: dict, model_name: str, engine_prefix: str) -> dict:
    """Build an OpenAI-compatible chat completion response from an engine result."""
    return {
        "id": f"{engine_prefix}-{uuid.uuid4().hex}",
        "object": "chat.completion",
        "created": int(time.time()),
        "model": model_name,
        "choices": [{
            "index": 0,
            "message": {
                "role": "assistant",
                "content": _sanitize_sse_token(result.get("response", "")),
            },
            "finish_reason": "stop",
        }],
        "usage": {
            "prompt_tokens": result.get("prompt_tokens", 0),
            "completion_tokens": result.get("tokens", 0),
            "total_tokens": result.get("context_used", 0),
        },
    }


async def _forward_to_ollama_lazy(messages, request, *, app_state, user_msg, fallback_from, fallback_reason):
    """Lazy-import wrapper to avoid circular imports with ollama.py."""
    from .ollama import _forward_to_ollama
    return await _forward_to_ollama(
        messages, request,
        app_state=app_state,
        user_msg=user_msg,
        fallback_from=fallback_from,
        fallback_reason=fallback_reason,
    )


async def fallback_to_ollama(messages, request, app_state, user_msg, from_engine: str, reason: str):
    """Forward to Ollama as a fallback. Uses lazy import to avoid circular deps."""
    return await _forward_to_ollama_lazy(
        messages, request,
        app_state=app_state,
        user_msg=user_msg,
        fallback_from=from_engine,
        fallback_reason=reason,
    )
