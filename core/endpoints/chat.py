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
from typing import Any, Optional

from fastapi import APIRouter, Depends, HTTPException, Request, BackgroundTasks
from fastapi.responses import StreamingResponse
from plugins.security.core.auth_dependencies import require_api_key
from plugins.security.core.input_sanitizers import validate_string_input, strip_memory_tags

from .chat_schemas import Message, ChatCompletionRequest
from .chat_sanitization import (
    _sanitize_rag_context,
    _sanitize_sse_token,
    _estimate_tokens,
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
from core.dependencies import limiter
from core.lang_detect import detect_user_lang, prepend_language_directive, append_language_reminder

logger = logging.getLogger(__name__)

router = APIRouter(tags=["chat"])


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

    user-role messages are now also passed
    through `SanitizerModule.sanitize()` which detects technical prompt
    injections / jailbreak patterns before the text reaches the
    philosophical modules downstream. The sanitizer is allowed to either
    rewrite the content (`clean_text`) or, when `needs_intervention` is
    set with a `high`/`critical` severity, raise an HTTPException to
    short-circuit the request. Lower severities log a warning but let the
    request continue so legitimate users are not blocked by false
    positives in the pattern set.
    """
    if body.model is not None:
        body.model = validate_string_input(body.model, max_length=200, context="param")
    if body.engine is not None:
        body.engine = validate_string_input(body.engine, max_length=50, context="param")
    sanitizer = None
    try:
        from plugins.security.sanitizer import get_sanitizer
        sanitizer = get_sanitizer()
    except Exception as exc:
        logger.debug(
            "SanitizerModule unavailable, falling back to legacy validation only: %s",
            exc,
        )
    for _msg in body.messages:
        if _msg.role is not None:
            _msg.role = validate_string_input(_msg.role, max_length=50, context="param")
        if _msg.content is not None:
            if _msg.role == "user":
                _msg.content = strip_memory_tags(_msg.content)
                if sanitizer is not None:
                    try:
                        result = sanitizer.sanitize(_msg.content)
                        if result.severity in ("high", "critical"):
                            logger.warning(
                                "SanitizerModule blocked %s-severity input (threats=%s, patterns=%s)",
                                result.severity,
                                result.threats_detected,
                                result.patterns_matched,
                            )
                            raise HTTPException(
                                status_code=400,
                                detail={
                                    "error": "input_rejected_by_sanitizer",
                                    "severity": result.severity,
                                    "threats": result.threats_detected,
                                },
                            )
                        if not result.is_safe:
                            logger.info(
                                "SanitizerModule rewrote user input (severity=%s, threats=%s)",
                                result.severity,
                                result.threats_detected,
                            )
                        _msg.content = result.clean_text
                    except HTTPException:
                        raise
                    except Exception as exc:
                        logger.warning(
                            "SanitizerModule.sanitize raised, keeping legacy-validated content: %s",
                            exc,
                        )
            _msg.content = validate_string_input(_msg.content, max_length=MAX_CHAT_INPUT_LENGTH, context="chat")


async def _fetch_rag_context(body: ChatCompletionRequest, app_state: Any, server_lang: str) -> str:
    """Retrieve RAG context text for the last user message, if RAG is enabled."""
    if not body.use_rag:
        return ""
    last_user_msg = next((m.content for m in reversed(body.messages) if m.role == "user"), None)
    if not last_user_msg:
        return ""
    logger.info("RAG Search for: '%s'", last_user_msg[:80] + "..." if len(last_user_msg) > 80 else last_user_msg)
    return await build_rag_context(last_user_msg, app_state, server_lang)


def _ensure_system_message(messages: list, app_state: Any, server_lang: str) -> None:
    """Prepend a system message to messages list if none is present (in-place)."""
    if not (messages and messages[0]['role'] == 'system'):
        nexe_prompt = prepend_language_directive(_get_system_prompt(app_state, server_lang), server_lang)
        nexe_prompt = append_language_reminder(nexe_prompt, server_lang)
        messages.insert(0, {"role": "system", "content": nexe_prompt})


def _trim_rag_context(safe_context: str, messages: list) -> str:
    """Trim RAG context to fit within the available token budget."""
    total_messages_text = "".join(m.get('content', '') for m in messages)
    used_tokens = _estimate_tokens(total_messages_text)
    max_rag_tokens = int(DEFAULT_CONTEXT_WINDOW * MAX_CONTEXT_RATIO)
    rag_tokens = _estimate_tokens(safe_context)

    if rag_tokens > max_rag_tokens:
        max_chars = max_rag_tokens * CHARS_PER_TOKEN_ESTIMATE
        safe_context = safe_context[:max_chars]
        logger.info("RAG context trimmed to fit context window: %s -> %s est. tokens", rag_tokens, max_rag_tokens)

    remaining_budget = DEFAULT_CONTEXT_WINDOW - used_tokens - _estimate_tokens(safe_context)
    if remaining_budget < 256:
        safe_context = safe_context[:1000]
        logger.warning("RAG context aggressively trimmed — only %s tokens remaining for response", remaining_budget)

    return safe_context


def _inject_rag_context_into_messages(messages: list, context_text: str, server_lang: str) -> None:
    """Inject RAG context into the last user message (in-place)."""
    if not (context_text and messages):
        return
    safe_context = _sanitize_rag_context(context_text)
    safe_context = _trim_rag_context(safe_context, messages)
    _labels = _RAG_CONTEXT_LABELS.get(server_lang, _RAG_CONTEXT_LABELS["en"])
    _instruction = _labels["intro"]
    for i in range(len(messages) - 1, -1, -1):
        if messages[i]['role'] == 'user':
            messages[i]['content'] = (
                f"[{_labels['docs']}]\n"
                f"{_instruction}\n"
                f"{safe_context}\n"
                f"[/CONTEXT]\n\n"
                f"{messages[i]['content']}"
            )
            break


async def _build_rag_and_system_prompt(
    body: ChatCompletionRequest, app_state: Any, server_lang: str
) -> tuple[list[dict], str]:
    """Build the final messages list with system prompt and injected RAG context.

    Returns:
        Tuple of (messages, raw_context_text).
    """
    context_text = await _fetch_rag_context(body, app_state, server_lang)

    messages = [m.model_dump() for m in body.messages]

    _ensure_system_message(messages, app_state, server_lang)

    _inject_rag_context_into_messages(messages, context_text, server_lang)

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
            logger.error("Failed to schedule memory save: %s", e)


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

    # Reply language follows the user's message (not just the install language).
    _server_lang = detect_user_lang(last_user_msg or "", fallback=os.getenv("NEXE_LANG", "en"))

    messages, context_text = await _build_rag_and_system_prompt(body, request.app.state, _server_lang)

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
