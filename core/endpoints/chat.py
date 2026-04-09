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
from typing import Any

from fastapi import APIRouter, Depends, Request, BackgroundTasks
from fastapi.responses import StreamingResponse
from plugins.security.core.auth_dependencies import require_api_key
from plugins.security.core.input_sanitizers import validate_string_input, strip_memory_tags

from .chat_schemas import Message, ChatCompletionRequest
from .chat_sanitization import (
    _sanitize_rag_context,
    _sanitize_sse_token,
    _estimate_tokens,
    MAX_RAG_CONTEXT_LENGTH,
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

logger = logging.getLogger(__name__)

router = APIRouter(tags=["chat"])


# --- System Prompt ---

def _get_system_prompt(app_state: Any, lang: str = None) -> str:
    """
    Selecciona el system prompt per idioma i tier de model.

    Prioritat:
    1. server.toml [personality.prompt].<lang>_<tier>
    2. server.toml [personality.prompt].<lang>_full  (fallback de tier)
    3. server.toml [personality.prompt].en_full       (fallback neutre)
    4. Prompt mínim hardcoded
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


# --- Main Endpoint ---

@router.post("/chat/completions", dependencies=[Depends(require_api_key)], summary="Chat completion with RAG support and engine auto-routing")
@limiter.limit("20/minute")
async def chat_completions(body: ChatCompletionRequest, request: Request, background_tasks: BackgroundTasks) -> Any:
    """
    Unified Chat Completion endpoint.
    Supports:
    - RAG (Retrieval Augmented Generation)
    - Auto-routing to engines (Ollama, MLX, Llama.cpp)
    """
    # SECURITY (Bug 21): Validate all string fields against XSS, SQL injection, etc.
    # Same pattern as Web UI (plugins/web_ui_module/api/routes_chat.py:78).
    # context="chat" relaxes detectors that produce false positives in conversational text.
    if body.model is not None:
        body.model = validate_string_input(body.model, max_length=200, context="param")
    if body.engine is not None:
        body.engine = validate_string_input(body.engine, max_length=50, context="param")
    for _msg in body.messages:
        if _msg.role is not None:
            _msg.role = validate_string_input(_msg.role, max_length=50, context="param")
        if _msg.content is not None:
            # SECURITY: Strip memory injection tags BEFORE validate to match routes_chat.py pattern
            if _msg.role == "user":
                _msg.content = strip_memory_tags(_msg.content)
            _msg.content = validate_string_input(_msg.content, max_length=8000, context="chat")

    engine, preferred_fallback = _resolve_engine(body.engine, request.app.state)
    start_time = time.time()
    engine_status = "success"

    # Server language: NEXE_LANG env var (not i18n module, which tracks UI translation language)
    _server_lang = os.getenv("NEXE_LANG", "ca").split("-")[0].lower()  # "ca-ES" → "ca"

    # 2. RAG Context Injection
    context_text = ""
    if body.use_rag:
        last_user_msg = next((m.content for m in reversed(body.messages) if m.role == "user"), None)
        if last_user_msg:
            logger.info("RAG Search for: '%s'", last_user_msg[:80] + "..." if len(last_user_msg) > 80 else last_user_msg)
            context_text = await build_rag_context(last_user_msg, request.app.state, _server_lang)

    # 3. Augment System Prompt (Nexe persona + sanitized RAG context)
    messages = [m.model_dump() for m in body.messages]

    # Injectar system prompt de Nexe si el client no n'envia cap
    has_system = messages and messages[0]['role'] == 'system'
    if not has_system:
        nexe_prompt = _get_system_prompt(request.app.state, _server_lang)
        messages.insert(0, {"role": "system", "content": nexe_prompt})

    if context_text and messages:
        # SECURITY: Sanitize RAG context before injection
        safe_context = _sanitize_rag_context(context_text)

        # CONTEXT WINDOW CONTROL: Ensure RAG doesn't overflow model context
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
            # Not enough room for model response — reduce RAG further
            safe_context = safe_context[:1000]
            logger.warning("RAG context aggressively trimmed — only %s tokens remaining for response", remaining_budget)

        # Inject RAG context into the last user message (NOT system prompt)
        # This preserves prefix caching for the system prompt
        _labels = _RAG_CONTEXT_LABELS.get(_server_lang, _RAG_CONTEXT_LABELS["en"])
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

    # 4. Dispatch to Engine
    # Extract last user message for auto-save logic
    last_user_msg = next((m.content for m in reversed(body.messages) if m.role == "user"), None)

    response = None
    try:
        if engine.lower() == "ollama":
            # Pass auto-save args
            response = await _forward_to_ollama(messages, body, request.app.state, last_user_msg)
        elif engine.lower() == "mlx":
            response = await _forward_to_mlx(messages, body, request)
        elif engine.lower() in ["llama_cpp", "llama.cpp", "llamacpp"]:
            response = await _forward_to_llama_cpp(messages, body, request)
        else:
            # Default/Fallback
            response = await _forward_to_ollama(messages, body, request.app.state, last_user_msg)
    except Exception:
        engine_status = "error"
        raise
    finally:
        try:
            from core.metrics.registry import CHAT_ENGINE_REQUESTS, CHAT_ENGINE_DURATION
            CHAT_ENGINE_REQUESTS.labels(engine=engine, status=engine_status).inc()
            CHAT_ENGINE_DURATION.labels(engine=engine).observe(time.time() - start_time)
        except Exception as e:
            logger.debug("Chat engine metrics update failed: %s", e)

    # 5. Episodic Memory Storage (Auto-Save for NON-streaming)
    # Streaming responses handle their own saving inside the generator now
    if not isinstance(response, StreamingResponse):
        try:
            # Extract content from response
            content = ""
            if isinstance(response, dict):
                choices = response.get("choices", [])
                if choices:
                    content = choices[0].get("message", {}).get("content", "")

            # Try Ollama native format: {"message": {"content": "..."}}
            if not content and isinstance(response, dict):
                content = response.get("message", {}).get("content", "")

            if content and last_user_msg:
                # Add storage task
                background_tasks.add_task(
                    _save_conversation_to_memory,
                    request.app.state,
                    last_user_msg,
                    content
                )
        except Exception as e:
            logger.error("Failed to schedule memory save: %s", e)
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
