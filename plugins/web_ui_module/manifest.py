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
from fastapi import APIRouter, HTTPException, UploadFile, File, Form, Depends, Header
from fastapi.responses import HTMLResponse, FileResponse, StreamingResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from .session_manager import SessionManager
from .file_handler import FileHandler
from .memory_helper import get_memory_helper
from plugins.security.core.auth_config import get_admin_api_key

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

# Initialize directories
_static_dir.mkdir(parents=True, exist_ok=True)
(_static_dir / "uploads").mkdir(parents=True, exist_ok=True)
_file_handler = FileHandler(_static_dir / "uploads")

# Create router
router_public = APIRouter(prefix="/ui", tags=["ui", "web", "demo"])


async def _require_ui_auth(x_api_key: Optional[str] = Header(None)):
    """Valida API key per a endpoints de la Web UI"""
    expected = get_admin_api_key()
    if expected and x_api_key != expected:
        raise HTTPException(status_code=401, detail="Invalid or missing API key")


# Endpoints
@router_public.get("/auth")
async def verify_auth(_auth=Depends(_require_ui_auth)):
    """Verificar API key"""
    return {"status": "ok"}


@router_public.get("/info")
async def get_ui_info(_auth=Depends(_require_ui_auth)):
    """Info del model i backend actiu"""
    import os
    model_name = os.getenv("NEXE_DEFAULT_MODEL", "unknown")
    backend = os.getenv("NEXE_MODEL_ENGINE", "auto")
    try:
        from core.lifespan import get_server_state
        version = get_server_state().config.get('meta', {}).get('version', '0.8')
    except Exception:
        version = "0.8"
    return {
        "model": model_name,
        "backend": backend,
        "version": version
    }


@router_public.get("/", response_class=HTMLResponse)
async def serve_ui():
    """Servir la pàgina principal"""
    html_path = _static_dir / "index.html"
    if html_path.exists():
        return FileResponse(html_path)
    raise HTTPException(status_code=404, detail="UI not found")


@router_public.get("/static/{filename:path}")
async def serve_static(filename: str):
    """Servir CSS/JS"""
    from fastapi.responses import Response

    file_path = (_static_dir / filename).resolve()
    if not str(file_path).startswith(str(_static_dir.resolve())):
        raise HTTPException(status_code=403, detail="Forbidden")
    if not file_path.exists():
        raise HTTPException(status_code=404, detail="File not found")

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
async def create_session(request: Optional[Dict[str, Any]] = None, _auth=Depends(_require_ui_auth)):
    """Crear nova sessió"""
    session = _session_manager.create_session()
    return {
        "session_id": session.id,
        "created_at": session.created_at.isoformat()
    }


@router_public.get("/session/{session_id}")
async def get_session_info(session_id: str, _auth=Depends(_require_ui_auth)):
    """Obtenir info de sessió"""
    session = _session_manager.get_session(session_id)
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")
    return session.to_dict()


@router_public.get("/session/{session_id}/history")
async def get_session_history(session_id: str, _auth=Depends(_require_ui_auth)):
    """Obtenir historial de sessió"""
    session = _session_manager.get_session(session_id)
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")
    return {"messages": session.get_history()}


@router_public.delete("/session/{session_id}")
async def delete_session(session_id: str, _auth=Depends(_require_ui_auth)):
    """Eliminar sessió"""
    deleted = _session_manager.delete_session(session_id)
    if not deleted:
        raise HTTPException(status_code=404, detail="Session not found")
    return {"status": "deleted"}


@router_public.get("/sessions")
async def list_sessions(_auth=Depends(_require_ui_auth)):
    """Llistar totes les sessions"""
    return {"sessions": _session_manager.list_sessions()}


@router_public.post("/upload")
async def upload_file(
    file: UploadFile = File(...),
    session_id: Optional[str] = Form(None),
    _auth=Depends(_require_ui_auth)
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
        raise HTTPException(status_code=400, detail="Could not extract text from file")

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
        else:
            # Autogenerar metadades bàsiques per millorar la cerca semàntica
            import os as _upos
            stem = Path(file.filename).stem.replace("_", " ").replace("-", " ")
            _lang = _upos.getenv("NEXE_LANG", "ca").split("-")[0].lower()
            # Abstract: primer paràgraf substantiu (màx 400 chars)
            _abstract = " ".join(body_content.split())[:400]
            doc_metadata.update({
                "abstract": _abstract,
                "tags": [stem],
                "priority": "P2",
                "type": "docs",
                "lang": _lang,
            })
            logger.info(f"No RAG header — metadades autogenerades per '{file.filename}'")

    # Chunk size adaptat a la mida del document per equilibrar precisió i cobertura:
    #   < 20K chars  (~7 pàg)   → 800   (màxima precisió)
    #   < 100K chars (~33 pàg)  → 1000
    #   < 300K chars (~100 pàg) → 1200
    #   >= 300K chars (>100 pàg)→ 1500  (docs molt grans: manté coherència per chunk)
    if rag_header and rag_header.is_valid:
        chunk_size = rag_header.chunk_size
    else:
        _doc_len = len(body_content)
        if _doc_len < 20_000:
            chunk_size = 800
        elif _doc_len < 100_000:
            chunk_size = 1000
        elif _doc_len < 300_000:
            chunk_size = 1200
        else:
            chunk_size = 1500
        logger.info(f"chunk_size auto={chunk_size} per {_doc_len} chars ({file.filename})")
    chunks = _file_handler.chunk_text(body_content, chunk_size=chunk_size)
    logger.info(f"Document '{file.filename}': {len(body_content)} chars → {len(chunks)} chunks (chunk_size={chunk_size})")

    # Ingest all chunks individually to nexe_web_ui (one embedding per chunk)
    memory_helper = get_memory_helper()
    ingestion_result = await memory_helper.save_document_chunks(
        chunks=chunks,
        filename=file.filename,
        session_id=session_id or "web_ui_upload",
        metadata=doc_metadata,
    )

    # Attach to session
    session = _session_manager.get_or_create_session(session_id)
    session.add_context_file(file.filename)

    # Attach to session: small=full, large=first 50 chunks (~30K tokens amb context 65K)
    MAX_PREVIEW_CHUNKS = 50
    preview_chunks = chunks[:MAX_PREVIEW_CHUNKS]
    session.attach_document(file.filename, body_content, preview_chunks, total_chunks=len(chunks))
    logger.info(f"Document '{file.filename}' attached ({len(preview_chunks)}/{len(chunks)} chunks) + RAG-ready")

    _session_manager._save_session_to_disk(session)

    return {
        "filename": file.filename,
        "size": len(content),
        "text_length": len(text),
        "chunks": len(chunks),
        "preview": body_content[:500] + "..." if len(body_content) > 500 else body_content,
        "ingested": ingestion_result.get("success", False),
        "chunks_saved": ingestion_result.get("chunks_saved", 0),
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
    return {"deleted": deleted, "message": f"{deleted} fitxers eliminats"}


@router_public.post("/chat")
async def chat(request: Dict[str, Any], _auth=Depends(_require_ui_auth)):
    """Endpoint de xat amb streaming i detecció d'intencions de memòria"""
    message = request.get("message", "")
    session_id = request.get("session_id")
    stream = request.get("stream", False)

    if not message:
        raise HTTPException(status_code=400, detail="Message is required")

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
                response_text = f"✅ Guardat a la memòria: \"{content_to_save}\"\n\nHo recordaré per a futures converses.\x00[MEM]\x00"
            else:
                response_text = f"❌ No s'ha pogut guardar: {result.get('message', 'Error desconegut')}"
        else:
            response_text = "❓ Què vols que guardi? Escriu el que vols recordar."
        memory_action = "save"

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
                                    f"[Mostrant les primeres ~{est_pages_shown} pàgines de ~{est_pages_total} "
                                    f"({shown}/{total_chunks} parts, {pct}% del document). "
                                    f"La resta del document està indexada — l'usuari pot fer preguntes "
                                    f"sobre qualsevol part i el sistema les recuperarà.]\n\n"
                                )
                            else:
                                document_context += f"[Document complet: ~{est_pages_total} pàgines]\n\n"
                            document_context += f"{doc_content}\n"

                        logger.info(f"Using attached document: {attached_doc['filename']} (parts {shown}/{total_chunks}, {len(doc_content)} chars)")

                    # 3. Get Memory Context (RAG) - SEMPRE buscar, no només amb patterns
                    rag_context = ""
                    if not attached_doc:
                        try:
                            recall_result = await memory_helper.recall_from_memory(message, limit=5)
                            if recall_result["success"] and recall_result["results"]:
                                # Filtrar per score mínim (0.5) per evitar soroll
                                relevant = [r for r in recall_result["results"] if r.get("score", 0) >= 0.5]
                                if relevant:
                                    rag_context = "\n\n[MEMÒRIA - Informació rellevant guardada anteriorment:]\n"
                                    for item in relevant:
                                        rag_context += f"- {item['content']}\n"
                                    logger.info(f"RAG: {len(relevant)} memories relevants (score >= 0.5)")
                                    for item in relevant:
                                        score = item.get('score', 0)
                                        col = item.get('metadata', {}).get('source_collection', '?')
                                        preview = item['content'][:80].replace('\n', ' ')
                                        logger.info(f"  RAG [{col}] score={score:.2f} → {repr(preview)}")
                        except Exception as e:
                            logger.warning(f"RAG lookup failed: {e}")

                    # 4. Construct Final System Prompt
                    # Llegir el prompt de server.toml via app_state (llengua + tier)
                    try:
                        from core.lifespan import get_server_state
                        from core.endpoints.chat import _get_system_prompt
                        import os as _os
                        _state = get_server_state()
                        _lang = _os.getenv("NEXE_LANG", "ca")
                        base_system_prompt = _get_system_prompt(_state, _lang)
                    except Exception:
                        base_system_prompt = "You are Nexe, a local AI assistant. Respond clearly and helpfully."
                    # System prompt SEMPRE estàtic (cachejable per MLX)
                    # El document o RAG van als messages[], no al system prompt
                    system_prompt = base_system_prompt

                    # 4. Prepare messages payload for engine
                    engine_messages = [
                        {"role": m["role"], "content": m["content"]}
                        for m in context_messages
                    ]

                    # Injectar context als messages (no al system prompt → MLX pot cachear el prefix)
                    if document_context:
                        # Document adjuntat: va davant del missatge de l'usuari
                        doc_block = (
                            "[DOCUMENT ADJUNTAT]\n"
                            f"{document_context}\n"
                            "[FI DOCUMENT]\n\n"
                            "Respon EXCLUSIVAMENT basant-te en el document anterior. "
                            "Si la informació no hi és, indica-ho clarament.\n\n"
                            f"{message}"
                        )
                        engine_messages.append({"role": "user", "content": doc_block})
                    elif rag_context:
                        # Context RAG: va davant del missatge de l'usuari
                        rag_block = f"[CONTEXT MEMÒRIA]\n{rag_context}[FI CONTEXT]\n\n{message}"
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
                                yield f"\n[Error: {str(e)}]"

                            # Save clean response (no think tags) to session/disk
                            import re as _re
                            clean_response = _re.sub(r"<think>[\s\S]*?</think>\s*", "", full_response).strip()
                            if clean_response:
                                session.add_message("assistant", clean_response)
                                _session_manager._save_session_to_disk(session)

                                # AUTO-SAVE: guarda missatge usuari directament (sense LLM)
                                if not full_response.startswith("❌"):
                                    try:
                                        save_result = await memory_helper.auto_save(
                                            user_message=message,
                                            session_id=session.id,
                                        )
                                        if save_result.get("document_id"):
                                            yield "\x00[MEM]\x00"
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
                response_text = "❌ Error: Cap motor d'IA disponible (prova iniciar Ollama amb 'ollama serve')"
        except Exception as e:
            logger.error(f"Error calling LLM: {e}")
            response_text = f"❌ Error: {str(e)}"

    session.add_message("assistant", response_text)
    _session_manager._save_session_to_disk(session)

    # AUTO-SAVE: guarda missatge usuari directament (sense LLM)
    if response_text and not response_text.startswith("❌") and not response_text.startswith("❓"):
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


@router_public.post("/memory/save")
async def memory_save(request: Dict[str, Any], _auth=Depends(_require_ui_auth)):
    """Guardar contingut explícitament a la memòria"""
    content = request.get("content", "")
    session_id = request.get("session_id", "unknown")
    metadata = request.get("metadata", {})

    if not content:
        raise HTTPException(status_code=400, detail="Content is required")

    memory_helper = get_memory_helper()
    result = await memory_helper.save_to_memory(
        content=content,
        session_id=session_id,
        metadata=metadata
    )

    return result


@router_public.post("/memory/recall")
async def memory_recall(request: Dict[str, Any], _auth=Depends(_require_ui_auth)):
    """Cercar a la memòria"""
    query = request.get("query", "")
    limit = request.get("limit", 5)

    if not query:
        raise HTTPException(status_code=400, detail="Query is required")

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


async def _session_cleanup_loop():
    """Background loop that removes inactive sessions every hour."""
    while True:
        await asyncio.sleep(3600)  # cada hora
        try:
            removed = _session_manager.cleanup_inactive(max_age_hours=24)
            if removed:
                logger.info("Session cleanup: %d sessions removed", removed)
        except Exception as e:
            logger.warning("Session cleanup failed: %s", e)


def start_session_cleanup_task():
    """Start session cleanup background task. Call from lifespan startup."""
    asyncio.create_task(_session_cleanup_loop())


# Module instance getter
def get_module_instance():
    """Get module instance (compatibility)."""
    from .module import WebUIModule
    return WebUIModule()
