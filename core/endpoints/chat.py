"""
────────────────────────────────────
Server Nexe
Version: 0.8
Author: Jordi Goy 
Location: core/endpoints/chat.py
Description: Unified Chat Endpoint with RAG support & Streaming.

www.jgoy.net · https://server-nexe.org
────────────────────────────────────
"""

from fastapi import APIRouter, HTTPException, Request, Depends, BackgroundTasks
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, ConfigDict, Field
from typing import List, Optional, Dict, Any, Union
import asyncio
import hashlib
import logging
import os
import httpx
import json
import time
import uuid
from datetime import datetime, timezone
from plugins.security.core.auth_dependencies import require_api_key
from memory.memory.models.memory_entry import MemoryEntry
from memory.rag_sources.base import SearchRequest

logger = logging.getLogger(__name__)

router = APIRouter(tags=["chat"])

# ═══════════════════════════════════════════════════════════════════════════
# MODULE-LEVEL CACHES & CONFIGURABLE TIMEOUTS
# ═══════════════════════════════════════════════════════════════════════════

# CS4: Cache for Ollama /api/tags — avoid HTTP call on every chat request
_ollama_tags_cache: dict = {"models": None, "ts": 0.0}
_TAGS_CACHE_TTL = 30  # seconds

# CS7: Configurable stream timeout via env var (default 300s for thinking models)
_OLLAMA_STREAM_TIMEOUT = float(os.environ.get("NEXE_OLLAMA_STREAM_TIMEOUT", "300"))

# Tracked background save tasks — prevents "Task was destroyed" warnings on shutdown
_background_tasks: set = set()

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

def _sanitize_rag_context(context: str) -> str:
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
        sanitized += "\n[...truncat]"
        logger.warning(f"RAG context truncated from {len(context)} to {MAX_RAG_CONTEXT_LENGTH} chars")

    # 2. Remove prompt injection patterns
    for pattern in _RAG_INJECTION_PATTERNS:
        sanitized = pattern.sub('[FILTERED]', sanitized)

    # 3. Escape our own delimiter markers to prevent context breakout
    sanitized = sanitized.replace('[/CONTEXT]', '[/CONTEXT_ESCAPED]')
    sanitized = sanitized.replace('[CONTEXT', '[CONTEXT_ESCAPED')

    return sanitized

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

# --- System Prompt ---

def _get_system_prompt(app_state, lang: str = None) -> str:
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

    # Busca prompt específic → fallback full → fallback en → mínim
    for key in [f"{lang_short}_{tier}", f"{lang_short}_full", "en_full"]:
        prompt = prompts.get(key, "")
        if prompt:
            return prompt

    return "You are Nexe, an AI assistant. Respond clearly and helpfully."


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
        logger.warning("Preferred engine '%s' not available, falling back", preferred)
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

@router.post("/chat/completions", dependencies=[Depends(require_api_key)], summary="Chat completion amb suport RAG i auto-routing d'engines")
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

    # Server language: NEXE_LANG env var (not i18n module, which tracks UI translation language)
    _server_lang = os.getenv("NEXE_LANG", "ca").split("-")[0].lower()  # "ca-ES" → "ca"

    # 2. RAG Context Injection
    context_text = ""
    if request.use_rag:
        try:
            # Extract last user message for query
            last_user_msg = next((m.content for m in reversed(request.messages) if m.role == "user"), None)
            if last_user_msg:
                logger.info(f"RAG Search for: '{last_user_msg}'")

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
                                logger.info(f"RAG: Found {len(doc_results)} docs from documentation")
                    except Exception as e:
                        logger.debug("RAG docs search failed: %s", e)

                    # 2. Search user knowledge (custom documents in knowledge/ folder)
                    try:
                        if await memory.collection_exists("user_knowledge"):
                            knowledge_results = await memory.search(
                                query=last_user_msg,
                                collection="user_knowledge",
                                top_k=3,
                                threshold=0.35,
                                filter_metadata={"lang": _server_lang}
                            )
                            if knowledge_results:
                                all_results.extend(knowledge_results)
                                logger.info(f"RAG: Found {len(knowledge_results)} docs from user knowledge")
                    except Exception as e:
                        logger.debug("RAG knowledge search failed: %s", e)

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
                                logger.info(f"RAG: Found {len(mem_results)} docs from chat memory")
                    except Exception as e:
                        logger.debug("RAG chat memory search failed: %s", e)

                    if all_results:
                        # Deduplicate results by content hash
                        seen_hashes = set()
                        unique_results = []
                        for r in all_results:
                            content_hash = hash(r.text[:200])
                            if content_hash not in seen_hashes:
                                seen_hashes.add(content_hash)
                                unique_results.append(r)
                        # Build context with clear source headers
                        context_parts = []
                        for r in unique_results[:5]:
                            source = getattr(r, 'metadata', {}).get('source', 'unknown') if hasattr(r, 'metadata') else 'unknown'
                            context_parts.append(f"[Font: {source}]\n{r.text}")
                        context_text = "\n\n".join(context_parts)
                        logger.info(f"RAG Context found (MemoryAPI): {len(context_text)} chars, {len(all_results)} results")
                except Exception as mem_err:
                    logger.debug(f"MemoryAPI not available: {mem_err}")

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
                            logger.info(f"RAG Context found (RAG module): {len(context_text)} chars")
                        else:
                            logger.info("RAG Search returned no results")
                    else:
                        logger.debug("No RAG source available")

        except Exception as e:
            logger.error(f"RAG Error: {e}")
            # Continue without context rather than failing

    # 3. Augment System Prompt (Nexe persona + sanitized RAG context)
    messages = [m.model_dump() for m in request.messages]

    # Injectar system prompt de Nexe si el client no n'envia cap
    has_system = messages and messages[0]['role'] == 'system'
    if not has_system:
        nexe_prompt = _get_system_prompt(req.app.state, _server_lang)
        messages.insert(0, {"role": "system", "content": nexe_prompt})

    if context_text and messages:
        # SECURITY: Sanitize RAG context before injection
        safe_context = _sanitize_rag_context(context_text)

        # Inject RAG context into the last user message (NOT system prompt)
        # This preserves prefix caching for the system prompt
        for i in range(len(messages) - 1, -1, -1):
            if messages[i]['role'] == 'user':
                messages[i]['content'] = (
                    f"[CONTEXT MEMÒRIA]\n"
                    f"Usa aquesta informació recuperada per respondre si és rellevant:\n"
                    f"{safe_context}\n"
                    f"[/CONTEXT]\n\n"
                    f"{messages[i]['content']}"
                )
                break

    # 4. Dispatch to Engine
    # Extract last user message for auto-save logic
    last_user_msg = next((m.content for m in reversed(request.messages) if m.role == "user"), None)

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
                    req.app.state,
                    last_user_msg,
                    content
                )
        except Exception as e:
            logger.error(f"Failed to schedule memory save: {e}")
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

        logger.info("💾 Auto-saving conversation to RAG memory (nexe_chat_memory)...")

        # Use MemoryAPI to store in Qdrant HTTP (same place RAG searches)
        memory = await get_memory_api()

        # Ensure collection exists (idempotent to handle concurrent requests)
        try:
            if not await memory.collection_exists("nexe_chat_memory"):
                await memory.create_collection("nexe_chat_memory", vector_size=768)
                logger.info("Created nexe_chat_memory collection")
        except Exception:
            # Collection may have been created by concurrent request — verify it exists
            if not await memory.collection_exists("nexe_chat_memory"):
                raise

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

        logger.info(f"Conversation saved to nexe_chat_memory (id={doc_id})")

        try:
            from core.metrics.registry import MEMORY_OPERATIONS
            MEMORY_OPERATIONS.labels(operation="autosave").inc()
        except Exception as e:
            logger.debug("Autosave metrics update failed: %s", e)

    except Exception as e:
        logger.error(f"Error saving conversation to memory: {e}")

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
    _ollama_host = os.environ.get("NEXE_OLLAMA_HOST", "http://localhost:11434").rstrip("/")
    url = f"{_ollama_host}/api/chat"

    # Get model from: request > NEXE_OLLAMA_MODEL > NEXE_DEFAULT_MODEL (si no és URL) > config > fallback
    model_name = request.model
    if not model_name:
        model_name = os.environ.get("NEXE_OLLAMA_MODEL")
    if not model_name:
        # Legacy: NEXE_DEFAULT_MODEL pot ser una URL HF o path — ignorar-la per Ollama
        _default = os.environ.get("NEXE_DEFAULT_MODEL", "")
        if _default and not _default.startswith(("http", "/", "~", "storage/")):
            model_name = _default
    if not model_name and app_state:
        config = getattr(app_state, "config", {}) or {}
        model_name = config.get("plugins", {}).get("models", {}).get("primary")
    if not model_name:
        model_name = "llama3.2"  # Last resort fallback

    # Check if Ollama is available before trying to connect
    try:
        _now = time.time()
        if _ollama_tags_cache["models"] is not None and (_now - _ollama_tags_cache["ts"]) < _TAGS_CACHE_TTL:
            available_models = _ollama_tags_cache["models"]
        else:
            async with httpx.AsyncClient(timeout=3.0) as client:
                tags_resp = await client.get(f"{_ollama_host}/api/tags")
                if tags_resp.status_code != 200:
                     raise HTTPException(status_code=502, detail=f"Ollama error (HTTP {tags_resp.status_code})")
                available_models = [m.get("name", "") for m in tags_resp.json().get("models", [])]
                _ollama_tags_cache["models"] = available_models
                _ollama_tags_cache["ts"] = _now

        # Filter out embedding models (they can't chat!) — runs on BOTH cache hit and miss
        EMBEDDING_MODELS = {"nomic-embed", "mxbai-embed", "all-minilm", "bge-", "embed"}
        chat_models = [m for m in available_models
                      if not any(emb in m.lower() for emb in EMBEDDING_MODELS)]

        # Verify the model exists
        if model_name not in available_models and f"{model_name}:latest" not in available_models:
            # Try to find a partial match in chat models only
            matching = [m for m in chat_models if model_name.split(":")[0] in m]
            if matching:
                model_name = matching[0]
                logger.info(f"Using available model: {model_name}")
            elif chat_models:
                # Use first available chat model as fallback
                model_name = chat_models[0]
                logger.warning(f"Requested model not found. Using available model: {model_name}")
            else:
                raise HTTPException(
                    status_code=503,
                    detail=f"No hi ha cap model de CHAT descarregat a Ollama. "
                           f"Executa: ollama pull llama3.2"
                )
    except httpx.ConnectError:
        raise HTTPException(
            status_code=503,
            detail="Ollama no disponible. El servidor s'està iniciant o Ollama no està instal·lat. "
                   "Espera uns segons i torna-ho a provar, o executa: curl -fsSL https://ollama.com/install.sh | sh"
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
                        error_detail = resp.json().get("error", "Unknown Ollama error")
                    except (ValueError, json.JSONDecodeError, AttributeError):
                        error_detail = f"Ollama returned HTTP {resp.status_code}"
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
                detail="Ollama no respon. Verifica que està corrent: ollama serve"
            )

async def _ollama_stream_generator(url: str, payload: dict, app_state=None, user_msg: str = None):
    """Generator compatible amb OpenAI format (més o menys) a partir d'Ollama + Auto-Save."""
    full_response_text = ""

    try:
        async with httpx.AsyncClient(timeout=_OLLAMA_STREAM_TIMEOUT) as client:
            async with client.stream("POST", url, json=payload) as resp:
                if resp.status_code != 200:
                    yield f"data: {json.dumps({'error': f'Ollama stream failed with status {resp.status_code}'})}\n\n"
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
                            # --- TRIGGER AUTO-SAVE (fire-and-forget) ---
                            if app_state and user_msg and full_response_text.strip():
                                async def _background_save_ollama():
                                    for attempt in range(2):
                                        try:
                                            await _save_conversation_to_memory(app_state, user_msg, full_response_text)
                                            return
                                        except Exception as e:
                                            if attempt == 0:
                                                await asyncio.sleep(1)
                                            else:
                                                logger.error("Stream Auto-Save failed after retry: %s", e)
                                task = asyncio.create_task(_background_save_ollama())
                                _background_tasks.add(task)
                                task.add_done_callback(_background_tasks.discard)
                            break

                    except json.JSONDecodeError as jde:
                        logger.debug("Ollama stream: JSON decode error on line: %s", jde)
    except asyncio.CancelledError:
        # Client disconnected during streaming — clean exit, no error.
        logger.debug("Ollama stream cancelled (client disconnected)")
        return
    except httpx.ConnectError:
        error_msg = {"error": "Ollama no disponible. Espera uns segons i torna-ho a provar."}
        yield f"data: {json.dumps(error_msg)}\n\n"
        yield "data: [DONE]\n\n"


async def _mlx_stream_generator(
    mlx_module,
    user_messages: List[Dict],
    system_msg: str,
    model_name: str,
    app_state=None,
    user_msg: str = None,
    session_id: str = "chat_session",
    max_tokens: Optional[int] = None,
    temperature: Optional[float] = None,
):
    """
    Generator SSE per MLX streaming.

    Usa asyncio.Queue per fer pont entre el callback síncron de MLX
    i l'async generator que necessita FastAPI.
    """
    tokens_queue: asyncio.Queue = asyncio.Queue(maxsize=512)
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
            logger.warning("Stream token enqueue failed (queue full/closed): %s", e)

    async def run_mlx():
        """Executa MLX en background amb stream_callback."""
        try:
            result = await mlx_module.chat(
                messages=user_messages,
                system=system_msg,
                session_id=session_id,
                stream_callback=on_token,
                max_tokens=max_tokens,
                temperature=temperature,
            )
            result_holder["result"] = result
        except Exception as e:
            result_holder["error"] = str(e)
            logger.error(f"MLX streaming error: {e}")
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

        # Auto-save a memòria (fire-and-forget com Ollama)
        if app_state and user_msg and full_response_text.strip():
            async def _background_save_mlx():
                for attempt in range(2):
                    try:
                        await _save_conversation_to_memory(app_state, user_msg, full_response_text)
                        return
                    except Exception as e:
                        if attempt == 0:
                            await asyncio.sleep(1)
                        else:
                            logger.error("MLX Stream Auto-Save failed after retry: %s", e)
            task = asyncio.create_task(_background_save_mlx())
            _background_tasks.add(task)
            task.add_done_callback(_background_tasks.discard)

        # Log mètriques si tenim resultat
        if result_holder["result"]:
            result = result_holder["result"]
            logger.info(
                "MLX stream completed: %d tokens, %.1f tok/s",
                result.get("tokens", 0),
                result.get("tokens_per_second", 0)
            )

    except Exception as e:
        logger.exception("MLX streaming failed")
        error_chunk = {"error": str(e)}
        yield f"data: {json.dumps(error_chunk)}\n\n"
    finally:
        if not mlx_task.done():
            mlx_task.cancel()


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
            logger.warning("MLX module not available (Metal/model not configured). Falling back to Ollama.")
            logger.info("To use MLX: Set NEXE_MLX_MODEL in .env and ensure Metal is available")
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

        # Derive session_id from X-Session-Id header or API key hash
        _api_key = (req.headers.get("x-api-key") or req.headers.get("authorization", "")).encode()
        session_id = req.headers.get("x-session-id") or f"sess_{hashlib.sha256(_api_key).hexdigest()[:16]}"

        # STREAMING MODE
        if request.stream:
            logger.info("Forwarding to MLX module (streaming)...")
            return StreamingResponse(
                _mlx_stream_generator(
                    mlx_module,
                    user_messages,
                    system_msg,
                    model_name,
                    app_state=req.app.state,
                    user_msg=last_user_msg,
                    session_id=session_id,
                    max_tokens=request.max_tokens,
                    temperature=request.temperature,
                ),
                media_type="text/event-stream",
                headers={
                    "Cache-Control": "no-cache",
                    "Connection": "keep-alive",
                    "X-Accel-Buffering": "no",
                },
            )

        # NON-STREAMING MODE
        logger.info("Forwarding to MLX module...")
        result = await mlx_module.chat(
            messages=user_messages,
            system=system_msg,
            session_id=session_id,
            max_tokens=request.max_tokens,
            temperature=request.temperature,
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
        logger.error("MLX execution failed: %s. Falling back to Ollama.", e)
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
            logger.warning("Llama.cpp module not available (model not configured). Falling back to Ollama.")
            logger.info("To use Llama.cpp: Set NEXE_LLAMA_CPP_MODEL in .env")
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

        # Derive session_id from X-Session-Id header or API key hash
        _api_key = (req.headers.get("x-api-key") or req.headers.get("authorization", "")).encode()
        session_id = req.headers.get("x-session-id") or f"sess_{hashlib.sha256(_api_key).hexdigest()[:16]}"

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
                    session_id=session_id,
                    max_tokens=request.max_tokens,
                    temperature=request.temperature,
                ),
                media_type="text/event-stream",
                headers={
                    "Cache-Control": "no-cache",
                    "Connection": "keep-alive",
                    "X-Accel-Buffering": "no",
                },
            )

        # Call llama.cpp module
        logger.info("Forwarding to Llama.cpp module...")
        result = await llama_module.chat(
            messages=user_messages,
            system=system_msg,
            session_id=session_id,
            max_tokens=request.max_tokens,
            temperature=request.temperature,
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
        logger.error("Llama.cpp execution failed: %s. Falling back to Ollama.", e)
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
    user_msg: str = None,
    session_id: str = "chat_session",
    max_tokens: Optional[int] = None,
    temperature: Optional[float] = None,
):
    """
    Generator SSE per Llama.cpp streaming.

    Usa asyncio.Queue per fer pont entre el callback de llama.cpp
    i l'async generator que necessita FastAPI.
    """
    tokens_queue: asyncio.Queue = asyncio.Queue(maxsize=512)
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
            logger.warning("Llama.cpp stream token enqueue failed (queue full/closed): %s", e)

    async def run_llama():
        """Executa Llama.cpp en background amb stream_callback."""
        try:
            result = await llama_module.chat(
                messages=user_messages,
                system=system_msg,
                session_id=session_id,
                stream_callback=on_token,
                max_tokens=max_tokens,
                temperature=temperature,
            )
            result_holder["result"] = result
        except Exception as e:
            result_holder["error"] = str(e)
            logger.error("Llama.cpp streaming error: %s", e)
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
            async def _background_save_llama():
                for attempt in range(2):
                    try:
                        await _save_conversation_to_memory(app_state, user_msg, full_response_text)
                        return
                    except Exception as e:
                        if attempt == 0:
                            await asyncio.sleep(1)
                        else:
                            logger.error("Llama.cpp Stream Auto-Save failed after retry: %s", e)
            task = asyncio.create_task(_background_save_llama())
            _background_tasks.add(task)
            task.add_done_callback(_background_tasks.discard)

    except Exception as e:
        logger.exception("Llama.cpp streaming failed")
        error_chunk = {"error": str(e)}
        yield f"data: {json.dumps(error_chunk)}\n\n"
    finally:
        if not llama_task.done():
            llama_task.cancel()
