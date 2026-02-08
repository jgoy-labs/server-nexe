"""
────────────────────────────────────
Server Nexe
Version: 0.8
Author: Jordi Goy 
Location: core/endpoints/chat.py
Description: Unified Chat Endpoint with RAG support & Streaming.

www.jgoy.net
────────────────────────────────────
"""

from fastapi import APIRouter, HTTPException, Request, Depends, BackgroundTasks
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, ConfigDict, Field
from typing import List, Optional, Dict, Any, Union
import asyncio
import logging
import httpx
import json
import time
import uuid
from datetime import datetime, timezone
from plugins.security.core.auth_dependencies import require_api_key
from memory.memory.models.memory_entry import MemoryEntry
from memory.rag_sources.base import SearchRequest
from personality.i18n.resolve import t_modular

logger = logging.getLogger(__name__)

router = APIRouter(tags=["chat"])

# ═══════════════════════════════════════════════════════════════════════════
# RAG CONTEXT SANITIZATION - Prevent prompt injection via retrieved content
# ═══════════════════════════════════════════════════════════════════════════
import re

# Maximum characters for RAG context injection
MAX_RAG_CONTEXT_LENGTH = 4000

# Patterns that could indicate prompt injection attempts in retrieved content
_RAG_INJECTION_PATTERNS = [
    re.compile(r'\[/?INST\]', re.IGNORECASE),           # Instruction markers
    re.compile(r'<\|/?system\|>', re.IGNORECASE),       # System role markers
    re.compile(r'<\|/?user\|>', re.IGNORECASE),         # User role markers
    re.compile(r'<\|/?assistant\|>', re.IGNORECASE),    # Assistant role markers
    re.compile(r'###\s*(system|user|assistant)', re.IGNORECASE),  # Role headers
    re.compile(r'\[CONTEXT[^\]]*\]', re.IGNORECASE),    # Our own context markers
]

def _sanitize_rag_context(context: str, truncation_marker: str = "[...truncated]") -> str:
    """
    Sanitize RAG retrieved content before injecting into prompt.

    SECURITY: RAG content comes from user-stored data and could contain
    prompt injection attempts. This function:
    1. Truncates to MAX_RAG_CONTEXT_LENGTH
    2. Removes known prompt injection patterns
    3. Escapes delimiter characters

    Args:
        context: Raw context text from RAG retrieval

    Returns:
        Sanitized context safe for prompt injection
    """
    if not context:
        return ""

    # 1. Truncate to prevent context overflow
    sanitized = context[:MAX_RAG_CONTEXT_LENGTH]
    if len(context) > MAX_RAG_CONTEXT_LENGTH:
        sanitized += "\n" + truncation_marker
        logger.warning(_t_global(
            "context_truncated",
            "RAG context truncated from {original} to {max} chars",
            original=len(context),
            max=MAX_RAG_CONTEXT_LENGTH,
        ))

    # 2. Remove prompt injection patterns
    for pattern in _RAG_INJECTION_PATTERNS:
        sanitized = pattern.sub('[FILTERED]', sanitized)

    # 3. Escape our own delimiter markers to prevent context breakout
    sanitized = sanitized.replace('[/CONTEXT]', '[/CONTEXT_ESCAPED]')
    sanitized = sanitized.replace('[CONTEXT', '[CONTEXT_ESCAPED')

    return sanitized

def _t_from_state(app_state, key: str, fallback: str, **kwargs) -> str:
    """Translate using app_state.i18n with fallback."""
    try:
        i18n = getattr(app_state, "i18n", None) if app_state else None
        if not i18n:
            return fallback.format(**kwargs) if kwargs else fallback
        value = i18n.t(key, **kwargs)
        if value == key:
            return fallback.format(**kwargs) if kwargs else fallback
        return value
    except Exception:
        return fallback.format(**kwargs) if kwargs else fallback

def _t_global(key: str, fallback: str, **kwargs) -> str:
    """Translate using modular i18n without app_state (fallback safe)."""
    return t_modular(f"core.chat.{key}", fallback, **kwargs)

# --- Memory command helpers (HTTP /v1/chat/completions) ---

def _parse_memory_command(text: Optional[str]) -> Optional[Dict[str, str]]:
    if not text:
        return None
    stripped = text.strip()
    if not stripped.startswith("/"):
        return None
    parts = stripped.split(maxsplit=1)
    cmd = parts[0][1:].lower()
    arg = parts[1].strip() if len(parts) > 1 else ""

    save_aliases = {"save", "guardar", "recorda"}
    recall_aliases = {"recall"}

    if cmd in save_aliases:
        return {"action": "save", "arg": arg}
    if cmd in recall_aliases:
        return {"action": "recall", "arg": arg}
    return None

def _memory_stream_response(text: str, model_name: str = "nexe-memory"):
    async def _gen():
        chunk = {
            "id": f"memory-{uuid.uuid4().hex}",
            "object": "chat.completion.chunk",
            "created": int(time.time()),
            "model": model_name,
            "choices": [{
                "index": 0,
                "delta": {"content": text},
                "finish_reason": None
            }]
        }
        yield f"data: {json.dumps(chunk)}\n\n"
        final_chunk = {
            "id": f"memory-{uuid.uuid4().hex}",
            "object": "chat.completion.chunk",
            "created": int(time.time()),
            "model": model_name,
            "choices": [{
                "index": 0,
                "delta": {},
                "finish_reason": "stop"
            }]
        }
        yield f"data: {json.dumps(final_chunk)}\n\n"
        yield "data: [DONE]\n\n"

    return StreamingResponse(
        _gen(),
        media_type="text/event-stream",
        headers={"X-Nexe-Engine": "memory"},
    )

def _memory_nonstream_response(text: str, model_name: str = "nexe-memory") -> Dict[str, Any]:
    return {
        "id": f"memory-{uuid.uuid4().hex}",
        "object": "chat.completion",
        "created": int(time.time()),
        "model": model_name,
        "choices": [{
            "index": 0,
            "message": {"role": "assistant", "content": text},
            "finish_reason": "stop"
        }],
        "usage": {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0},
        "nexe_engine": "memory",
    }

async def _handle_memory_command(
    cmd: Dict[str, str],
    request: ChatCompletionRequest,
    app_state=None,
) -> Union[Dict[str, Any], StreamingResponse]:
    action = cmd.get("action")
    arg = cmd.get("arg", "")

    if action == "save":
        if not arg:
            msg = _t_from_state(
                app_state,
                "core.chat.memory_save_missing",
                "Missing text. Usage: /save <text>"
            )
            return _memory_stream_response(msg) if request.stream else _memory_nonstream_response(msg)

        from memory.memory.api.v1 import get_memory_api
        memory = await get_memory_api()

        if not await memory.collection_exists("nexe_chat_memory"):
            await memory.create_collection("nexe_chat_memory", vector_size=384)

        await memory.store(
            text=arg,
            collection="nexe_chat_memory",
            metadata={
                "type": "manual_save",
                "source": "chat-api",
                "timestamp": datetime.now(timezone.utc).isoformat(),
            }
        )

        msg = _t_from_state(
            app_state,
            "core.chat.memory_save_ok",
            "Saved to memory."
        )
        return _memory_stream_response(msg) if request.stream else _memory_nonstream_response(msg)

    if action == "recall":
        if not arg:
            msg = _t_from_state(
                app_state,
                "core.chat.memory_recall_missing",
                "Missing query. Usage: /recall <query>"
            )
            return _memory_stream_response(msg) if request.stream else _memory_nonstream_response(msg)

        from memory.memory.api.v1 import get_memory_api
        memory = await get_memory_api()

        if not await memory.collection_exists("nexe_chat_memory"):
            msg = _t_from_state(
                app_state,
                "core.chat.memory_recall_empty",
                "Nothing found in memory."
            )
            return _memory_stream_response(msg) if request.stream else _memory_nonstream_response(msg)

        results = await memory.search(query=arg, collection="nexe_chat_memory", top_k=3, threshold=0.3)
        if not results:
            msg = _t_from_state(
                app_state,
                "core.chat.memory_recall_empty",
                "Nothing found in memory."
            )
            return _memory_stream_response(msg) if request.stream else _memory_nonstream_response(msg)

        lines = []
        for r in results[:3]:
            text = getattr(r, "text", "") or ""
            compact = " ".join(text.split())
            if len(compact) > 160:
                compact = compact[:157] + "..."
            lines.append(f"- {compact}")

        header = _t_from_state(
            app_state,
            "core.chat.memory_recall_found",
            "Found in memory:"
        )
        msg = header + "\n" + "\n".join(lines)
        return _memory_stream_response(msg) if request.stream else _memory_nonstream_response(msg)

    # Unknown command -> let normal chat handle it
    return None

# --- Schemas ---

class Message(BaseModel):
    role: str
    content: str
    
    model_config = ConfigDict(protected_namespaces=())

class ChatCompletionRequest(BaseModel):
    messages: List[Message]
    model: Optional[str] = None
    engine: Optional[str] = "auto"
    stream: bool = False
    use_rag: bool = True  # RAG enabled by default - searches nexe_documentation + nexe_chat_memory
    temperature: float = Field(default=0.7, ge=0.0, le=2.0)  # Validated range
    max_tokens: Optional[int] = Field(default=None, ge=1, le=32000)  # Prevent DoS via huge values

    model_config = ConfigDict(protected_namespaces=())

# --- Router Logic ---

def _normalize_engine(engine: Optional[str]) -> Optional[str]:
    if not engine:
        return None
    value = engine.strip().lower()
    if value in {"llama.cpp", "llama-cpp", "llamacpp"}:
        return "llama_cpp"
    return value

def _get_preferred_engine(app_state) -> Optional[str]:
    """
    Get preferred engine from:
    1. NEXE_MODEL_ENGINE env variable (set by installer)
    2. Config file fallback
    """
    import os

    # Priority 1: Environment variable (set by installer in .env)
    env_engine = os.environ.get("NEXE_MODEL_ENGINE")
    if env_engine:
        return env_engine

    # Priority 2: Config file
    config = getattr(app_state, "config", {}) or {}
    return config.get("plugins", {}).get("models", {}).get("preferred_engine")

def _engine_available(engine: str, app_state) -> bool:
    modules = getattr(app_state, "modules", {}) or {}
    if engine == "ollama":
        return "ollama_module" in modules
    if engine == "mlx":
        return "mlx_module" in modules
    if engine == "llama_cpp":
        return "llama_cpp_module" in modules
    return False

def _resolve_engine(request_engine: Optional[str], app_state) -> tuple[str, Optional[str]]:
    requested = _normalize_engine(request_engine)
    if requested and requested != "auto":
        return requested, None

    preferred = _normalize_engine(_get_preferred_engine(app_state))
    if preferred and preferred != "auto":
        if _engine_available(preferred, app_state):
            return preferred, None
        logger.warning(_t_from_state(
            app_state,
            "core.chat.preferred_engine_unavailable",
            "Preferred engine '{engine}' not available, falling back",
            engine=preferred,
        ))
        for candidate in ["mlx", "llama_cpp", "ollama"]:
            if _engine_available(candidate, app_state):
                return candidate, preferred

    for candidate in ["mlx", "llama_cpp", "ollama"]:
        if _engine_available(candidate, app_state):
            return candidate, None

    return "ollama", None

def _rag_result_to_text(result: Any) -> str:
    """Normalize RAG results to plain text for context injection."""
    if isinstance(result, dict):
        return result.get("content") or result.get("text") or str(result)
    if hasattr(result, "text"):
        return result.text
    return str(result)

@router.post("/chat/completions", dependencies=[Depends(require_api_key)])
async def chat_completions(request: ChatCompletionRequest, req: Request, background_tasks: BackgroundTasks):
    """
    Unified Chat Completion endpoint.
    Supports:
    - RAG (Retrieval Augmented Generation)
    - Auto-routing to engines (Ollama, MLX, Llama.cpp)
    """
    engine, preferred_fallback = _resolve_engine(request.engine, req.app.state)
    start_time = time.time()
    engine_status = "success"

    # Detect memory commands (/save, /recall) before RAG/engine routing
    last_user_msg = next((m.content for m in reversed(request.messages) if m.role == "user"), None)
    mem_cmd = _parse_memory_command(last_user_msg)
    if mem_cmd:
        mem_response = await _handle_memory_command(mem_cmd, request, req.app.state)
        if mem_response is not None:
            return mem_response

    # 2. RAG Context Injection
    context_text = ""
    if request.use_rag:
        try:
            # Extract last user message for query
            if last_user_msg:
                logger.info(_t_from_state(
                    req.app.state,
                    "core.chat.rag_search",
                    "RAG Search for: '{query}'",
                    query=last_user_msg,
                ))

                # Try MemoryAPI first (same as /v1/memory/store uses)
                try:
                    from memory.memory.api.v1 import get_memory_api
                    memory = await get_memory_api()

                    all_results = []

                    # 1. Search documentation first (nexe_documentation)
                    try:
                        if await memory.collection_exists("nexe_documentation"):
                            doc_results = await memory.search(
                                query=last_user_msg,
                                collection="nexe_documentation",
                                top_k=3,
                                threshold=0.4
                            )
                            if doc_results:
                                all_results.extend(doc_results)
                                logger.info(_t_from_state(
                                    req.app.state,
                                    "core.chat.rag_docs_found",
                                    "RAG: Found {count} docs from documentation",
                                    count=len(doc_results),
                                ))
                    except Exception as e:
                        logger.debug(_t_from_state(
                            req.app.state,
                            "core.chat.rag_docs_failed",
                            "RAG docs search failed: {error}",
                            error=str(e),
                        ))

                    # 2. Search user knowledge (custom documents in knowledge/ folder)
                    try:
                        if await memory.collection_exists("user_knowledge"):
                            knowledge_results = await memory.search(
                                query=last_user_msg,
                                collection="user_knowledge",
                                top_k=3,
                                threshold=0.35
                            )
                            if knowledge_results:
                                all_results.extend(knowledge_results)
                                logger.info(_t_from_state(
                                    req.app.state,
                                    "core.chat.rag_knowledge_found",
                                    "RAG: Found {count} docs from user knowledge",
                                    count=len(knowledge_results),
                                ))
                    except Exception as e:
                        logger.debug(_t_from_state(
                            req.app.state,
                            "core.chat.rag_knowledge_failed",
                            "RAG knowledge search failed: {error}",
                            error=str(e),
                        ))

                    # 3. Search user memory (nexe_chat_memory - conversations)
                    try:
                        if await memory.collection_exists("nexe_chat_memory"):
                            mem_results = await memory.search(
                                query=last_user_msg,
                                collection="nexe_chat_memory",
                                top_k=2,
                                threshold=0.3
                            )
                            if mem_results:
                                all_results.extend(mem_results)
                                logger.info(_t_from_state(
                                    req.app.state,
                                    "core.chat.rag_memory_found",
                                    "RAG: Found {count} docs from chat memory",
                                    count=len(mem_results),
                                ))
                    except Exception as e:
                        logger.debug(_t_from_state(
                            req.app.state,
                            "core.chat.rag_memory_failed",
                            "RAG chat memory search failed: {error}",
                            error=str(e),
                        ))

                    if all_results:
                        # Build context with clear source headers
                        context_parts = []
                        for r in all_results[:5]:
                            source = getattr(r, 'metadata', {}).get('source', 'unknown') if hasattr(r, 'metadata') else 'unknown'
                            context_parts.append(f"[Font: {source}]\n{r.text}")
                        context_text = "\n\n".join(context_parts)
                        logger.info(_t_from_state(
                            req.app.state,
                            "core.chat.rag_context_memoryapi",
                            "RAG Context found (MemoryAPI): {chars} chars, {count} results",
                            chars=len(context_text),
                            count=len(all_results),
                        ))
                except Exception as mem_err:
                    logger.debug(_t_from_state(
                        req.app.state,
                        "core.chat.memory_api_not_available",
                        "MemoryAPI not available: {error}",
                        error=str(mem_err),
                    ))

                    # Fallback to RAG module if MemoryAPI fails
                    rag_module = None
                    if hasattr(req.app.state, 'modules'):
                        rag_module = req.app.state.modules.get('rag')

                    if rag_module and hasattr(rag_module, 'search'):
                        search_request = SearchRequest(query=last_user_msg, top_k=3)
                        results = await rag_module.search(search_request, source="personality")

                        if results:
                            if isinstance(results, list):
                                context_text = "\n".join([_rag_result_to_text(r) for r in results])
                            else:
                                context_text = str(results)
                            logger.info(_t_from_state(
                                req.app.state,
                                "core.chat.rag_context_module",
                                "RAG Context found (RAG module): {chars} chars",
                                chars=len(context_text),
                            ))
                        else:
                            logger.info(_t_from_state(
                                req.app.state,
                                "core.chat.rag_no_results",
                                "RAG Search returned no results",
                            ))
                    else:
                        logger.debug(_t_from_state(
                            req.app.state,
                            "core.chat.rag_no_source",
                            "No RAG source available",
                        ))

        except Exception as e:
            logger.error(_t_from_state(
                req.app.state,
                "core.chat.rag_error",
                "RAG Error: {error}",
                error=str(e),
            ))
            # Continue without context rather than failing

    # 3. Augment System Prompt (with sanitized RAG context)
    messages = [m.model_dump() for m in request.messages]
    if context_text and messages:
        # SECURITY: Sanitize RAG context before injection
        truncation_marker = _t_from_state(
            req.app.state,
            "core.chat.context_truncated_marker",
            "[...truncated]",
        )
        safe_context = _sanitize_rag_context(context_text, truncation_marker=truncation_marker)
        context_header = _t_from_state(
            req.app.state,
            "core.chat.context_header",
            "[CONTEXT MEMORY]",
        )
        context_instruction = _t_from_state(
            req.app.state,
            "core.chat.context_instruction",
            "Use this retrieved information if relevant:",
        )
        context_footer = _t_from_state(
            req.app.state,
            "core.chat.context_footer",
            "[/CONTEXT]",
        )
        context_block = f"{context_header}\n{context_instruction}\n{safe_context}\n{context_footer}"

        # Find system prompt or insert one
        if messages[0]['role'] == 'system':
            messages[0]['content'] += f"\n\n{context_block}"
        else:
            messages.insert(0, {"role": "system", "content": context_block})

    # 4. Dispatch to Engine
    # last_user_msg already resolved above for auto-save logic

    response = None
    try:
        if engine.lower() == "ollama":
            # Pass auto-save args
            response = await _forward_to_ollama(messages, request, req.app.state, last_user_msg)
        elif engine.lower() == "mlx":
            response = await _forward_to_mlx(messages, request, req)
        elif engine.lower() in ["llama_cpp", "llama.cpp", "llamacpp"]:
            response = await _forward_to_llama_cpp(messages, request, req)
        else:
            # Default/Fallback
            response = await _forward_to_ollama(messages, request, req.app.state, last_user_msg)
    except Exception:
        engine_status = "error"
        raise
    finally:
        try:
            from core.metrics.registry import CHAT_ENGINE_REQUESTS, CHAT_ENGINE_DURATION
            CHAT_ENGINE_REQUESTS.labels(engine=engine, status=engine_status).inc()
            CHAT_ENGINE_DURATION.labels(engine=engine).observe(time.time() - start_time)
        except Exception as e:
            logger.debug(_t_from_state(
                req.app.state,
                "core.chat.metrics_update_failed",
                "Chat engine metrics update failed: {error}",
                error=str(e),
            ))

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
            
            if content and last_user_msg:
                # Add storage task
                background_tasks.add_task(
                    _save_conversation_to_memory,
                    req.app.state,
                    last_user_msg,
                    content
                )
        except Exception as e:
            logger.error(_t_from_state(
                req.app.state,
                "core.chat.autosave_schedule_failed",
                "Failed to schedule memory save: {error}",
                error=str(e),
            ))
    if isinstance(response, StreamingResponse):
        if "X-Nexe-Engine" not in response.headers:
            response.headers["X-Nexe-Engine"] = engine
        if preferred_fallback and "X-Nexe-Fallback-From" not in response.headers:
            response.headers["X-Nexe-Fallback-From"] = preferred_fallback
            response.headers["X-Nexe-Fallback-Reason"] = "preferred_unavailable"
    elif isinstance(response, dict):
        response.setdefault("nexe_engine", engine)
        if preferred_fallback:
            response.setdefault(
                "nexe_fallback",
                {"from": preferred_fallback, "to": engine, "reason": "preferred_unavailable"},
            )

    return response

async def _save_conversation_to_memory(app_state, user_msg: str, assistant_msg: str):
    """Background task to save conversation data to RAG-searchable memory."""
    try:
        from memory.memory.api.v1 import get_memory_api

        # Create conversation text
        conversation_text = f"User: {user_msg}\nAssistant: {assistant_msg}"

        logger.info(_t_from_state(
            app_state,
            "core.chat.autosave_start",
            "💾 Auto-saving conversation to RAG memory (nexe_chat_memory)...",
        ))

        # Use MemoryAPI to store in Qdrant HTTP (same place RAG searches)
        memory = await get_memory_api()

        # Ensure collection exists
        if not await memory.collection_exists("nexe_chat_memory"):
            await memory.create_collection("nexe_chat_memory", vector_size=384)
            logger.info(_t_from_state(
                app_state,
                "core.chat.autosave_collection_created",
                "Created nexe_chat_memory collection",
            ))

        # Store the conversation
        doc_id = await memory.store(
            text=conversation_text,
            collection="nexe_chat_memory",
            metadata={
                "type": "conversation_turn",
                "auto_saved": True,
                "source": "chat_interaction",
                "timestamp": datetime.now(timezone.utc).isoformat()
            }
        )

        logger.info(_t_from_state(
            app_state,
            "core.chat.autosave_saved",
            "Conversation saved to nexe_chat_memory (id={id})",
            id=doc_id,
        ))

        try:
            from core.metrics.registry import MEMORY_OPERATIONS
            MEMORY_OPERATIONS.labels(operation="autosave").inc()
        except Exception as e:
            logger.debug(_t_from_state(
                app_state,
                "core.chat.autosave_metrics_failed",
                "Autosave metrics update failed: {error}",
                error=str(e),
            ))

    except Exception as e:
        logger.error(_t_from_state(
            app_state,
            "core.chat.autosave_error",
            "Error saving conversation to memory: {error}",
            error=str(e),
        ))

async def _forward_to_ollama(
    messages: List[Dict],
    request: ChatCompletionRequest,
    app_state=None,
    user_msg: str = None,
    fallback_from: Optional[str] = None,
    fallback_reason: Optional[str] = None,
):
    """Forward request to local Ollama instance."""
    import os
    url = "http://localhost:11434/api/chat"

    # Get model from: request > env var > config > fallback
    model_name = request.model
    if not model_name:
        model_name = os.environ.get("NEXE_DEFAULT_MODEL")
    if not model_name and app_state:
        config = getattr(app_state, "config", {}) or {}
        model_name = config.get("plugins", {}).get("models", {}).get("primary")
    if not model_name:
        model_name = "llama3.2"  # Last resort fallback

    # Check if Ollama is available before trying to connect
    try:
        async with httpx.AsyncClient(timeout=3.0) as client:
            tags_resp = await client.get("http://localhost:11434/api/tags")
            if tags_resp.status_code != 200:
                 raise HTTPException(
                     status_code=502,
                     detail=_t_from_state(
                         app_state,
                         "core.chat.ollama_http_error",
                         "Ollama error (HTTP {status})",
                         status=tags_resp.status_code,
                     ),
                 )
            available_models = [m.get("name", "") for m in tags_resp.json().get("models", [])]

            # Filter out embedding models (they can't chat!)
            EMBEDDING_MODELS = {"nomic-embed", "mxbai-embed", "all-minilm", "bge-", "embed"}
            chat_models = [m for m in available_models
                          if not any(emb in m.lower() for emb in EMBEDDING_MODELS)]

            # Verify the model exists
            if model_name not in available_models and f"{model_name}:latest" not in available_models:
                # Try to find a partial match in chat models only
                matching = [m for m in chat_models if model_name.split(":")[0] in m]
                if matching:
                    model_name = matching[0]
                    logger.info(_t_from_state(
                        app_state,
                        "core.chat.ollama_model_fallback",
                        "Using available model: {model}",
                        model=model_name,
                    ))
                elif chat_models:
                    # Use first available chat model as fallback
                    model_name = chat_models[0]
                    logger.warning(_t_from_state(
                        app_state,
                        "core.chat.ollama_model_not_found",
                        "Requested model not found. Using available model: {model}",
                        model=model_name,
                    ))
                else:
                    raise HTTPException(
                        status_code=503,
                        detail=_t_from_state(
                            app_state,
                            "core.chat.ollama_no_chat_models",
                            "No chat model downloaded in Ollama. Run: ollama pull llama3.2",
                        ),
                    )
    except httpx.ConnectError:
        raise HTTPException(
            status_code=503,
            detail=_t_from_state(
                app_state,
                "core.chat.ollama_not_available",
                "Ollama not available. The server is starting or Ollama is not installed. "
                "Wait a few seconds and try again, or run: curl -fsSL https://ollama.com/install.sh | sh",
            ),
        )

    payload = {
        "model": model_name,
        "messages": messages,
        "stream": request.stream,
        "options": {
            "temperature": request.temperature,
            "num_predict": request.max_tokens or 2048
        }
    }

    if request.stream:
        headers = {"X-Nexe-Engine": "ollama"}
        if fallback_from:
            headers["X-Nexe-Fallback-From"] = fallback_from
            headers["X-Nexe-Fallback-Reason"] = fallback_reason or "fallback"
        return StreamingResponse(
            _ollama_stream_generator(url, payload, app_state, user_msg),
            media_type="text/event-stream",
            headers=headers,
        )
    else:
        # Blocking call
        try:
            async with httpx.AsyncClient() as client:
                resp = await client.post(url, json=payload, timeout=60.0)
                if resp.status_code != 200:
                    try:
                        error_detail = resp.json().get("error") or _t_from_state(
                            app_state,
                            "core.chat.ollama_unknown_error",
                            "Unknown Ollama error",
                        )
                    except (ValueError, json.JSONDecodeError, AttributeError):
                        error_detail = _t_from_state(
                            app_state,
                            "core.chat.ollama_returned_http",
                            "Ollama returned HTTP {status}",
                            status=resp.status_code,
                        )
                    raise HTTPException(status_code=resp.status_code, detail=error_detail)
                response = resp.json()
                response.setdefault("nexe_engine", "ollama")
                if fallback_from:
                    response.setdefault(
                        "nexe_fallback",
                        {"from": fallback_from, "to": "ollama", "reason": fallback_reason or "fallback"},
                    )
                return response
        except httpx.ConnectError:
            raise HTTPException(
                status_code=503,
                detail=_t_from_state(
                    app_state,
                    "core.chat.ollama_no_response",
                    "Ollama is not responding. Verify it is running: ollama serve",
                ),
            )

async def _ollama_stream_generator(url: str, payload: dict, app_state=None, user_msg: str = None):
    """Generator compatible amb OpenAI format (més o menys) a partir d'Ollama + Auto-Save."""
    full_response_text = ""

    try:
        async with httpx.AsyncClient(timeout=60.0) as client:
            async with client.stream("POST", url, json=payload) as resp:
                if resp.status_code != 200:
                    error_msg = _t_from_state(
                        app_state,
                        "core.chat.ollama_stream_failed_status",
                        "Ollama stream failed with status {status}",
                        status=resp.status_code,
                    )
                    yield f"data: {json.dumps({'error': error_msg})}\n\n"
                    yield "data: [DONE]\n\n"
                    return

                async for line in resp.aiter_lines():
                    if not line: continue
                    try:
                        # Ollama retorna JSON lines
                        data = json.loads(line)
                        content = data.get("message", {}).get("content", "")
                        done = data.get("done", False)

                        if content:
                            full_response_text += content # Accumulate
                            # Wrap in OpenAI-like SSe format for our client convenience
                            chunk = {
                                "choices": [{"delta": {"content": content}}]
                            }
                            yield f"data: {json.dumps(chunk)}\n\n"

                        if done:
                            yield "data: [DONE]\n\n"
                            # --- TRIGGER AUTO-SAVE ---
                            if app_state and user_msg and full_response_text.strip():
                                 try:
                                     await _save_conversation_to_memory(app_state, user_msg, full_response_text)
                                 except Exception as e:
                                     logger.error(_t_from_state(
                                         app_state,
                                         "core.chat.autosave_stream_failed",
                                         "Stream Auto-Save failed: {error}",
                                         error=str(e),
                                     ))
                            break

                    except json.JSONDecodeError:
                        pass
    except httpx.ConnectError:
        error_msg = {
            "error": _t_from_state(
                app_state,
                "core.chat.ollama_stream_not_available",
                "Ollama not available. Wait a few seconds and try again.",
            )
        }
        yield f"data: {json.dumps(error_msg)}\n\n"
        yield "data: [DONE]\n\n"


async def _mlx_stream_generator(
    mlx_module,
    user_messages: List[Dict],
    system_msg: str,
    model_name: str,
    app_state=None,
    user_msg: str = None
):
    """
    Generator SSE per MLX streaming.

    Usa asyncio.Queue per fer pont entre el callback síncron de MLX
    i l'async generator que necessita FastAPI.
    """
    tokens_queue: asyncio.Queue = asyncio.Queue()
    loop = asyncio.get_running_loop()
    generation_done = asyncio.Event()
    result_holder = {"result": None, "error": None}
    full_response_text = ""

    def on_token(token: str):
        """Callback cridat per cada token generat (des de thread MLX)."""
        nonlocal full_response_text
        full_response_text += token
        try:
            # Thread-safe: posar token a la queue
            loop.call_soon_threadsafe(
                tokens_queue.put_nowait,
                token
            )
        except Exception as e:
            logger.debug(_t_from_state(
                app_state,
                "core.chat.mlx_token_enqueue_failed",
                "Stream token enqueue failed (queue closed): {error}",
                error=str(e),
            ))  # Queue tancada, ignorar

    async def run_mlx():
        """Executa MLX en background amb stream_callback."""
        try:
            result = await mlx_module.chat(
                messages=user_messages,
                system=system_msg,
                session_id="chat_session",
                stream_callback=on_token
            )
            result_holder["result"] = result
        except Exception as e:
            result_holder["error"] = str(e)
            logger.error(_t_from_state(
                app_state,
                "core.chat.mlx_stream_error",
                "MLX streaming error: {error}",
                error=str(e),
            ))
        finally:
            generation_done.set()

    # Iniciar MLX en background
    mlx_task = asyncio.create_task(run_mlx())

    try:
        # Enviar tokens mentre es generen
        while not generation_done.is_set() or not tokens_queue.empty():
            try:
                token = await asyncio.wait_for(
                    tokens_queue.get(),
                    timeout=0.1
                )
                # Format OpenAI SSE
                chunk = {
                    "id": f"mlx-stream-{int(time.time())}",
                    "object": "chat.completion.chunk",
                    "created": int(time.time()),
                    "model": model_name,
                    "choices": [{
                        "index": 0,
                        "delta": {"content": token},
                        "finish_reason": None
                    }]
                }
                yield f"data: {json.dumps(chunk)}\n\n"
            except asyncio.TimeoutError:
                if generation_done.is_set() and tokens_queue.empty():
                    break

        # Esperar que acabi
        await mlx_task

        # Chunk final amb finish_reason
        final_chunk = {
            "id": f"mlx-stream-{int(time.time())}",
            "object": "chat.completion.chunk",
            "created": int(time.time()),
            "model": model_name,
            "choices": [{
                "index": 0,
                "delta": {},
                "finish_reason": "stop"
            }]
        }
        yield f"data: {json.dumps(final_chunk)}\n\n"
        yield "data: [DONE]\n\n"

        # Auto-save a memòria (com Ollama)
        if app_state and user_msg and full_response_text.strip():
            try:
                await _save_conversation_to_memory(app_state, user_msg, full_response_text)
            except Exception as e:
                logger.error(_t_from_state(
                    app_state,
                    "core.chat.mlx_autosave_failed",
                    "MLX Stream Auto-Save failed: {error}",
                    error=str(e),
                ))

        # Log mètriques si tenim resultat
        if result_holder["result"]:
            result = result_holder["result"]
            logger.info(_t_from_state(
                app_state,
                "core.chat.mlx_stream_completed",
                "MLX stream completed: {tokens} tokens, {tps:.1f} tok/s",
                tokens=result.get("tokens", 0),
                tps=result.get("tokens_per_second", 0),
            ))

    except Exception as e:
        logger.exception(_t_from_state(
            app_state,
            "core.chat.mlx_stream_failed",
            "MLX streaming failed",
        ))
        error_chunk = {"error": str(e)}
        yield f"data: {json.dumps(error_chunk)}\n\n"


async def _forward_to_mlx(messages: List[Dict], request: ChatCompletionRequest, req: Request):
    """Forward to MLX module (Apple Silicon optimized)."""
    try:
        # Get MLX module from app state
        mlx_module = None
        if hasattr(req.app.state, 'modules'):
            mlx_module = req.app.state.modules.get('mlx_module')

        last_user_msg = next(
            (m.get("content") for m in reversed(messages) if m.get("role") == "user"),
            None,
        )

        if not mlx_module or not hasattr(mlx_module, 'chat'):
            # MLX module not loaded or not available - fallback to Ollama
            logger.warning(_t_from_state(
                req.app.state,
                "core.chat.mlx_unavailable",
                "MLX module not available (Metal/model not configured). Falling back to Ollama.",
            ))
            logger.info(_t_from_state(
                req.app.state,
                "core.chat.mlx_setup_hint",
                "To use MLX: Set NEXE_MLX_MODEL in .env and ensure Metal is available",
            ))
            return await _forward_to_ollama(
                messages,
                request,
                app_state=req.app.state,
                user_msg=last_user_msg,
                fallback_from="mlx",
                fallback_reason="module_unavailable",
            )

        # Prepare messages for MLX
        system_msg = ""
        user_messages = []

        for msg in messages:
            if msg.get("role") == "system":
                system_msg = msg.get("content", "")
            else:
                user_messages.append(msg)

        model_name = request.model or "mlx-local"

        # STREAMING MODE
        if request.stream:
            logger.info(_t_from_state(
                req.app.state,
                "core.chat.mlx_forward_streaming",
                "Forwarding to MLX module (streaming)...",
            ))
            return StreamingResponse(
                _mlx_stream_generator(
                    mlx_module,
                    user_messages,
                    system_msg,
                    model_name,
                    app_state=req.app.state,
                    user_msg=last_user_msg,
                ),
                media_type="text/event-stream",
                headers={
                    "Cache-Control": "no-cache",
                    "Connection": "keep-alive",
                    "X-Accel-Buffering": "no",
                },
            )

        # NON-STREAMING MODE
        logger.info(_t_from_state(
            req.app.state,
            "core.chat.mlx_forward",
            "Forwarding to MLX module...",
        ))
        result = await mlx_module.chat(
            messages=user_messages,
            system=system_msg,
            session_id="chat_session",
        )

        return {
            "id": f"mlx-{uuid.uuid4().hex}",
            "object": "chat.completion",
            "created": int(time.time()),
            "model": model_name,
            "choices": [{
                "index": 0,
                "message": {
                    "role": "assistant",
                    "content": result.get("response", "")
                },
                "finish_reason": "stop"
            }],
            "usage": {
                "prompt_tokens": result.get("prompt_tokens", 0),
                "completion_tokens": result.get("tokens", 0),
                "total_tokens": result.get("context_used", 0)
            }
        }

    except Exception as e:
        logger.error(_t_from_state(
            req.app.state,
            "core.chat.mlx_execution_failed",
            "MLX execution failed: {error}. Falling back to Ollama.",
            error=str(e),
        ))
        return await _forward_to_ollama(
            messages,
            request,
            app_state=req.app.state,
            user_msg=last_user_msg,
            fallback_from="mlx",
            fallback_reason="execution_failed",
        )

async def _forward_to_llama_cpp(messages: List[Dict], request: ChatCompletionRequest, req: Request):
    """Forward to Llama.cpp module (GGUF models)."""
    try:
        # Get llama_cpp module from app state
        llama_module = None
        if hasattr(req.app.state, 'modules'):
            llama_module = req.app.state.modules.get('llama_cpp_module')

        last_user_msg = next(
            (m.get("content") for m in reversed(messages) if m.get("role") == "user"),
            None,
        )

        if not llama_module or not hasattr(llama_module, 'chat'):
            # Llama.cpp module not loaded - fallback to Ollama
            logger.warning(_t_from_state(
                req.app.state,
                "core.chat.llamacpp_unavailable",
                "Llama.cpp module not available (model not configured). Falling back to Ollama.",
            ))
            logger.info(_t_from_state(
                req.app.state,
                "core.chat.llamacpp_setup_hint",
                "To use Llama.cpp: Set NEXE_LLAMA_CPP_MODEL in .env",
            ))
            return await _forward_to_ollama(
                messages,
                request,
                app_state=req.app.state,
                user_msg=last_user_msg,
                fallback_from="llama_cpp",
                fallback_reason="module_unavailable",
            )

        # Prepare messages for llama.cpp
        system_msg = ""
        user_messages = []

        for msg in messages:
            if msg.get("role") == "system":
                system_msg = msg.get("content", "")
            else:
                user_messages.append(msg)

        if request.stream:
            model_name = request.model or "llama-cpp-local"
            return StreamingResponse(
                _llama_cpp_stream_generator(
                    llama_module,
                    user_messages,
                    system_msg,
                    model_name,
                    app_state=req.app.state,
                    user_msg=last_user_msg,
                ),
                media_type="text/event-stream",
                headers={
                    "Cache-Control": "no-cache",
                    "Connection": "keep-alive",
                    "X-Accel-Buffering": "no",
                },
            )

        # Call llama.cpp module
        logger.info(_t_from_state(
            req.app.state,
            "core.chat.llamacpp_forward",
            "Forwarding to Llama.cpp module...",
        ))
        result = await llama_module.chat(
            messages=user_messages,
            system=system_msg,
            session_id="chat_session",
        )

        # Convert llama.cpp response to OpenAI format
        return {
            "id": f"llamacpp-{uuid.uuid4().hex}",
            "object": "chat.completion",
            "created": int(time.time()),
            "model": request.model or "llama-cpp-local",
            "choices": [{
                "index": 0,
                "message": {
                    "role": "assistant",
                    "content": result.get("response", "")
                },
                "finish_reason": "stop"
            }],
            "usage": {
                "prompt_tokens": result.get("prompt_tokens", 0),
                "completion_tokens": result.get("tokens", 0),
                "total_tokens": result.get("context_used", 0)
            }
        }

    except Exception as e:
        logger.error(_t_from_state(
            req.app.state,
            "core.chat.llamacpp_execution_failed",
            "Llama.cpp execution failed: {error}. Falling back to Ollama.",
            error=str(e),
        ))
        return await _forward_to_ollama(
            messages,
            request,
            app_state=req.app.state,
            user_msg=last_user_msg,
            fallback_from="llama_cpp",
            fallback_reason="execution_failed",
        )

async def _llama_cpp_stream_generator(
    llama_module,
    user_messages: List[Dict],
    system_msg: str,
    model_name: str,
    app_state=None,
    user_msg: str = None
):
    """
    Generator SSE per Llama.cpp streaming.

    Usa asyncio.Queue per fer pont entre el callback de llama.cpp
    i l'async generator que necessita FastAPI.
    """
    tokens_queue: asyncio.Queue = asyncio.Queue()
    loop = asyncio.get_running_loop()
    generation_done = asyncio.Event()
    result_holder = {"result": None, "error": None}
    full_response_text = ""

    def on_token(token: str):
        """Callback cridat per cada token generat (des de thread)."""
        nonlocal full_response_text
        full_response_text += token
        try:
            loop.call_soon_threadsafe(
                tokens_queue.put_nowait,
                token
            )
        except Exception as e:
            logger.debug(_t_from_state(
                app_state,
                "core.chat.llamacpp_token_enqueue_failed",
                "Llama.cpp stream token enqueue failed (queue closed): {error}",
                error=str(e),
            ))

    async def run_llama():
        """Executa Llama.cpp en background amb stream_callback."""
        try:
            result = await llama_module.chat(
                messages=user_messages,
                system=system_msg,
                session_id="chat_session",
                stream_callback=on_token
            )
            result_holder["result"] = result
        except Exception as e:
            result_holder["error"] = str(e)
            logger.error(_t_from_state(
                app_state,
                "core.chat.llamacpp_stream_error",
                "Llama.cpp streaming error: {error}",
                error=str(e),
            ))
        finally:
            generation_done.set()

    llama_task = asyncio.create_task(run_llama())

    try:
        while not generation_done.is_set() or not tokens_queue.empty():
            try:
                token = await asyncio.wait_for(
                    tokens_queue.get(),
                    timeout=0.1
                )
                chunk = {
                    "id": f"llamacpp-stream-{int(time.time())}",
                    "object": "chat.completion.chunk",
                    "created": int(time.time()),
                    "model": model_name,
                    "choices": [{
                        "index": 0,
                        "delta": {"content": token},
                        "finish_reason": None
                    }]
                }
                yield f"data: {json.dumps(chunk)}\n\n"
            except asyncio.TimeoutError:
                if generation_done.is_set() and tokens_queue.empty():
                    break

        await llama_task

        final_chunk = {
            "id": f"llamacpp-stream-{int(time.time())}",
            "object": "chat.completion.chunk",
            "created": int(time.time()),
            "model": model_name,
            "choices": [{
                "index": 0,
                "delta": {},
                "finish_reason": "stop"
            }]
        }
        yield f"data: {json.dumps(final_chunk)}\n\n"
        yield "data: [DONE]\n\n"

        if app_state and user_msg and full_response_text.strip():
            try:
                await _save_conversation_to_memory(app_state, user_msg, full_response_text)
            except Exception as e:
                logger.error(_t_from_state(
                    app_state,
                    "core.chat.llamacpp_autosave_failed",
                    "Llama.cpp Stream Auto-Save failed: {error}",
                    error=str(e),
                ))

    except Exception as e:
        logger.exception(_t_from_state(
            app_state,
            "core.chat.llamacpp_stream_failed",
            "Llama.cpp streaming failed",
        ))
        error_chunk = {"error": str(e)}
        yield f"data: {json.dumps(error_chunk)}\n\n"
