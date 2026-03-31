"""
------------------------------------
Server Nexe
Location: plugins/web_ui_module/api/routes_chat.py
Description: Endpoint POST /chat (~500 lines).
             Intent detection, RAG, compaction, multi-engine, streaming.
             Extret de routes.py durant refactoring de tech debt.

www.jgoy.net · https://server-nexe.org
------------------------------------
"""

from pathlib import Path
from typing import Dict, Any
import asyncio
import logging
import os as _os
import re as _re
from fastapi import APIRouter, HTTPException, Depends, Request as FastAPIRequest
from fastapi.responses import StreamingResponse
from core.dependencies import limiter

from plugins.web_ui_module.messages import get_message
from plugins.security.core.input_sanitizers import validate_string_input, strip_memory_tags
from core.endpoints.chat_sanitization import _sanitize_rag_context

def _get_memory_helper():
    """Lazy resolve via routes module so test patches work."""
    import plugins.web_ui_module.api.routes as _r
    return _r.get_memory_helper()

def _compact_session(session, engine, session_mgr):
    """Lazy resolve via routes module so test patches work."""
    import plugins.web_ui_module.api.routes as _r
    return _r.compact_session(session, engine, session_mgr)

logger = logging.getLogger(__name__)


def register_chat_routes(router: APIRouter, *, session_mgr, require_ui_auth):
    """Registra endpoint: POST /chat"""

    # -- POST /chat --
    #    ~550 lines: intent detection, RAG, compaction,
    #    multi-engine, streaming

    @router.post("/chat")
    @limiter.limit("20/minute")
    async def chat(request: FastAPIRequest, body: Dict[str, Any], _auth=Depends(require_ui_auth)):
        """Chat endpoint with streaming and memory intent detection"""
        message = body.get("message", "")
        session_id = body.get("session_id")
        stream = body.get("stream", False)

        if not message:
            raise HTTPException(status_code=400, detail=get_message(None, "webui.chat.message_required"))

        # Security: strip [MEM_SAVE:] tags from user input to prevent memory injection (SEC-002)
        message = strip_memory_tags(message)

        # Security: validate input (XSS, SQL injection, path traversal)
        message = validate_string_input(message, max_length=8000, context="chat")

        session = session_mgr.get_or_create_session(session_id)
        session.add_message("user", message)
        session_mgr._save_session_to_disk(session)

        # Detect intent (save, recall, or chat)
        memory_helper = _get_memory_helper()
        intent, extracted_content = memory_helper.detect_intent(message)

        response_text = ""
        memory_action = None

        if intent == "save":
            # Save to memory
            content_to_save = extracted_content.strip() if extracted_content else message
            # Clean up content (remove trailing punctuation from save request)
            content_to_save = content_to_save.rstrip('?!').strip()

            if content_to_save:
                result = await memory_helper.save_to_memory(
                    content=content_to_save,
                    session_id=session.id,
                    metadata={"original_message": message, "type": "user_fact"}
                )
                if result["success"]:
                    _safe_content = str(content_to_save).replace("\x00", "").replace("]", "")[:200]
                    response_text = f"Saved to memory: \"{_safe_content}\"\n\nI'll remember this for future conversations.\x00[MEM]\x00"
                else:
                    response_text = f"Could not save: {result.get('message', 'Unknown error')}"
            else:
                response_text = "What do you want me to remember? Write what you want to save."
            memory_action = "save"

        elif intent == "delete":
            # Delete from memory
            content_to_delete = extracted_content.strip() if extracted_content else ""
            if content_to_delete:
                result = await memory_helper.delete_from_memory(content_to_delete)
                if result["success"] and result.get("deleted", 0) > 0:
                    # Sanitize message in history to avoid re-save loop
                    # (the model would see the fact in history and re-save it via MEM_SAVE)
                    if session.messages and session.messages[-1]["role"] == "user":
                        session.messages[-1]["content"] = f"[Memory command: delete '{content_to_delete[:50]}']"
                    response_text = f"Deleted from memory: {result['deleted']} entry(ies) related to \"{content_to_delete[:100]}\""
                elif result["success"]:
                    response_text = f"Nothing found in memory about \"{content_to_delete[:100]}\""
                else:
                    response_text = f"Error: {result.get('message', 'Unknown error')}"
            else:
                response_text = "What do you want me to forget? Write what you want to delete."
            memory_action = "delete"

        elif intent == "recall":
            # Recall intent: DON'T show raw results, use LLM with memory context
            # Falls through to normal chat processing with memory search
            memory_action = "recall"
            intent = "chat"  # Treat as chat so LLM responds naturally

        if intent == "chat":
            # Normal chat - Auto-detect and use available LLM engine
            try:
                from core.lifespan import get_server_state
                import os

                module_manager = get_server_state().module_manager
                # Prioritzar model/backend del request (selector UI) sobre env vars
                model_name = body.get("model") or os.getenv("NEXE_DEFAULT_MODEL", "llama3.2:3b")
                preferred_engine = (body.get("backend") or os.getenv("NEXE_MODEL_ENGINE", "auto")).lower()

                # Log available modules
                available_modules = [m.name for m in module_manager.registry.list_modules()]
                logger.info(f"Available modules: {available_modules}")

                # Engine priority based on config
                engines_to_try = []
                if preferred_engine == "auto":
                    engines_to_try = ["ollama_module", "mlx_module", "llama_cpp_module"]
                elif preferred_engine == "ollama":
                    engines_to_try = ["ollama_module", "mlx_module", "llama_cpp_module"]
                elif preferred_engine == "mlx":
                    engines_to_try = ["mlx_module", "ollama_module", "llama_cpp_module"]
                elif preferred_engine == "llamacpp":
                    engines_to_try = ["llama_cpp_module", "ollama_module", "mlx_module"]

                response_text = None
                for engine_name in engines_to_try:
                    logger.info(f"Trying engine: {engine_name}")
                    registration = module_manager.registry.get_module(engine_name)
                    if not registration:
                        logger.warning(f"{engine_name} not registered")
                        continue
                    if not registration.instance:
                        logger.warning(f"{engine_name} has no instance")
                        continue

                    manifest_module = registration.instance
                    # Get actual module instance via get_module_instance() function
                    if not hasattr(manifest_module, 'get_module_instance'):
                        logger.warning(f"{engine_name} has no get_module_instance()")
                        continue

                    engine = manifest_module.get_module_instance()
                    if not engine:
                        logger.warning(f"{engine_name} get_module_instance() returned None")
                        continue
                    if not hasattr(engine, 'chat'):
                        logger.warning(f"{engine_name} has no chat method")
                        continue

                    try:
                        # Resoldre ruta local del model si ve del selector UI
                        if body.get("model"):
                            from core.lifespan import get_server_state as _gss
                            models_dir = Path(os.getenv("NEXE_STORAGE_PATH", "storage")) / "models"
                            if not models_dir.is_absolute():
                                models_dir = Path(_gss().project_root) / models_dir
                            local_path = models_dir / model_name

                            if engine_name == "mlx_module" and local_path.exists():
                                os.environ["NEXE_MLX_MODEL"] = str(local_path)
                                from plugins.mlx_module.core.config import MLXConfig
                                new_config = MLXConfig.from_env()
                                if hasattr(engine, '_node') and engine._node:
                                    if engine._node.config.model_path != new_config.model_path:
                                        engine._node.config = new_config
                                        engine._node.__class__._config = new_config
                                        engine._node.__class__._model = None
                                        logger.info(f"MLX model switched to: {local_path}")

                            elif engine_name == "llama_cpp_module" and local_path.exists():
                                os.environ["NEXE_LLAMA_CPP_MODEL"] = str(local_path)
                                from plugins.llama_cpp_module.core.config import LlamaCppConfig
                                from plugins.llama_cpp_module.core.chat import LlamaCppChatNode
                                from plugins.llama_cpp_module.core.model_pool import ModelPool
                                new_config = LlamaCppConfig.from_env()
                                if hasattr(engine, '_node') and engine._node:
                                    old_path = engine._node.config.model_path
                                    if old_path != new_config.model_path:
                                        # Destruir pool antic i recrear amb nou config
                                        if LlamaCppChatNode._pool is not None:
                                            LlamaCppChatNode._pool.destroy_all()
                                        engine._node.config = new_config
                                        LlamaCppChatNode._config = new_config
                                        LlamaCppChatNode._pool = ModelPool(new_config)
                                        logger.info(f"Llama.cpp model switched to: {new_config.model_path}")

                        logger.info(f"Calling {engine_name}.chat with model={model_name}")

                        # --- Context Compacting ---
                        # Si la sessio te massa missatges, compactar amb resum LLM
                        await _compact_session(session, engine, session_mgr)

                        # --- Build Context ---
                        # 1. Get recent conversation history with summary context
                        context_messages_full = session.get_context_messages()
                        # Exclude the very last message (just added) to avoid duplication
                        context_messages = context_messages_full[:-1] if context_messages_full else []

                        # 2. Check for attached document (takes priority over RAG)
                        attached_doc = session.get_and_clear_attached_document()
                        session_mgr._save_session_to_disk(session)

                        document_context = ""
                        if attached_doc:
                            chunks = attached_doc.get('chunks', [attached_doc.get('content', '')])
                            total_chunks = attached_doc.get('total_chunks', len(chunks))
                            total_chars = attached_doc.get('total_chars', 0)

                            shown = len(chunks)
                            doc_content = "\n\n---\n\n".join(chunks)

                            if total_chunks == 1:
                                document_context = f"\n\nDOCUMENT ADJUNTAT ({attached_doc['filename']}):\n\n{doc_content}\n"
                            else:
                                est_pages_total = round(total_chars / 3000)
                                est_pages_shown = round(len(doc_content) / 3000)
                                pct = round(shown * 100 / total_chunks)
                                document_context = f"\n\nDOCUMENT ADJUNTAT ({attached_doc['filename']}):\n"
                                if shown < total_chunks:
                                    document_context += (
                                        f"[Mostrant les primeres ~{est_pages_shown} pagines de ~{est_pages_total} "
                                        f"({shown}/{total_chunks} parts, {pct}% del document). "
                                        f"La resta del document esta indexada — l'usuari pot fer preguntes "
                                        f"sobre qualsevol part i el sistema les recuperara.]\n\n"
                                    )
                                else:
                                    document_context += f"[Document complet: ~{est_pages_total} pagines]\n\n"
                                document_context += f"{doc_content}\n"

                            # Sanitize document context (prompt injection + control chars)
                            document_context = _sanitize_rag_context(document_context)
                            logger.info(f"Using attached document: {attached_doc['filename']} (parts {shown}/{total_chunks}, {len(doc_content)} chars)")

                        # 3. Get Memory Context (RAG) - SEMPRE buscar, no nomes amb patterns
                        rag_context = ""
                        rag_count = 0
                        _rag_items = []  # (collection, score) tuples for weight display
                        if not attached_doc:
                            try:
                                _active_colls = body.get("rag_collections")
                                recall_result = await memory_helper.recall_from_memory(message, limit=5, collections=_active_colls, session_id=session.id)
                                if recall_result["success"] and recall_result["results"]:
                                    # Filter by minimum score (configurable, default 0.30)
                                    rag_threshold = float(body.get("rag_threshold", 0.30))
                                    all_scores = [(r.get('metadata', {}).get('source_collection', '?'), r.get('score', 0)) for r in recall_result["results"]]
                                    logger.info("RAG pre-filter: %s results, threshold=%s, scores=%s", len(recall_result['results']), rag_threshold, all_scores)
                                    relevant = [r for r in recall_result["results"] if r.get("score", 0) >= rag_threshold]
                                    if relevant:
                                        rag_count = len(relevant)
                                        # Separate by collection: system docs, technical docs, memory
                                        doc_items = [r for r in relevant if r.get('metadata', {}).get('source_collection') == 'nexe_documentation']
                                        knowledge_items = [r for r in relevant if r.get('metadata', {}).get('source_collection') == 'user_knowledge']
                                        memory_items = [r for r in relevant if r.get('metadata', {}).get('source_collection') not in ('user_knowledge', 'nexe_documentation')]
                                        # RAG context labels per idioma (coincideixen amb system prompt)
                                        _rag_labels = {
                                            "ca": ("DOCUMENTACIO DEL SISTEMA", "DOCUMENTACIO TECNICA", "MEMORIA DE L'USUARI"),
                                            "es": ("DOCUMENTACION DEL SISTEMA", "DOCUMENTACION TECNICA", "MEMORIA DEL USUARIO"),
                                            "en": ("SYSTEM DOCUMENTATION", "TECHNICAL DOCUMENTATION", "USER MEMORY"),
                                        }
                                        _lang_key = _os.environ.get("NEXE_LANG", "ca").split("-")[0].lower()
                                        _labels = _rag_labels.get(_lang_key, _rag_labels["en"])
                                        if doc_items:
                                            rag_context += f"\n\n[{_labels[0]}]\n"
                                            for item in doc_items:
                                                rag_context += f"- {item['content']}\n"
                                        if knowledge_items:
                                            rag_context += f"\n\n[{_labels[1]}]\n"
                                            for item in knowledge_items:
                                                rag_context += f"- {item['content']}\n"
                                        if memory_items:
                                            rag_context += f"\n\n[{_labels[2]}]\n"
                                            for item in memory_items:
                                                rag_context += f"- {item['content']}\n"
                                        # Sanitize RAG context (prompt injection + control chars + truncate)
                                        rag_context = _sanitize_rag_context(rag_context)
                                        logger.info("RAG: %s relevant memories (score >= %s)", len(relevant), rag_threshold)
                                        for item in relevant:
                                            score = item.get('score', 0)
                                            col = item.get('metadata', {}).get('source_collection', '?')
                                            _rag_items.append((col, score))
                                            preview = item['content'][:80].replace('\n', ' ')
                                            logger.info(f"  RAG [{col}] score={score:.2f} -> {repr(preview)}")
                            except Exception as e:
                                logger.warning(f"RAG lookup failed: {e}")

                        # 4. Construct Final System Prompt
                        # Llegir el prompt de server.toml via app_state (llengua + tier)
                        try:
                            from core.lifespan import get_server_state
                            from core.endpoints.chat import _get_system_prompt
                            import os as _os_inner
                            _state = get_server_state()
                            _lang = _os_inner.getenv("NEXE_LANG", "ca")
                            base_system_prompt = _get_system_prompt(_state, _lang)
                        except Exception:
                            base_system_prompt = "You are Nexe, a local AI assistant. Respond clearly and helpfully."
                        # System prompt SEMPRE estatic (cachejable per MLX)
                        # El document o RAG van als messages[], no al system prompt
                        system_prompt = base_system_prompt

                        # 4. Prepare messages payload for engine
                        engine_messages = [
                            {"role": m["role"], "content": m["content"]}
                            for m in context_messages
                        ]

                        # Token budget: estimate total context and truncate if needed
                        MAX_CONTEXT_CHARS = int(_os.environ.get("NEXE_MAX_CONTEXT_CHARS", "24000"))
                        system_chars = len(system_prompt)
                        history_chars = sum(len(m.get("content", "")) for m in context_messages)
                        message_chars = len(message)
                        available_chars = MAX_CONTEXT_CHARS - system_chars - history_chars - message_chars - 500

                        # Injectar context als messages (no al system prompt -> MLX pot cachear el prefix)
                        if document_context and available_chars > 0:
                            document_context = document_context[:available_chars]
                            # Document adjuntat: va davant del missatge de l'usuari
                            doc_block = (
                                "[DOCUMENT ADJUNTAT]\n"
                                f"{document_context}\n"
                                "[FI DOCUMENT]\n\n"
                                "Respon EXCLUSIVAMENT basant-te en el document anterior. "
                                "Si la informacio no hi es, indica-ho clarament.\n\n"
                                f"{message}"
                            )
                            engine_messages.append({"role": "user", "content": doc_block})
                        elif rag_context and available_chars > 0:
                            rag_context = rag_context[:available_chars]
                            # Context RAG: docs sistema, docs tecnics, memoria
                            rag_block = f"[CONTEXT]\n{rag_context}[FI CONTEXT]\n\n{message}"
                            engine_messages.append({"role": "user", "content": rag_block})
                        else:
                            engine_messages.append({"role": "user", "content": message})

                        messages = engine_messages
                        response_chunks = []

                        # Adapt to different chat signatures
                        import inspect
                        sig = inspect.signature(engine.chat)

                        if 'model' in sig.parameters:
                            # Ollama-style: chat(model, messages, stream=...)
                            # We inject system prompt as first message for Ollama
                            full_messages = [{"role": "system", "content": system_prompt}] + messages
                            chat_result = engine.chat(model=model_name, messages=full_messages, stream=stream)
                        else:
                            # MLX/LlamaCpp-style: chat(messages, system=...)
                            if engine_name in ("mlx_module", "llama_cpp_module"):
                                # MLX module requires a callback for streaming
                                queue = asyncio.Queue()

                                _stream_chunk_count = [0]

                                def stream_cb(token):
                                    # MLXChatNode already marshals this to the main loop, so we can just put in queue
                                    _stream_chunk_count[0] += 1
                                    if _stream_chunk_count[0] <= 3 or _stream_chunk_count[0] % 50 == 0:
                                        logger.debug("stream_cb: chunk #%d (%d chars)", _stream_chunk_count[0], len(token))
                                    queue.put_nowait(token)

                                # Launch chat in background task
                                ml_task = asyncio.create_task(engine.chat(messages=messages, system=system_prompt, stream_callback=stream_cb))

                                # Async generator that yields from queue until task is done
                                async def queue_generator():
                                    while True:
                                        # Check if queue has items first
                                        if not queue.empty():
                                            yield await queue.get()
                                            continue

                                        # If queue is empty, check if task is done
                                        if ml_task.done():
                                            # If task failed, re-raise exception
                                            if ml_task.exception():
                                                raise ml_task.exception()
                                            break

                                        # Wait for new tokens with short timeout
                                        try:
                                            token = await asyncio.wait_for(queue.get(), timeout=0.05)
                                            yield token
                                        except asyncio.TimeoutError:
                                            continue

                                chat_result = queue_generator()

                            else:
                                chat_result = engine.chat(messages=messages, system=system_prompt)

                        # Flag si s'ha compactat per avisar al client
                        _compacted = session.compaction_count > 0 and session.context_summary is not None

                        if stream:
                            async def response_generator():
                                full_response = ""
                                _safe_model = str(model_name).replace("\x00", "").replace("]", "")[:100]
                                yield f"\x00[MODEL:{_safe_model}]\x00"
                                if rag_count > 0:
                                    yield f"\x00[RAG:{int(rag_count)}]\x00"
                                    # RAG weight details for UI/CLI display
                                    if _rag_items:
                                        avg_score = sum(s for _, s in _rag_items) / len(_rag_items)
                                        yield f"\x00[RAG_AVG:{avg_score:.2f}]\x00"
                                        for _col, _score in _rag_items:
                                            _safe_col = str(_col).replace("\x00", "").replace("|", "_")[:30]
                                            yield f"\x00[RAG_ITEM:{_safe_col}|{_score:.2f}]\x00"
                                if _compacted:
                                    yield f"\x00[COMPACT:{int(session.compaction_count)}]\x00"

                                # Check if model is loaded (Ollama, MLX, llama.cpp)
                                if hasattr(engine, 'is_model_loaded'):
                                    try:
                                        loaded = await engine.is_model_loaded(model_name)
                                        if not loaded:
                                            logger.info("Model %s not loaded — loading... [%s]", model_name, engine_name)
                                            yield f"\x00[MODEL_LOADING:{_safe_model}|{engine_name}]\x00"
                                    except Exception as e:
                                        logger.debug("Model loaded check failed for %s: %s", model_name, e)

                                try:
                                    # Handle both AsyncIterator (streaming) and direct coroutine response (non-streaming)
                                    if inspect.isasyncgen(chat_result) or hasattr(chat_result, '__aiter__'):
                                        _in_thinking = False
                                        _in_content_think = False
                                        _first_chunk = True
                                        _first_content_after_think = None
                                        _has_any_thinking = False
                                        _mem_tag_buf = ""  # Buffer for cross-chunk [MEM_SAVE: ...] tags
                                        async for chunk in chat_result:
                                            content = ""
                                            thinking = ""
                                            if isinstance(chunk, dict):
                                                # Ollama: thinking in separate field (qwen3.5, etc.)
                                                if "message" in chunk:
                                                    thinking = chunk["message"].get("thinking", "")
                                                    content = chunk["message"].get("content", "")
                                                elif "content" in chunk:
                                                    content = chunk["content"]
                                                elif "response" in chunk:
                                                    content = chunk["response"]
                                            elif isinstance(chunk, str):
                                                content = chunk

                                            # Model carregat — qualsevol chunk = model respon
                                            if _first_chunk:
                                                _first_chunk = False
                                                yield "\x00[MODEL_READY]\x00"

                                            # Stream thinking tokens wrapped in <think> tags
                                            if thinking:
                                                if not _in_thinking:
                                                    _in_thinking = True
                                                    _has_any_thinking = True
                                                    yield "<think>"
                                                    full_response += "<think>"
                                                yield thinking
                                                full_response += thinking
                                            elif _in_thinking:
                                                # Transition: thinking done, close tag
                                                _in_thinking = False
                                                yield "</think>"
                                                full_response += "</think>"

                                            if content:
                                                # GPT-OSS: NO netejar tags server-side
                                                # El client (_parseThinkingChannels) necessita
                                                # l'estructura analysis/assistant/final intacta
                                                _is_gpt_oss = "gpt-oss" in model_name.lower()
                                                if not _is_gpt_oss:
                                                    # Models normals: normalitzar thinking tags
                                                    content = content.replace('<|thinking|>', '<think>')
                                                    content = content.replace('<|/thinking|>', '</think>')
                                                    # Netejar tags (<|channel|>, ....) server-side
                                                    content = _re.sub(r'<\|[^|]+\|>', '', content)
                                                    content = _re.sub(r'[◁◀][^▷▶]*[▷▶]', '', content)
                                                full_response += content
                                                # Separar <think> blocks incrustats al content (qwq:32b, etc.)
                                                if '<think>' in content or '</think>' in content or _in_content_think:
                                                    _vis_parts = []
                                                    _sc = 0
                                                    while _sc < len(content):
                                                        if _in_content_think:
                                                            _te = content.find('</think>', _sc)
                                                            if _te >= 0:
                                                                _in_content_think = False
                                                                _sc = _te + 8
                                                            else:
                                                                break
                                                        else:
                                                            _ts = content.find('<think>', _sc)
                                                            if _ts >= 0:
                                                                if _ts > _sc:
                                                                    _vis_parts.append(content[_sc:_ts])
                                                                _in_content_think = True
                                                                _has_any_thinking = True
                                                                _sc = _ts + 7
                                                            else:
                                                                _vis_parts.append(content[_sc:])
                                                                break
                                                    visible = ''.join(_vis_parts)
                                                else:
                                                    visible = content
                                                # Strip [MEM_SAVE: ...] from visible stream (cross-chunk safe)
                                                visible = _mem_tag_buf + visible
                                                _mem_tag_buf = ""
                                                # Check for incomplete tag at end of chunk
                                                _bracket = visible.rfind('[')
                                                if _bracket >= 0 and ']' not in visible[_bracket:] and 'MEM' in visible[_bracket:]:
                                                    _mem_tag_buf = visible[_bracket:]
                                                    visible = visible[:_bracket]
                                                # Strip complete tags
                                                visible = _re.sub(r'\[MEM_SAVE:\s*.+?\]\s*', '', visible)
                                                if visible:
                                                    yield visible
                                    else:
                                        # Fallback for non-streaming engines
                                        yield "\x00[MODEL_READY]\x00"
                                        result = await chat_result if inspect.iscoroutine(chat_result) else chat_result
                                        content = ""
                                        if isinstance(result, dict):
                                            if "message" in result and "content" in result["message"]:
                                                content = result["message"]["content"]
                                            elif "content" in result:
                                                content = result["content"]
                                            elif "response" in result:
                                                content = result["response"]
                                        elif isinstance(result, str):
                                            content = result

                                        if content:
                                            full_response += content
                                            yield content

                                except Exception as e:
                                    err_msg = repr(e) if not str(e) else str(e)
                                    logger.error("Streaming error: %s", err_msg)
                                    yield f"\n[Error: {err_msg}]"

                                if not _has_any_thinking:
                                    logger.info("Model did not produce thinking tokens (model decides when to think)")

                                # Save clean response (no think/GPT-OSS tags) to session/disk
                                clean_response = full_response
                                clean_response = _re.sub(r"<think>[\s\S]*?</think>\s*", "", clean_response)
                                clean_response = _re.sub(r'<\|[^|]+\|>', '', clean_response)
                                clean_response = _re.sub(r'[◁◀][^▷▶]*[▷▶]', '', clean_response)
                                # GPT-OSS: extreure nomes la part "final" (resposta real)
                                _m = _re.search(r'(?:assistant\s*)?final\s*([\s\S]+)$', clean_response, _re.IGNORECASE)
                                if _m:
                                    clean_response = _m.group(1).strip()
                                else:
                                    # Fallback: treure prefix "analysis..." si hi es
                                    clean_response = _re.sub(r'^analysis\s*', '', clean_response, flags=_re.IGNORECASE).strip()
                                # Extract [MEM_SAVE: ...] facts from LLM response
                                _mem_saves = _re.findall(r'\[MEM_SAVE:\s*(.+?)\]', clean_response)
                                clean_response = _re.sub(r'\[MEM_SAVE:\s*.+?\]\s*', '', clean_response).strip()

                                if clean_response:
                                    session.add_message("assistant", clean_response)
                                    session_mgr._save_session_to_disk(session)

                                    # Save LLM-extracted facts to memory
                                    _mem_saved_count = 0
                                    # Junk patterns: false facts the model may generate
                                    _junk_patterns = _re.compile(
                                        r'(?i)(no\s+(coneix|s\.han|tinc|té|hi ha)|'
                                        r'no\s+s\.han\s+detectat|'
                                        r'busco\s+ajuda|necessit[oa]|'
                                        r'primera\s+interacci|'
                                        r'no\s+personal|sense\s+dades|'
                                        # English junk patterns
                                        r"I\s+don.t\s+(know|have)|no\s+information|"
                                        r"first\s+interaction|not\s+personal|no\s+data|"
                                        r"no\s+previous|cannot\s+recall|"
                                        # Prompt injection markers in facts
                                        r'\[MEM_SAVE|ignore\s+(all\s+)?previous|'
                                        r'system\s+prompt|override\s+instruction)',
                                    )
                                    for fact in _mem_saves:
                                        fact = fact.strip()
                                        if not fact or len(fact) < 5:
                                            continue
                                        # Filtrar fets negatius/brossa
                                        if _junk_patterns.search(fact):
                                            logger.debug("MEM_SAVE skip (junk): '%s'", fact[:80])
                                            continue
                                        try:
                                            result = await memory_helper.save_to_memory(
                                                content=fact,
                                                session_id=session.id,
                                                metadata={"type": "user_fact", "source": "llm_extract", "is_mem_save": True}
                                            )
                                            # Comptar nomes si realment s'ha guardat (no duplicat)
                                            if result.get("document_id"):
                                                _mem_saved_count += 1
                                                logger.info("MEM_SAVE: '%s'", fact[:80])
                                            else:
                                                logger.debug("MEM_SAVE skip (dedup): '%s'", fact[:80])
                                        except Exception as e:
                                            logger.debug("MEM_SAVE failed: %s", e)
                                    if _mem_saved_count > 0:
                                        yield f"\x00[MEM:{_mem_saved_count}]\x00"

                            return StreamingResponse(
                                response_generator(),
                                media_type="text/plain",
                                headers={
                                    "Cache-Control": "no-cache, no-store",
                                    "X-Accel-Buffering": "no",
                                    "X-Content-Type-Options": "nosniff",
                                }
                            )

                        # Handle non-streaming response accumulation
                        if inspect.isasyncgen(chat_result) or hasattr(chat_result, '__aiter__'):
                            async for chunk in chat_result:
                                if isinstance(chunk, dict) and "message" in chunk and "content" in chunk["message"]:
                                    response_chunks.append(chunk["message"]["content"])
                                elif isinstance(chunk, dict) and "content" in chunk:
                                    response_chunks.append(chunk["content"])
                                elif isinstance(chunk, str):
                                    response_chunks.append(chunk)
                        else:
                            # Await if it's a coroutine (direct result)
                            result = await chat_result if inspect.iscoroutine(chat_result) else chat_result
                            if isinstance(result, dict):
                                if "message" in result and "content" in result["message"]:
                                    response_chunks.append(result["message"]["content"])
                                elif "content" in result:
                                    response_chunks.append(result["content"])
                                elif "response" in result:
                                    response_chunks.append(result["response"])
                            elif isinstance(result, str):
                                response_chunks.append(result)

                        response_text = "".join(response_chunks)
                        if response_text:
                            logger.info(f"{engine_name} succeeded!")
                            break
                    except Exception as e:
                        logger.warning(f"{engine_name} failed: {e}")
                        logger.debug("Engine error details:", exc_info=True)
                        continue

                if not response_text:
                    response_text = "Error: No AI engine available (try starting Ollama with 'ollama serve')"
            except Exception as e:
                logger.error(f"Error calling LLM: {e}")
                response_text = f"Error: {str(e)}"

        # Strip MEM_SAVE tags i extreure fets (non-streaming path)
        if response_text and intent == "chat" and not response_text.startswith("Error:"):
            # Netejar thinking tags
            response_text = _re.sub(r"<think>[\s\S]*?</think>\s*", "", response_text)
            response_text = _re.sub(r'<\|[^|]+\|>', '', response_text)
            # GPT-OSS: extreure nomes la part "final"
            _m_ns = _re.search(r'(?:assistant\s*)?final\s*([\s\S]+)$', response_text, _re.IGNORECASE)
            if _m_ns:
                response_text = _m_ns.group(1).strip()
            else:
                response_text = _re.sub(r'^analysis\s*', '', response_text, flags=_re.IGNORECASE).strip()
            # Extreure [MEM_SAVE: ...] fets abans de strip
            _mem_saves_ns = _re.findall(r'\[MEM_SAVE:\s*(.+?)\]', response_text)
            response_text = _re.sub(r'\[MEM_SAVE:\s*.+?\]\s*', '', response_text).strip()
            # Save extracted facts to memory
            if _mem_saves_ns:
                _junk_re = _re.compile(
                    r'(?i)(no\s+(coneix|s.han|tinc|té|hi ha)|'
                    r'no\s+s.han\s+detectat|busco\s+ajuda|necessit[oa]|'
                    r'primera\s+interacci|no\s+personal|sense\s+dades)',
                )
                for _fact in _mem_saves_ns:
                    _fact = _fact.strip()
                    if not _fact or len(_fact) < 5:
                        continue
                    if _junk_re.search(_fact):
                        logger.debug("MEM_SAVE skip (junk/no-stream): '%s'", _fact[:80])
                        continue
                    try:
                        _save_r = await memory_helper.save_to_memory(
                            content=_fact,
                            session_id=session.id,
                            metadata={"type": "user_fact", "source": "llm_extract", "is_mem_save": True}
                        )
                        if _save_r.get("document_id"):
                            logger.info("MEM_SAVE (no-stream): '%s'", _fact[:80])
                    except Exception as e:
                        logger.debug("MEM_SAVE failed (no-stream): %s", e)

        session.add_message("assistant", response_text)
        session_mgr._save_session_to_disk(session)

        # AUTO-SAVE: guarda missatge usuari directament (sense LLM)
        if response_text and not response_text.startswith("Error:") and not response_text.startswith("What do you want"):
            try:
                save_result = await memory_helper.auto_save(
                    user_message=message,
                    session_id=session.id,
                )
                if save_result.get("document_id"):
                    logger.debug(f"Auto-saved to RAG: {message[:40]}")
            except Exception as e:
                logger.warning(f"Auto-save to RAG failed: {e}")

        if stream:
            async def generate():
                for char in response_text:
                    yield char
            return StreamingResponse(generate(), media_type="text/plain")
        else:
            return {
                "response": response_text,
                "session_id": session.id,
                "intent": intent,
                "memory_action": memory_action
            }
