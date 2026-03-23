"""
────────────────────────────────────
Server Nexe
Version: 0.8
Author: Jordi Goy
Location: plugins/web_ui_module/manifest.py
Description: Router FastAPI per mòdul Web UI.

www.jgoy.net · https://server-nexe.org
────────────────────────────────────
"""

from pathlib import Path
from typing import Dict, Any, Optional
import asyncio
import logging
import os as _os
import re as _re
import secrets
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


async def _generate_rag_metadata(body_content: str, filename: str) -> dict:
    """
    Usa el LLM per generar abstract i tags consistents amb el contingut real del document.
    Fa servir els primers 3000 chars com a mostra. Fallback a extracció simple si falla.
    """
    import os as _os
    import inspect

    stem = Path(filename).stem.replace("_", " ").replace("-", " ")
    _lang = _os.getenv("NEXE_LANG", "ca").split("-")[0].lower()

    def _fallback():
        return {
            "abstract": " ".join(body_content.split())[:300],
            "tags": [stem],
            "priority": "P2",
            "type": "docs",
            "lang": _lang,
        }

    try:
        from core.lifespan import get_server_state
        module_manager = get_server_state().module_manager
        model_name = _os.getenv("NEXE_DEFAULT_MODEL", "llama3.2:3b")

        sample = body_content[:3000].strip()
        system_prompt = "Ets un sistema d'indexació de documents. Respon NOMÉS en el format demanat, sense explicacions."
        user_prompt = (
            f'Analitza aquest fragment del document "{filename}" i genera:\n'
            f'1. Un abstract de 1-2 frases (màx 300 caràcters) que descrigui el contingut real\n'
            f'2. Entre 3 i 6 tags rellevants en minúscules\n\n'
            f'Fragment:\n---\n{sample}\n---\n\n'
            f'Respon EXACTAMENT en aquest format:\n'
            f'abstract: [descripció]\n'
            f'tags: [tag1, tag2, tag3]'
        )

        for engine_name in ["mlx_module", "ollama_module", "llama_cpp_module"]:
            reg = module_manager.registry.get_module(engine_name)
            if not reg or not reg.instance:
                continue
            engine = reg.instance.get_module_instance() if hasattr(reg.instance, 'get_module_instance') else None
            if not engine or not hasattr(engine, 'chat'):
                continue

            try:
                sig = inspect.signature(engine.chat)
                if 'model' in sig.parameters:
                    full_msgs = [{"role": "system", "content": system_prompt},
                                 {"role": "user", "content": user_prompt}]
                    chat_result = engine.chat(model=model_name, messages=full_msgs, stream=False)
                else:
                    chat_result = engine.chat(messages=[{"role": "user", "content": user_prompt}],
                                              system=system_prompt, stream=False)

                # Recollir resposta (streaming o no)
                response_text = ""
                if inspect.isasyncgen(chat_result) or hasattr(chat_result, '__aiter__'):
                    async for chunk in chat_result:
                        if isinstance(chunk, dict):
                            response_text += (chunk.get("message", {}).get("content", "")
                                              or chunk.get("content", ""))
                        elif isinstance(chunk, str):
                            response_text += chunk
                elif inspect.iscoroutine(chat_result):
                    result = await chat_result
                    if isinstance(result, dict):
                        response_text = (result.get("message", {}).get("content", "")
                                         or result.get("content", "")
                                         or result.get("response", ""))
                    else:
                        response_text = str(result)
                else:
                    response_text = str(chat_result)

                # Filtrar tags <think>...</think> si el model en genera
                response_text = _re.sub(r"<think>[\s\S]*?</think>\s*", "", response_text).strip()

                # Parsejar abstract i tags
                abstract = ""
                tags = [stem]
                for line in response_text.split('\n'):
                    line = line.strip()
                    if line.lower().startswith('abstract:'):
                        abstract = line[9:].strip().strip('"\'')[:400]
                    elif line.lower().startswith('tags:'):
                        tags_str = line[5:].strip().strip('[]')
                        tags = [t.strip().strip('"\'') for t in tags_str.split(',') if t.strip()][:6]

                if abstract:
                    logger.info(f"LLM metadata per '{filename}': abstract={abstract[:60]}… tags={tags}")
                    return {
                        "abstract": abstract,
                        "tags": tags or [stem],
                        "priority": "P2",
                        "type": "docs",
                        "lang": _lang,
                    }
            except Exception as e:
                logger.warning(f"LLM metadata ({engine_name}) fallida: {e}")
                continue

    except Exception as e:
        logger.warning(f"_generate_rag_metadata fallida: {e}")

    return _fallback()

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
    if expected and not secrets.compare_digest(x_api_key or "", expected):
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
    try:
        lang = get_server_state().config.get('personality', {}).get('i18n', {}).get('default_language', 'en-US')
    except Exception:
        lang = "en-US"
    return {
        "model": model_name,
        "backend": backend,
        "version": version,
        "lang": lang.split('-')[0]
    }


@router_public.get("/backends")
async def list_backends(_auth=Depends(_require_ui_auth)):
    """Llista backends disponibles amb els seus models"""
    import os
    from core.lifespan import get_server_state

    module_manager = get_server_state().module_manager
    backends = []

    # Directori de models local
    models_dir = Path(os.getenv("NEXE_STORAGE_PATH", "storage")) / "models"
    if not models_dir.is_absolute():
        from core.lifespan import get_server_state
        root = Path(get_server_state().project_root)
        models_dir = root / models_dir

    # Ollama
    try:
        reg = module_manager.registry.get_module("ollama_module")
        if reg and reg.instance:
            engine = reg.instance
            if hasattr(engine, "get_module_instance"):
                engine = engine.get_module_instance()
            if hasattr(engine, "list_models"):
                models = await engine.list_models()
                model_names = [m.get("name", m.get("model", "?")) for m in models]
                backends.append({"id": "ollama", "name": "Ollama", "models": model_names, "active": False})
    except Exception as e:
        logger.debug(f"Ollama backend scan failed: {e}")

    # MLX
    try:
        if models_dir.exists():
            mlx_models = [d.name for d in models_dir.iterdir() if d.is_dir()]
            if mlx_models:
                backends.append({"id": "mlx", "name": "MLX", "models": mlx_models, "active": False})
    except Exception as e:
        logger.debug(f"MLX backend scan failed: {e}")

    # Llama.cpp - només mostrar si hi ha fitxers .gguf disponibles
    try:
        reg = module_manager.registry.get_module("llama_cpp_module")
        if reg and reg.instance:
            gguf_models = []
            if models_dir.exists():
                gguf_models = [f.name for f in models_dir.iterdir() if f.suffix == ".gguf"]
            if gguf_models:
                backends.append({"id": "llamacpp", "name": "Llama.cpp", "models": gguf_models, "active": False})
    except Exception as e:
        logger.debug(f"Llama.cpp backend scan failed: {e}")

    # Marcar actiu
    current_backend = os.getenv("NEXE_MODEL_ENGINE", "auto").lower()
    current_model = os.getenv("NEXE_DEFAULT_MODEL", "")
    for b in backends:
        if current_backend == b["id"] or (current_backend == "auto" and b == backends[0]):
            b["active"] = True
            break

    return {"backends": backends, "current_backend": current_backend, "current_model": current_model}


@router_public.post("/backend")
async def set_backend(request: Dict[str, Any], _auth=Depends(_require_ui_auth)):
    """Canvia el backend i/o model actiu en runtime"""
    import os
    backend = request.get("backend", "").lower()
    model = request.get("model", "")

    if backend:
        os.environ["NEXE_MODEL_ENGINE"] = backend
        logger.info(f"Backend canviat a: {backend}")
    if model:
        os.environ["NEXE_DEFAULT_MODEL"] = model
        logger.info(f"Model canviat a: {model}")

    return {"status": "ok", "backend": os.getenv("NEXE_MODEL_ENGINE", "auto"), "model": os.getenv("NEXE_DEFAULT_MODEL", "")}


@router_public.get("/", response_class=HTMLResponse)
async def serve_ui():
    """Servir la pàgina principal amb l'idioma del servidor injectat"""
    html_path = _static_dir / "index.html"
    if not html_path.exists():
        raise HTTPException(status_code=404, detail="UI not found")
    html = html_path.read_text(encoding="utf-8")
    lang = _os.getenv("NEXE_LANG", "ca").split("-")[0].lower()
    html = html.replace('lang="ca"', f'lang="{lang}"')
    html = html.replace("</head>", f'<script>window.NEXE_LANG="{lang}";</script>\n</head>')
    return HTMLResponse(content=html)


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
    _mime = {
        ".css":   "text/css; charset=utf-8",
        ".js":    "application/javascript; charset=utf-8",
        ".svg":   "image/svg+xml",
        ".png":   "image/png",
        ".jpg":   "image/jpeg",
        ".jpeg":  "image/jpeg",
        ".ico":   "image/x-icon",
        ".woff2": "font/woff2",
        ".woff":  "font/woff",
        ".html":  "text/html; charset=utf-8",
        ".map":   "application/json",
    }
    media_type = _mime.get(file_path.suffix, "application/octet-stream")

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
    text = await _file_handler.extract_text_async(file_path)
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
            # Generar metadades via LLM per màxima consistència amb el contingut
            auto_meta = await _generate_rag_metadata(body_content, file.filename)
            doc_metadata.update(auto_meta)
            logger.info(f"No RAG header — metadades LLM per '{file.filename}'")

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
async def list_uploaded_files(_auth=Depends(_require_ui_auth)):
    """Llistar tots els fitxers pujats"""
    files = _file_handler.get_uploaded_files()
    return {"files": files, "total": len(files)}


@router_public.post("/files/cleanup")
async def cleanup_files(max_age_hours: int = 24, _auth=Depends(_require_ui_auth)):
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
                _safe_content = str(content_to_save).replace("\x00", "").replace("]", "")[:200]
                response_text = f"✅ Guardat a la memòria: \"{_safe_content}\"\n\nHo recordaré per a futures converses.\x00[MEM]\x00"
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
            # Prioritzar model/backend del request (selector UI) sobre env vars
            model_name = request.get("model") or os.getenv("NEXE_DEFAULT_MODEL", "llama3.2:3b")
            preferred_engine = (request.get("backend") or os.getenv("NEXE_MODEL_ENGINE", "auto")).lower()

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
                    if request.get("model"):
                        from core.lifespan import get_server_state as _gss
                        models_dir = Path(os.getenv("NEXE_STORAGE_PATH", "storage")) / "models"
                        if not models_dir.is_absolute():
                            models_dir = Path(_gss().project_root) / models_dir
                        local_path = models_dir / model_name

                        if engine_name == "mlx_module" and local_path.exists():
                            os.environ["NEXE_MLX_MODEL"] = str(local_path)
                            from plugins.mlx_module.config import MLXConfig
                            new_config = MLXConfig.from_env()
                            if hasattr(engine, '_node') and engine._node:
                                if engine._node.config.model_path != new_config.model_path:
                                    engine._node.config = new_config
                                    engine._node.__class__._config = new_config
                                    engine._node.__class__._model = None
                                    logger.info(f"MLX model switched to: {local_path}")

                        elif engine_name == "llama_cpp_module" and local_path.exists():
                            os.environ["NEXE_LLAMA_CPP_MODEL"] = str(local_path)
                            from plugins.llama_cpp_module.config import LlamaCppConfig
                            from plugins.llama_cpp_module.chat import LlamaCppChatNode
                            from plugins.llama_cpp_module.model_pool import ModelPool
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
                    # Si la sessió té massa missatges, compactar amb resum LLM
                    if session.needs_compaction():
                        to_compact = session.get_messages_to_compact()
                        if to_compact:
                            try:
                                import re as _re_compact
                                def _clean_for_compact(txt):
                                    txt = _re_compact.sub(r'<think>.*?</think>', '', txt, flags=_re_compact.DOTALL)
                                    txt = _re_compact.sub(r'<\|thinking\|>.*?<\|/thinking\|>', '', txt, flags=_re_compact.DOTALL)
                                    return txt.strip()
                                compact_text = "\n".join(
                                    f"{m['role']}: {_clean_for_compact(m['content'][:1500])}"
                                    for m in to_compact
                                )
                                prev_summary = f"Resum anterior: {session.context_summary}\n\n" if session.context_summary else ""
                                compact_prompt = (
                                    f"{prev_summary}"
                                    f"Resumeix aquesta conversa en 2-3 frases curtes. "
                                    f"Inclou: tema principal, decisions preses, i informació clau. "
                                    f"Respon NOMÉS amb el resum, res més.\n\n{compact_text}"
                                )
                                # Usar el mateix engine per resumir
                                summary_result = await engine.chat(
                                    messages=[{"role": "user", "content": compact_prompt}],
                                    system="Ets un assistent que fa resums breus i precisos de converses."
                                )
                                summary = ""
                                if isinstance(summary_result, dict):
                                    if "message" in summary_result and isinstance(summary_result["message"], dict):
                                        summary = summary_result["message"].get("content", "")
                                    elif "response" in summary_result:
                                        summary = summary_result["response"]
                                    elif "content" in summary_result:
                                        summary = summary_result["content"]
                                    elif "choices" in summary_result:
                                        choices = summary_result["choices"]
                                        if choices:
                                            summary = choices[0].get("message", {}).get("content", "")
                                elif isinstance(summary_result, str):
                                    summary = summary_result
                                if summary:
                                    session.apply_compaction(summary)
                                    _session_manager._save_session_to_disk(session)
                                    logger.info("Session %s: compaction done (%d chars summary)", session.id[:8], len(summary))
                                else:
                                    logger.warning("Session %s: compaction returned empty summary", session.id[:8])
                            except Exception as e:
                                logger.warning("Compaction failed: %s", e)

                    # --- Build Context ---
                    # 1. Get recent conversation history with summary context
                    context_messages_full = session.get_context_messages()
                    # Exclude the very last message (just added) to avoid duplication
                    context_messages = context_messages_full[:-1] if context_messages_full else []

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

                        # Sanitize document context (same as RAG context)
                        document_context = _re.sub(r'[\x00-\x08\x0b\x0c\x0e-\x1f]', '', document_context)
                        logger.info(f"Using attached document: {attached_doc['filename']} (parts {shown}/{total_chunks}, {len(doc_content)} chars)")

                    # 3. Get Memory Context (RAG) - SEMPRE buscar, no només amb patterns
                    rag_context = ""
                    rag_count = 0
                    if not attached_doc:
                        try:
                            recall_result = await memory_helper.recall_from_memory(message, limit=5)
                            if recall_result["success"] and recall_result["results"]:
                                # Filtrar per score mínim (configurable, default 0.6)
                                rag_threshold = float(request.get("rag_threshold", 0.6))
                                relevant = [r for r in recall_result["results"] if r.get("score", 0) >= rag_threshold]
                                if relevant:
                                    rag_count = len(relevant)
                                    # Separar knowledge (docs) de memòria (converses)
                                    knowledge_items = [r for r in relevant if r.get('metadata', {}).get('source_collection') == 'user_knowledge']
                                    memory_items = [r for r in relevant if r.get('metadata', {}).get('source_collection') != 'user_knowledge']
                                    rag_context = ""
                                    if knowledge_items:
                                        rag_context += "\n\n[DOCUMENTACIÓ TÈCNICA]\n"
                                        for item in knowledge_items:
                                            rag_context += f"- {item['content']}\n"
                                    if memory_items:
                                        rag_context += "\n\n[MEMÒRIA DE L'USUARI]\n"
                                        for item in memory_items:
                                            rag_context += f"- {item['content']}\n"
                                    # Sanitize RAG context: remove control chars and truncate
                                    rag_context = _re.sub(r'[\x00-\x08\x0b\x0c\x0e-\x1f]', '', rag_context)
                                    if len(rag_context) > 8000:
                                        rag_context = rag_context[:8000]
                                    logger.info(f"RAG: {len(relevant)} memories relevants (score >= {rag_threshold})")
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

                    # Token budget: estimate total context and truncate if needed
                    MAX_CONTEXT_CHARS = int(_os.environ.get("NEXE_MAX_CONTEXT_CHARS", "24000"))
                    system_chars = len(system_prompt)
                    history_chars = sum(len(m.get("content", "")) for m in context_messages)
                    message_chars = len(message)
                    available_chars = MAX_CONTEXT_CHARS - system_chars - history_chars - message_chars - 500

                    # Injectar context als messages (no al system prompt → MLX pot cachear el prefix)
                    if document_context and available_chars > 0:
                        document_context = document_context[:available_chars]
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
                    elif rag_context and available_chars > 0:
                        rag_context = rag_context[:available_chars]
                        # Context RAG: separat en documentació i memòria
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
                        # Check if it supports system prompt in messages or as separate arg (Ollama supports 'system' in messages)
                        # We inject system prompt as first message for Ollama
                        full_messages = [{"role": "system", "content": system_prompt}] + messages
                        chat_result = engine.chat(model=model_name, messages=full_messages, stream=stream)
                    else:
                        # MLX/LlamaCpp-style: chat(messages, system=...)
                        if engine_name in ("mlx_module", "llama_cpp_module") and stream:
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
                            if _compacted:
                                yield f"\x00[COMPACT:{int(session.compaction_count)}]\x00"

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
                                            # GPT-OSS: NO netejar tags server-side
                                            # El client (_parseThinkingChannels) necessita
                                            # l'estructura analysis/assistant/final intacta
                                            _is_gpt_oss = "gpt-oss" in model_name.lower()
                                            if not _is_gpt_oss:
                                                # Models normals: normalitzar thinking tags
                                                content = content.replace('<|thinking|>', '<think>')
                                                content = content.replace('<|/thinking|>', '</think>')
                                                # Netejar tags (<|channel|>, ◁...▷) server-side
                                                content = _re.sub(r'<\|[^|]+\|>', '', content)
                                                content = _re.sub(r'[◁◀][^▷▶]*[▷▶]', '', content)
                                            full_response += content
                                            if content:
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

                            # Save clean response (no think/GPT-OSS tags) to session/disk
                            clean_response = full_response
                            clean_response = _re.sub(r"<think>[\s\S]*?</think>\s*", "", clean_response)
                            clean_response = _re.sub(r'<\|[^|]+\|>', '', clean_response)
                            clean_response = _re.sub(r'[◁◀][^▷▶]*[▷▶]', '', clean_response)
                            # GPT-OSS: extreure només la part "final" (resposta real)
                            _m = _re.search(r'(?:assistant\s*)?final\s*([\s\S]+)$', clean_response, _re.IGNORECASE)
                            if _m:
                                clean_response = _m.group(1).strip()
                            else:
                                # Fallback: treure prefix "analysis..." si hi és
                                clean_response = _re.sub(r'^analysis\s*', '', clean_response, flags=_re.IGNORECASE).strip()
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
