"""
────────────────────────────────────
Server Nexe
Version: 0.8
Author: Jordi Goy
Location: plugins/web_ui_module/manifest.py
Description: Router FastAPI per mòdul Web UI.

www.jgoy.net
────────────────────────────────────
"""

from pathlib import Path
from typing import Dict, Any, Optional
import asyncio
import logging
from fastapi import APIRouter, HTTPException, UploadFile, File, Form
from fastapi.responses import HTMLResponse, FileResponse, StreamingResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
import logging

from .session_manager import SessionManager
from .file_handler import FileHandler
from .memory_helper import get_memory_helper
from .i18n import t

# Import RAG header parser
try:
    from memory.rag.header_parser import parse_rag_header
except ImportError:
    parse_rag_header = None

logger = logging.getLogger(__name__)

# Module state
_session_manager = SessionManager()
_file_handler = None
_static_dir = Path(__file__).parent / "static"
_initialized = False

# Initialize directories
_static_dir.mkdir(parents=True, exist_ok=True)
(_static_dir / "uploads").mkdir(parents=True, exist_ok=True)
_file_handler = FileHandler(_static_dir / "uploads")

# Create router
router_public = APIRouter(prefix="/ui", tags=["ui", "web", "demo"])


# Endpoints
@router_public.get("/", response_class=HTMLResponse)
async def serve_ui():
    """Servir la pàgina principal"""
    html_path = _static_dir / "index.html"
    if html_path.exists():
        return FileResponse(html_path)
    raise HTTPException(status_code=404, detail=t("web_ui.http.ui_not_found", "UI not found"))


@router_public.get("/static/{filename}")
async def serve_static(filename: str):
    """Servir CSS/JS"""
    from fastapi.responses import Response

    file_path = _static_dir / filename
    if not file_path.exists():
        raise HTTPException(status_code=404, detail=t("web_ui.http.file_not_found", "File not found"))

    # Determine media type
    if file_path.suffix == ".css":
        media_type = "text/css; charset=utf-8"
    elif file_path.suffix == ".js":
        media_type = "application/javascript; charset=utf-8"
    else:
        media_type = "text/plain"

    # Read file and return as Response with proper headers
    content = file_path.read_bytes()
    return Response(
        content=content,
        media_type=media_type,
        headers={
            "Cache-Control": "public, max-age=3600",
            "Content-Length": str(len(content))
        }
    )


@router_public.post("/session/new")
async def create_session(request: Optional[Dict[str, Any]] = None):
    """Crear nova sessió"""
    session = _session_manager.create_session()
    return {
        "session_id": session.id,
        "created_at": session.created_at.isoformat()
    }


@router_public.get("/session/{session_id}")
async def get_session_info(session_id: str):
    """Obtenir info de sessió"""
    session = _session_manager.get_session(session_id)
    if not session:
        raise HTTPException(status_code=404, detail=t("web_ui.http.session_not_found", "Session not found"))
    return session.to_dict()


@router_public.get("/session/{session_id}/history")
async def get_session_history(session_id: str):
    """Obtenir historial de sessió"""
    session = _session_manager.get_session(session_id)
    if not session:
        raise HTTPException(status_code=404, detail=t("web_ui.http.session_not_found", "Session not found"))
    return {"messages": session.get_history()}


@router_public.delete("/session/{session_id}")
async def delete_session(session_id: str):
    """Eliminar sessió"""
    deleted = _session_manager.delete_session(session_id)
    if not deleted:
        raise HTTPException(status_code=404, detail=t("web_ui.http.session_not_found", "Session not found"))
    return {"status": t("web_ui.session.deleted", "deleted")}


@router_public.get("/sessions")
async def list_sessions():
    """Llistar totes les sessions"""
    return {"sessions": _session_manager.list_sessions()}


@router_public.post("/upload")
async def upload_file(
    file: UploadFile = File(...),
    session_id: Optional[str] = Form(None)
):
    """Pujar fitxer i afegir al context de la sessió + ingesta automàtica a memòria"""
    content = await file.read()
    valid, error = _file_handler.validate_file(file.filename, len(content))
    if not valid:
        raise HTTPException(status_code=400, detail=error)

    file_path = await _file_handler.save_file(file.filename, content)
    text = _file_handler.extract_text(file_path)
    if not text:
        _file_handler.delete_file(file_path)
        raise HTTPException(status_code=400, detail=t("web_ui.http.extract_text_failed", "Could not extract text from file"))

    # Parse RAG header if available
    rag_header = None
    body_content = text
    doc_metadata = {
        "filename": file.filename,
        "upload_type": "file",
        "size": len(content),
        "source": "web_ui"
    }

    if parse_rag_header:
        rag_header, body_content = parse_rag_header(text)
        if rag_header.is_valid:
            doc_metadata.update({
                "doc_id": rag_header.id,
                "abstract": rag_header.abstract,
                "tags": rag_header.tags,
                "priority": rag_header.priority,
                "type": rag_header.type,
                "lang": rag_header.lang,
                "collection": rag_header.collection
            })
            logger.info(f"RAG header found: id={rag_header.id}, priority={rag_header.priority}")

    # Ingest document into memory system automatically
    memory_helper = get_memory_helper()
    ingestion_result = await memory_helper.save_to_memory(
        content=body_content,
        session_id=session_id or "web_ui_upload",
        metadata=doc_metadata
    )

    logger.info(f"Document '{file.filename}' ingested: {ingestion_result.get('message', 'OK')}")

    # Attach document to session for immediate use in next chat
    session = _session_manager.get_or_create_session(session_id)
    session.add_context_file(file.filename)

    # Chunk large documents (use header chunk_size if available)
    chunk_size = rag_header.chunk_size if (rag_header and rag_header.is_valid) else 2500
    chunks = _file_handler.chunk_text(body_content, chunk_size=chunk_size)
    session.attach_document(file.filename, body_content, chunks)
    _session_manager._save_session_to_disk(session)

    logger.info(f"Document '{file.filename}' attached with {len(chunks)} chunks")

    return {
        "filename": file.filename,
        "size": len(content),
        "text_length": len(text),
        "preview": body_content[:500] + "..." if len(body_content) > 500 else body_content,
        "ingested": ingestion_result.get("success", False),
        "memory_id": ingestion_result.get("entry_id"),
        "session_id": session.id,
        "has_rag_header": rag_header.is_valid if rag_header else False
    }


@router_public.get("/files")
async def list_uploaded_files():
    """Llistar tots els fitxers pujats"""
    files = _file_handler.get_uploaded_files()
    return {"files": files, "total": len(files)}


@router_public.post("/files/cleanup")
async def cleanup_files(max_age_hours: int = 24):
    """Netejar fitxers antics (per defecte > 24h)"""
    deleted = _file_handler.cleanup_old_files(max_age_hours)
    return {
        "deleted": deleted,
        "message": t(
            "web_ui.cleanup.deleted_message",
            "{count} files deleted",
            count=deleted
        )
    }


@router_public.post("/chat")
async def chat(request: Dict[str, Any]):
    """Endpoint de xat amb streaming i detecció d'intencions de memòria"""
    message = request.get("message", "")
    session_id = request.get("session_id")
    stream = request.get("stream", False)

    if not message:
        raise HTTPException(status_code=400, detail=t("web_ui.http.message_required", "Message is required"))

    session = _session_manager.get_or_create_session(session_id)
    session.add_message("user", message)
    _session_manager._save_session_to_disk(session)

    # Detect intent (save, recall, or chat)
    memory_helper = get_memory_helper()
    intent, extracted_content = memory_helper.detect_intent(message)

    response_text = ""
    memory_action = None

    if intent == "save":
        # Save to memory
        content_to_save = extracted_content.strip() if extracted_content else message
        # Clean up content (remove trailing punctuation from save request)
        content_to_save = content_to_save.rstrip('?¿!').strip()

        if content_to_save:
            result = await memory_helper.save_to_memory(
                content=content_to_save,
                session_id=session.id,
                metadata={"original_message": message, "type": "user_fact"}
            )
            if result["success"]:
                response_text = t(
                    "web_ui.memory.save_success",
                    "✅ Saved to memory: \"{content}\"\n\nI will remember this for future conversations.",
                    content=content_to_save
                )
            else:
                response_text = t(
                    "web_ui.memory.save_failed",
                    "❌ Could not save: {error}",
                    error=result.get("message", t("web_ui.memory.unknown_error", "Unknown error"))
                )
        else:
            response_text = t(
                "web_ui.memory.save_prompt",
                "❓ What would you like me to save? Write what you want me to remember."
            )
        memory_action = "save"

    elif intent == "recall":
        # Recall intent: DON'T show raw results, use LLM with memory context
        # Falls through to normal chat processing with memory search
        memory_action = "recall"
        intent = "chat"  # Treat as chat so LLM responds naturally

    if intent == "chat":
        # Normal chat - Auto-detect and use available LLM engine
        try:
            from core.container import get_service
            import os

            module_manager = get_service("module_manager")
            model_name = os.getenv("NEXE_DEFAULT_MODEL", "llama3.2:3b")
            preferred_engine = os.getenv("NEXE_MODEL_ENGINE", "auto").lower()

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
                    logger.info(f"Calling {engine_name}.chat with model={model_name}")
                    
                    # --- Build Context ---
                    # 1. Get recent conversation history from session
                    history_messages = session.get_history() # [{"role": "user", ...}, ...]
                    # Exclude the very last message we just added to avoid duplication if engine adds it
                    context_messages = history_messages[:-1]

                    # 2. Check for attached document (takes priority over RAG)
                    attached_doc = session.get_and_clear_attached_document()
                    _session_manager._save_session_to_disk(session)

                    document_context = ""
                    if attached_doc:
                        chunks = attached_doc.get('chunks', [attached_doc.get('content', '')])
                        total_chunks = len(chunks)
                        total_chars = attached_doc.get('total_chars', 0)

                        if total_chunks == 1:
                            # Document petit - passar sencer
                            doc_content = chunks[0][:3500]
                            document_context = t(
                                "web_ui.document.attached_single",
                                "\n\nATTACHED DOCUMENT ({filename}):\n\n{content}\n",
                                filename=attached_doc["filename"],
                                content=doc_content
                            )
                        else:
                            # Document gran - passar primer chunk amb info
                            doc_content = chunks[0]
                            document_context = t(
                                "web_ui.document.attached_multi_intro",
                                "\n\nATTACHED DOCUMENT ({filename}):\n",
                                filename=attached_doc["filename"]
                            )
                            document_context += t(
                                "web_ui.document.attached_multi_meta",
                                "[Large document: {total_chars} characters split into {total_chunks} parts. Showing part {part}/{total_chunks}]\n\n",
                                total_chars=total_chars,
                                total_chunks=total_chunks,
                                part=1
                            )
                            document_context += f"{doc_content}\n"
                            document_context += t(
                                "web_ui.document.attached_multi_footer",
                                "\n[End of part {part}/{total_chunks}. The user can ask 'continue' or 'next part' to see more.]\n",
                                part=1,
                                total_chunks=total_chunks
                            )

                        logger.info(f"Using attached document: {attached_doc['filename']} (chunk 1/{total_chunks}, {len(doc_content)} chars)")

                    # 3. Get Memory Context (RAG) - SEMPRE buscar, no només amb patterns
                    rag_context = ""
                    if not attached_doc:
                        try:
                            recall_result = await memory_helper.recall_from_memory(message, limit=5)
                            if recall_result["success"] and recall_result["results"]:
                                # Filtrar per score mínim (0.5) per evitar soroll
                                relevant = [r for r in recall_result["results"] if r.get("score", 0) >= 0.5]
                                if relevant:
                                    rag_context = t(
                                        "web_ui.memory.context_header",
                                        "\n\n[MEMORY - Relevant information saved earlier:]\n"
                                    )
                                    for item in relevant:
                                        rag_context += f"- {item['content']}\n"
                                    logger.info(f"RAG: {len(relevant)} memories relevants (score >= 0.5)")
                        except Exception as e:
                            logger.warning(f"RAG lookup failed: {e}")

                    # 4. Construct Final System Prompt
                    base_system_prompt = t(
                        "web_ui.prompts.base_system",
                        "You are Nexe, a private and secure local AI assistant."
                    )
                    if document_context:
                        # MODE ZEN: Prompt restrictiu que FORÇA resposta basada en document
                        # Evita al·lucinacions forçant el model a cenyir-se al contingut
                        system_prompt = t(
                            "web_ui.prompts.document_mode",
                            "# DOCUMENT MODE: DOCUMENT ASSISTANT\n\n"
                            "CRITICAL INSTRUCTIONS - FOLLOW STRICTLY:\n\n"
                            "1. Answer ONLY and EXCLUSIVELY based on the document provided below\n"
                            "2. Do NOT invent information that is not in the document\n"
                            "3. Do NOT hallucinate or add external data\n"
                            "4. If the information does NOT appear in the document, say clearly: \"This information does not appear in the provided document\"\n"
                            "5. Quote verbatim fragments from the document when possible\n"
                            "6. Be precise and concise\n"
                            "7. Respond in the same language as the user\n\n"
                            "---\n\n"
                            "ATTACHED DOCUMENT:\n"
                            "{document_context}\n\n"
                            "---\n\n"
                            "Now answer the user's question based EXCLUSIVELY on the previous document. If you cannot answer with the document information, say so.",
                            document_context=document_context
                        )
                    elif rag_context:
                        system_prompt = t(
                            "web_ui.prompts.rag_context",
                            "{base_system_prompt}\n\n"
                            "INTERNAL CONTEXT (Do not show to user, only use to respond):\n"
                            "{rag_context}\n\n"
                            "IMPORTANT: The previous context is background information. Do NOT include it in your response. Respond naturally using the information if relevant.",
                            base_system_prompt=base_system_prompt,
                            rag_context=rag_context
                        )
                    else:
                        system_prompt = base_system_prompt

                    # 4. Prepare messages payload for engine
                    # Most engines expect just the new message if they manage history, OR full history.
                    # MLXChatNode manages its own KV cache but expects 'messages' to be the NEW messages to process
                    # if we want to rely on its cache for history. HOWEVER, simple stateless engines need full history.
                    
                    # For robust history, we send the full conversation history.
                    # We need to transform session messages to the format expected by engines
                    engine_messages = [
                        {"role": m["role"], "content": m["content"]} 
                        for m in context_messages
                    ]
                    # Add current user message
                    engine_messages.append({"role": "user", "content": message})


                    messages = engine_messages
                    response_chunks = []
                    
                    # Adapt to different chat signatures
                    import inspect
                    sig = inspect.signature(engine.chat)
                    
                    if 'model' in sig.parameters:
                        # Ollama-style: chat(model, messages, stream=...)
                        # Check if it supports system prompt in messages or as separate arg (Ollama supports 'system' in messages)
                        # We inject system prompt as first message for Ollama
                        full_messages = [{"role": "system", "content": system_prompt}] + messages
                        chat_result = engine.chat(model=model_name, messages=full_messages, stream=stream)
                    else:
                        # MLX/LlamaCpp-style: chat(messages, system=...)
                        if engine_name == "mlx_module" and stream:
                            # MLX module requires a callback for streaming
                            queue = asyncio.Queue()
                            
                            def stream_cb(token):
                                # MLXChatNode already marshals this to the main loop, so we can just put in queue
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
                    
                    if stream:
                        async def response_generator():
                            full_response = ""
                            try:
                                # Handle both AsyncIterator (streaming) and direct coroutine response (non-streaming)
                                if inspect.isasyncgen(chat_result) or hasattr(chat_result, '__aiter__'):
                                    async for chunk in chat_result:
                                        content = ""
                                        if isinstance(chunk, dict):
                                            if "message" in chunk and "content" in chunk["message"]:
                                                content = chunk["message"]["content"]
                                            elif "content" in chunk:
                                                content = chunk["content"]
                                            elif "response" in chunk:
                                                content = chunk["response"]
                                        elif isinstance(chunk, str):
                                            content = chunk
                                        
                                        if content:
                                            full_response += content
                                            yield content
                                else:
                                    # Fallback for non-streaming engines
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
                                logger.error(f"Streaming error: {e}")
                                yield t(
                                    "web_ui.chat.stream_error",
                                    "\n[Error: {error}]",
                                    error=str(e)
                                )
                            
                            # Save to session/disk after streaming completes
                            if full_response:
                                session.add_message("assistant", full_response)
                                _session_manager._save_session_to_disk(session)

                                # SMART AUTO-SAVE to RAG (streaming)
                                if not full_response.startswith("❌"):
                                    try:
                                        await memory_helper.smart_save(
                                            user_message=message,
                                            assistant_response=full_response,
                                            session_id=session.id,
                                            model_name=model_name
                                        )
                                    except Exception as e:
                                        logger.debug("RAG auto-save failed: %s", e)
                                
                        return StreamingResponse(response_generator(), media_type="text/plain")

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
                        logger.info(f"✅ {engine_name} succeeded!")
                        break
                except Exception as e:
                    logger.warning(f"{engine_name} failed: {e}")
                    logger.debug("Engine error details:", exc_info=True)
                    continue

            if not response_text:
                response_text = t(
                    "web_ui.http.engine_unavailable",
                    "❌ Error: No AI engine available (try starting Ollama with 'ollama serve')"
                )
        except Exception as e:
            logger.error(f"Error calling LLM: {e}")
            response_text = t(
                "web_ui.http.error_generic",
                "❌ Error: {error}",
                error=str(e)
            )

    session.add_message("assistant", response_text)
    _session_manager._save_session_to_disk(session)

    # SMART AUTO-SAVE to RAG: Extreure fets rellevants i guardar
    # Només guardar si no és un error i la resposta té contingut útil
    if response_text and not response_text.startswith("❌") and not response_text.startswith("❓"):
        try:
            # Usar smart_save: extreu fets, no guarda xerrameca
            # model_name ve del bloc chat (si existeix)
            save_result = await memory_helper.smart_save(
                user_message=message,
                assistant_response=response_text,
                session_id=session.id,
                model_name=locals().get('model_name')
            )
            if save_result.get("document_id"):
                logger.debug(f"Smart-saved to RAG: {save_result.get('message')}")
            else:
                logger.debug(f"No save needed: {save_result.get('message')}")
        except Exception as e:
            logger.warning(f"Smart auto-save to RAG failed: {e}")

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


@router_public.post("/memory/save")
async def memory_save(request: Dict[str, Any]):
    """Guardar contingut explícitament a la memòria"""
    content = request.get("content", "")
    session_id = request.get("session_id", "unknown")
    metadata = request.get("metadata", {})

    if not content:
        raise HTTPException(status_code=400, detail=t("web_ui.http.content_required", "Content is required"))

    memory_helper = get_memory_helper()
    result = await memory_helper.save_to_memory(
        content=content,
        session_id=session_id,
        metadata=metadata
    )

    return result


@router_public.post("/memory/recall")
async def memory_recall(request: Dict[str, Any]):
    """Cercar a la memòria"""
    query = request.get("query", "")
    limit = request.get("limit", 5)

    if not query:
        raise HTTPException(status_code=400, detail=t("web_ui.http.query_required", "Query is required"))

    memory_helper = get_memory_helper()
    result = await memory_helper.recall_from_memory(
        query=query,
        limit=limit
    )

    return result


@router_public.get("/health")
async def health():
    """Health check del plugin"""
    return {
        "status": "healthy",
        "initialized": True,
        "sessions": len(_session_manager.list_sessions())
    }


# Module instance getter
def get_module_instance():
    """Get module instance (compatibility)."""
    from .module import WebUIModule
    return WebUIModule()
