"""
────────────────────────────────────
Server Nexe
Author: Jordi Goy
Location: core/endpoints/chat.py
Description: Unified Chat Endpoint with RAG support & Streaming.
             Orchestrator — delegates to submodules.

www.jgoy.net · https://server-nexe.org
────────────────────────────────────
"""

import logging
import os
import time
from collections import OrderedDict
from typing import Any, Optional

from fastapi import APIRouter, Depends, Request, BackgroundTasks
from fastapi.responses import StreamingResponse
from plugins.security.core.auth_dependencies import require_api_key
from plugins.security.core.input_sanitizers import validate_string_input, strip_memory_tags

from .chat_schemas import Message, ChatCompletionRequest
from core.log_redact import redact_user_content
from .chat_sanitization import (
    append_rag_security_rule,
    _sanitize_rag_context,
    _sanitize_sse_token,
    _estimate_tokens,
    untrusted_context_turns,
    wrap_untrusted_context,
    MAX_RAG_CONTEXT_LENGTH,
    MAX_CHAT_INPUT_LENGTH,
    MAX_CONTEXT_RATIO,
    DEFAULT_CONTEXT_WINDOW,
    CHARS_PER_TOKEN_ESTIMATE,
)
from .chat_rag import (
    build_rag_context,
    _rag_result_to_text,
    _RAG_CONTEXT_LABELS,
    RAG_DOCS_THRESHOLD,
    RAG_KNOWLEDGE_THRESHOLD,
    RAG_MEMORY_THRESHOLD,
)
from .chat_memory import _save_conversation_to_memory, _pending_save_tasks
from .chat_engines.routing import (
    _normalize_engine,
    _get_preferred_engine,
    _engine_available,
    _resolve_engine,
)
from .chat_engines.ollama import (
    _forward_to_ollama,
    _ollama_stream_generator,
    _ollama_tags_cache,
    TAGS_CACHE_TTL,
    _OLLAMA_STREAM_TIMEOUT,
    _OLLAMA_ERRORS,
)
from .chat_engines.mlx import _forward_to_mlx, _mlx_stream_generator
from .chat_engines.llama_cpp import _forward_to_llama_cpp, _llama_cpp_stream_generator
from .chat_engines._common import derive_session_id
from core.dependencies import limiter
from core.lang_detect import (
    detect_user_lang_or_none as _detect_lang_or_none,
    fallback_lang as _fallback_lang,
    natural_text_len,
    prepend_language_directive,
    append_language_reminder,
)

logger = logging.getLogger(__name__)

router = APIRouter(tags=["chat"])


# --- #854: sticky reply language (same policy as #850 on the web UI route) ---
# The language decides the CRITICAL directive that OPENS the system prompt, so
# recomputing it per request rewrote the prompt from token 0 mid-conversation:
# a new trie node on MLX, _destroy + GGUF reload on llama.cpp — for the same
# session_id the engines key their prefix cache by. Policy (commit 8f67d6a6,
# #850): the fallback is returned but NEVER seeded, the switch gate measures
# the NATURAL text (code/URLs out), and a switch needs two consecutive
# detections of the same new language.
#
# This route has no ChatSession to hang the state on, so it keeps an LRU keyed
# by the very session_id the engines use (derive_session_id) — stickiness and
# prefix cache then share one scope by construction. The policy is duplicated
# rather than imported because core must not depend on a plugin; the parity
# test in tests/core/endpoints/test_f854_sticky_lang_openai.py fails if either
# copy drifts (the shared home would be core.lang_detect — see the finding).
_STICKY_LANG_MIN_SWITCH_CHARS = 25
_SESSION_LANG_MAX = 256
_SESSION_LANG: "OrderedDict[str, dict]" = OrderedDict()


def _reset_session_lang_state() -> None:
    """Drop every remembered session language — test isolation only.

    The map is process-local state with no lifecycle of its own; nothing in the
    server calls this. Tests that drive the route must, or a session language
    seeded by one test decides the system prompt of the next.
    """
    _SESSION_LANG.clear()


def _resolve_request_lang(session_key: str, user_text: str) -> str:
    """Reply language for this turn: sticky per session_key (#854).

    Mirrors plugins/web_ui_module/api/routes_chat._resolve_session_lang.
    """
    detected = _detect_lang_or_none(user_text)
    state = _SESSION_LANG.get(session_key)
    if state is None:
        # A guess never locks the session — the first REAL detection decides.
        if detected is None:
            return _fallback_lang(None)
        _SESSION_LANG[session_key] = {"lang": detected, "pending": None}
        while len(_SESSION_LANG) > _SESSION_LANG_MAX:
            _SESSION_LANG.popitem(last=False)
        return detected

    _SESSION_LANG.move_to_end(session_key)
    sticky = state["lang"]
    if (
        detected
        and detected != sticky
        and natural_text_len(user_text) >= _STICKY_LANG_MIN_SWITCH_CHARS
    ):
        if state["pending"] == detected:
            state["lang"] = detected
            state["pending"] = None
            return detected
        state["pending"] = detected
        return sticky
    if detected == sticky and state["pending"] is not None:
        state["pending"] = None  # the conversation reaffirms the sticky language
    return sticky


# --- System Prompt ---

def _get_system_prompt(app_state: Any, lang: Optional[str] = None) -> str:
    """
    Select the system prompt by language and model tier.

    Priority:
    1. server.toml [personality.prompt].<lang>_<tier>
    2. server.toml [personality.prompt].<lang>_full  (tier fallback)
    3. server.toml [personality.prompt].en_full       (neutral fallback)
    4. Hardcoded minimum prompt
    """
    if lang is None:
        lang = os.getenv("NEXE_LANG", "en")

    config = getattr(app_state, "config", {}) or {}
    prompts = config.get("personality", {}).get("prompt", {})

    tier = os.getenv("NEXE_PROMPT_TIER", "full")
    lang_short = lang.split("-")[0].lower()  # "ca-ES" → "ca"

    # Look up specific prompt → fallback to full → fallback to en → minimum
    for key in [f"{lang_short}_{tier}", f"{lang_short}_full", "en_full"]:
        prompt = prompts.get(key, "")
        if prompt:
            return prompt

    return "You are Nexe, an AI assistant. Respond clearly and helpfully."


# --- Helper Functions ---

def _validate_chat_request(body: ChatCompletionRequest) -> None:
    """Sanitize and validate all user-supplied fields in the chat request.

    user-role messages go through `apply_user_text_sanitizer`, which
    detects jailbreaks / prompt injections. High/critical → HTTP 400.
    The module does not rewrite the text (it is a detector; D-B / D-G).
    """
    if body.model is not None:
        body.model = validate_string_input(body.model, max_length=200, context="param")
    if body.engine is not None:
        body.engine = validate_string_input(body.engine, max_length=50, context="param")
    from plugins.security.sanitizer import apply_user_text_sanitizer
    for _msg in body.messages:
        if _msg.role is not None:
            _msg.role = validate_string_input(_msg.role, max_length=50, context="param")
        if _msg.content is not None:
            if _msg.role == "user":
                _msg.content = strip_memory_tags(_msg.content)
                _msg.content = apply_user_text_sanitizer(_msg.content)
            _msg.content = validate_string_input(_msg.content, max_length=MAX_CHAT_INPUT_LENGTH, context="chat")


async def _fetch_rag_context(body: ChatCompletionRequest, app_state: Any, server_lang: str) -> str:
    """Retrieve RAG context text for the last user message, if RAG is enabled."""
    if not body.use_rag:
        return ""
    last_user_msg = next((m.content for m in reversed(body.messages) if m.role == "user"), None)
    if not last_user_msg:
        return ""
    # MC-109/111: the user's message must not land in plain in the log file.
    logger.info("RAG Search for: %s", redact_user_content(last_user_msg))
    return await build_rag_context(last_user_msg, app_state, server_lang)


def _ensure_system_message(messages: list, app_state: Any, server_lang: str) -> None:
    """Prepend a system message to messages list if none is present (in-place)."""
    if not (messages and messages[0]['role'] == 'system'):
        nexe_prompt = prepend_language_directive(_get_system_prompt(app_state, server_lang), server_lang)
        nexe_prompt = append_language_reminder(nexe_prompt, server_lang)
        messages.insert(0, {"role": "system", "content": nexe_prompt})


def get_effective_context_window(engine: str) -> int:
    """MC-090: the RAG token budget must reflect the context window the serving
    engine actually uses, not a fixed 8192.

    For **Ollama** that is ``auto_num_ctx()`` (e.g. 4096 on a 16GB machine),
    capped at the configured budget so we never plan for more than the engine
    can hold (the silent-truncation bug) nor more than the user asked for. Other
    engines keep ``DEFAULT_CONTEXT_WINDOW`` for 1.0.7 — MLX's ``max_kv_size`` is
    a KV-cache budget, not a context window, so adjusting it is deferred (1.1.0).
    """
    if engine and engine.lower() == "ollama":
        try:
            from .chat_engines.ollama_helpers import auto_num_ctx
            return min(auto_num_ctx(), DEFAULT_CONTEXT_WINDOW)
        except Exception as exc:
            # Never let context-window detection (e.g. a bad NEXE_OLLAMA_NUM_CTX
            # or a psutil hiccup) break the chat request — fall back to default.
            logger.warning("Could not resolve Ollama context window, using default: %s", exc)
            return DEFAULT_CONTEXT_WINDOW
    return DEFAULT_CONTEXT_WINDOW


def _trim_rag_context(safe_context: str, messages: list, effective_ctx_window: int = None) -> str:
    """Trim RAG context to fit within the available token budget.

    ``effective_ctx_window`` (MC-090) is the real context window of the serving
    engine; when None it falls back to ``DEFAULT_CONTEXT_WINDOW`` (back-compat).
    """
    ctx_window = effective_ctx_window if effective_ctx_window is not None else DEFAULT_CONTEXT_WINDOW
    total_messages_text = "".join(m.get('content', '') for m in messages)
    used_tokens = _estimate_tokens(total_messages_text)
    max_rag_tokens = int(ctx_window * MAX_CONTEXT_RATIO)
    rag_tokens = _estimate_tokens(safe_context)

    if rag_tokens > max_rag_tokens:
        max_chars = max_rag_tokens * CHARS_PER_TOKEN_ESTIMATE
        safe_context = safe_context[:max_chars]
        logger.info("RAG context trimmed to fit context window: %s -> %s est. tokens", rag_tokens, max_rag_tokens)

    remaining_budget = ctx_window - used_tokens - _estimate_tokens(safe_context)
    if remaining_budget < 256:
        safe_context = safe_context[:1000]
        logger.warning("RAG context aggressively trimmed — only %s tokens remaining for response", remaining_budget)

    return safe_context


def _inject_rag_context_into_messages(messages: list, context_text: str, server_lang: str, effective_ctx_window: int = None) -> None:
    """Inject RAG context as its own turn pair before the last user message (in-place).

    B030 (RT-01): the retrieved content is wrapped in nonce'd delimiters with a
    data-not-instructions intro, and the system message gets the static RAG
    security rule. _sanitize_rag_context escapes forged delimiters inside the
    content, so only this runtime can emit a valid [CONTEXT <id>] pair.

    B030 layer 2d (turn separation): the wrapped block travels in a separate
    user turn + assistant data-only acknowledgement, inserted BEFORE the last
    user message — the user's question arrives clean and keeps its authority,
    instead of the document speaking with the user's voice.
    """
    if not (context_text and messages):
        return
    safe_context = _sanitize_rag_context(context_text)
    safe_context = _trim_rag_context(safe_context, messages, effective_ctx_window)
    _labels = _RAG_CONTEXT_LABELS.get(server_lang, _RAG_CONTEXT_LABELS["en"])
    _instruction = _labels["intro"]
    wrapped = wrap_untrusted_context(f"{_instruction}\n{safe_context}", server_lang)
    for i in range(len(messages) - 1, -1, -1):
        if messages[i]['role'] == 'user':
            messages[i:i] = untrusted_context_turns(wrapped, server_lang)
            break
    # #851: la regla de seguretat s'arma INCONDICIONALMENT al caller
    # (_build_rag_and_system_prompt) — aquí només corria amb context i
    # partia el namespace de la caché de prefix entre torns amb/sense RAG.


async def _build_rag_and_system_prompt(
    body: ChatCompletionRequest, app_state: Any, server_lang: str, effective_ctx_window: int = None
) -> tuple[list[dict], str]:
    """Build the final messages list with system prompt and injected RAG context.

    ``effective_ctx_window`` (MC-090) is the serving engine's real context window,
    used to size the RAG token budget; None falls back to DEFAULT_CONTEXT_WINDOW.

    Returns:
        Tuple of (messages, raw_context_text).
    """
    context_text = await _fetch_rag_context(body, app_state, server_lang)

    messages = [m.model_dump() for m in body.messages]

    _ensure_system_message(messages, app_state, server_lang)

    _inject_rag_context_into_messages(messages, context_text, server_lang, effective_ctx_window)

    # #851: static data-not-instructions rule, UNCONDITIONAL (parity with the
    # web UI route via the shared helper) — a conditional suffix split the
    # prefix-cache namespace between RAG and non-RAG turns.
    if messages and messages[0]['role'] == 'system':
        messages[0]['content'] = append_rag_security_rule(messages[0]['content'], server_lang)

    return messages, context_text


async def _dispatch_to_engine(
    engine: str, messages: list[dict], body: ChatCompletionRequest,
    request: Request, app_state: Any, last_user_msg: Optional[str]
) -> Any:
    """Route the chat request to the resolved backend engine (Ollama, MLX, or llama.cpp)."""
    if engine.lower() == "ollama":
        return await _forward_to_ollama(messages, body, app_state, last_user_msg)
    elif engine.lower() == "mlx":
        return await _forward_to_mlx(messages, body, request)
    elif engine.lower() in ["llama_cpp", "llama.cpp", "llamacpp"]:
        return await _forward_to_llama_cpp(messages, body, request)
    else:
        return await _forward_to_ollama(messages, body, app_state, last_user_msg)


def _record_engine_metrics(engine: str, engine_status: str, start_time: float) -> None:
    """Emit Prometheus counters and histogram for the chat engine invocation."""
    try:
        from core.metrics.registry import CHAT_ENGINE_REQUESTS, CHAT_ENGINE_DURATION
        CHAT_ENGINE_REQUESTS.labels(engine=engine, status=engine_status).inc()
        CHAT_ENGINE_DURATION.labels(engine=engine).observe(time.time() - start_time)
    except Exception as e:
        logger.debug("Chat engine metrics update failed: %s", e)


def _schedule_episodic_memory(
    response: Any, background_tasks: BackgroundTasks,
    app_state: Any, last_user_msg: Optional[str]
) -> None:
    """Queue a background task to save the conversation turn to episodic memory."""
    if not isinstance(response, StreamingResponse):
        try:
            content = ""
            if isinstance(response, dict):
                choices = response.get("choices", [])
                if choices:
                    content = choices[0].get("message", {}).get("content", "")
            if not content and isinstance(response, dict):
                content = response.get("message", {}).get("content", "")
            if content and last_user_msg:
                background_tasks.add_task(
                    _save_conversation_to_memory,
                    app_state,
                    last_user_msg,
                    content
                )
        except Exception as e:
            logger.error("Failed to schedule memory save: %s", e, exc_info=True)


def _inject_response_headers(
    response: Any, engine: str, context_text: str, preferred_fallback: Optional[str]
) -> Any:
    """Add ``X-Nexe-*`` headers (engine, RAG status, fallback) to the response."""
    if isinstance(response, StreamingResponse):
        if "X-Nexe-Engine" not in response.headers:
            response.headers["X-Nexe-Engine"] = engine
        response.headers["X-Nexe-RAG-Status"] = "active" if context_text else "inactive"
        if preferred_fallback and "X-Nexe-Fallback-From" not in response.headers:
            response.headers["X-Nexe-Fallback-From"] = preferred_fallback
            response.headers["X-Nexe-Fallback-Reason"] = "preferred_unavailable"
    elif isinstance(response, dict):
        response.setdefault("nexe_engine", engine)
        response.setdefault("nexe_rag_status", "active" if context_text else "inactive")
        if preferred_fallback:
            response.setdefault(
                "nexe_fallback",
                {"from": preferred_fallback, "to": engine, "reason": "preferred_unavailable"},
            )
    return response


# --- Main Endpoint ---

@router.post("/chat/completions", dependencies=[Depends(require_api_key)], summary="Chat completion with RAG support and engine auto-routing", operation_id="chat_completions")
@limiter.limit("20/minute")
async def chat_completions(body: ChatCompletionRequest, request: Request, background_tasks: BackgroundTasks) -> Any:
    """
    Unified Chat Completion endpoint.
    Supports:
    - RAG (Retrieval Augmented Generation)
    - Auto-routing to engines (Ollama, MLX, Llama.cpp)
    """
    _validate_chat_request(body)

    engine, preferred_fallback = _resolve_engine(body.engine, request.app.state)
    start_time = time.time()
    engine_status = "success"

    last_user_msg = next((m.content for m in reversed(body.messages) if m.role == "user"), None)

    # Reply language follows the user's message (not just the install language),
    # sticky per session so a short ack cannot rewrite the system prompt from
    # token 0 halfway through a conversation (#854).
    _server_lang = _resolve_request_lang(derive_session_id(request), last_user_msg or "")

    # MC-090: size the RAG budget to the engine's real context window (Ollama).
    _effective_ctx = get_effective_context_window(engine)
    messages, context_text = await _build_rag_and_system_prompt(body, request.app.state, _server_lang, _effective_ctx)

    response = None
    try:
        response = await _dispatch_to_engine(engine, messages, body, request, request.app.state, last_user_msg)
    except Exception:
        engine_status = "error"
        raise
    finally:
        _record_engine_metrics(engine, engine_status, start_time)

    _schedule_episodic_memory(response, background_tasks, request.app.state, last_user_msg)

    return _inject_response_headers(response, engine, context_text, preferred_fallback)


# Re-exports for backwards compatibility (used by tests and other modules
# that import from core.endpoints.chat instead of the original submodule).
# Adding __all__ silences ruff F401 for these intentional re-exports.
__all__ = [
    "router",
    "chat_completions",
    # Re-exported from .chat_schemas
    "Message",
    "ChatCompletionRequest",
    # Re-exported from .chat_sanitization
    "_sanitize_rag_context",
    "_sanitize_sse_token",
    "_estimate_tokens",
    "MAX_RAG_CONTEXT_LENGTH",
    "MAX_CONTEXT_RATIO",
    "DEFAULT_CONTEXT_WINDOW",
    "CHARS_PER_TOKEN_ESTIMATE",
    # Re-exported from .chat_rag
    "build_rag_context",
    "_rag_result_to_text",
    "_RAG_CONTEXT_LABELS",
    "RAG_DOCS_THRESHOLD",
    "RAG_KNOWLEDGE_THRESHOLD",
    "RAG_MEMORY_THRESHOLD",
    # Re-exported from .chat_memory
    "_save_conversation_to_memory",
    "_pending_save_tasks",
    # Re-exported from .chat_engines.routing
    "_normalize_engine",
    "_get_preferred_engine",
    "_engine_available",
    "_resolve_engine",
    # Re-exported from .chat_engines.ollama
    "_forward_to_ollama",
    "_ollama_stream_generator",
    "_ollama_tags_cache",
    "TAGS_CACHE_TTL",
    "_OLLAMA_STREAM_TIMEOUT",
    "_OLLAMA_ERRORS",
    # Re-exported from .chat_engines.mlx
    "_forward_to_mlx",
    "_mlx_stream_generator",
    # Re-exported from .chat_engines.llama_cpp
    "_forward_to_llama_cpp",
    "_llama_cpp_stream_generator",
]
