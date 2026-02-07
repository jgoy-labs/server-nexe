"""
────────────────────────────────────
Server Nexe
Version: 0.8
Author: Jordi Goy
Location: plugins/ollama_module/manifest.py
Description: Router FastAPI per mòdul Ollama. Exposa endpoints REST per gestió.
             Lazy initialization to avoid side effects at import.

www.jgoy.net
────────────────────────────────────
"""

import logging
from pathlib import Path
from typing import List, Optional

from fastapi import APIRouter, HTTPException, Depends
from fastapi.responses import HTMLResponse, FileResponse, StreamingResponse
from pydantic import BaseModel

from plugins.security.core.validators import validate_safe_path
from plugins.security.core.auth import require_api_key
from personality.i18n.resolve import t_modular

logger = logging.getLogger(__name__)

def _t_log(key: str, fallback: str, **kwargs) -> str:
    return t_modular(f"ollama_module.logs.{key}", fallback, **kwargs)

router_public = APIRouter(prefix="/ollama", tags=["ollama"])

MODULE_PATH = Path(__file__).parent
UI_PATH = MODULE_PATH / "ui"

# Lazy singleton - no side effects at import
_ollama_module: Optional["OllamaModule"] = None


def _get_module():
    """Lazy initialization of OllamaModule."""
    global _ollama_module
    if _ollama_module is None:
        from .module import OllamaModule
        _ollama_module = OllamaModule()
        logger.info(_t_log("lazy_initialized", "OllamaModule lazy-initialized"))
    return _ollama_module


def get_ollama_module():
    """Retorna instància d'OllamaModule (dependency injection)"""
    module = _get_module()
    if module is None:
        raise HTTPException(
            status_code=503,
            detail=t_modular(
              "ollama_module.errors.not_initialized",
              "Ollama module not initialized"
            )
        )
    return module


def get_module_instance():
    """Get module instance (lazy)."""
    return _get_module()

class ChatMessage(BaseModel):
  """Model per missatge de chat"""
  role: str
  content: str

class ChatRequest(BaseModel):
  """Request per chat amb Ollama"""
  model: str
  messages: List[ChatMessage]
  stream: bool = True

class PullModelRequest(BaseModel):
  """Request per descarregar model"""
  name: str

@router_public.get("/ui", response_class=HTMLResponse)
async def serve_ui():
  """
  Serveix interfície web del chatbot Ollama.
  """
  index_path = UI_PATH / "index.html"

  if not index_path.exists():
    return HTMLResponse(
      content=f"<h1>{t_modular('ollama_module.ui.not_found', 'Ollama UI not found')}</h1>",
      status_code=404
    )

  with open(index_path, 'r', encoding='utf-8') as f:
    content = f.read()

  return HTMLResponse(content=content)

@router_public.get("/ui/assets/css/{path:path}")
async def serve_css(path: str):
  """Serveix fitxers CSS"""
  css_base = UI_PATH / "assets" / "css"
  safe_path = validate_safe_path(css_base / path, css_base)
  return FileResponse(safe_path, media_type="text/css")

@router_public.get("/ui/js/{path:path}")
async def serve_js(path: str):
  """Serveix fitxers JavaScript"""
  js_base = UI_PATH / "js"
  safe_path = validate_safe_path(js_base / path, js_base)
  return FileResponse(safe_path, media_type="application/javascript")

@router_public.get("/api/models")
async def list_models(
  module = Depends(get_ollama_module)
):
  """
  Llista models locals d'Ollama.

  Returns:
    {"status": "ok", "models": [...]}
  """
  try:
    models = await module.list_models()

    return {
      "status": "ok",
      "total": len(models),
      "models": models
    }

  except Exception as e:
    logger.error(
      _t_log(
        "list_models_failed",
        "Failed to list Ollama models: {error}",
        error=str(e),
      )
    )
    raise HTTPException(
      status_code=503,
      detail=t_modular(
        "ollama_module.errors.connection_failed",
        "Ollama connection failed: {error}",
        error=str(e)
      )
    )

@router_public.post("/api/pull")
async def pull_model(
  request: PullModelRequest,
  module = Depends(get_ollama_module),
  _: str = Depends(require_api_key)
):
  """
  Descarrega model d'Ollama amb streaming de progrés.

  Security: Requires API key (download costs bandwidth)

  Args:
    request: Nom del model a descarregar

  Returns:
    StreamingResponse amb events de progrés
  """
  async def progress_stream():
    """Generator per streaming de progrés"""
    try:
      async for progress in module.pull_model(request.name):
        import json
        data = json.dumps(progress)
        yield f"data: {data}\n\n"

    except Exception as e:
      logger.error(
        _t_log(
          "pull_model_failed",
          "Pull model failed: {error}",
          error=str(e),
        )
      )
      error_data = {"error": str(e), "status": "error"}
      import json
      yield f"data: {json.dumps(error_data)}\n\n"

  return StreamingResponse(
    progress_stream(),
    media_type="text/event-stream",
    headers={
      "Cache-Control": "no-cache",
      "Connection": "keep-alive",
    }
  )

@router_public.post("/api/chat")
async def chat(
  request: ChatRequest,
  module = Depends(get_ollama_module),
  _: str = Depends(require_api_key)
):
  """
  Chat amb model Ollama (SEMPRE amb streaming).

  Security: Requires API key (CPU intensive operation)

  Args:
    request: Model + missatges

  Returns:
    StreamingResponse amb chunks de resposta en temps real
  """
  messages = [{"role": m.role, "content": m.content} for m in request.messages]

  async def chat_stream():
    """Generator per streaming de respostes"""
    try:
      async for chunk in module.chat(
        model=request.model,
        messages=messages,
        stream=True
      ):
        import json
        data = json.dumps(chunk)
        yield f"data: {data}\n\n"

        if chunk.get("done", False):
          break

    except Exception as e:
      logger.error(
        _t_log(
          "chat_failed",
          "Chat failed: {error}",
          error=str(e),
        )
      )
      error_data = {"error": str(e), "done": True}
      import json
      yield f"data: {json.dumps(error_data)}\n\n"

  return StreamingResponse(
    chat_stream(),
    media_type="text/event-stream",
    headers={
      "Cache-Control": "no-cache",
      "Connection": "keep-alive",
      "X-Accel-Buffering": "no",
    }
  )

@router_public.get("/api/models/{model_name}/info")
async def get_model_info(
  model_name: str,
  module = Depends(get_ollama_module)
):
  """
  Obté informació detallada d'un model.

  Args:
    model_name: Nom del model

  Returns:
    Info del model (modelfile, parameters, template)
  """
  try:
    info = await module.get_model_info(model_name)

    return {
      "status": "ok",
      "model": model_name,
      "info": info
    }

  except Exception as e:
    logger.error(
      _t_log(
        "get_info_failed",
        "Failed to get model info: {error}",
        error=str(e),
      )
    )
    raise HTTPException(
      status_code=404,
      detail=t_modular(
        "ollama_module.errors.model_not_found",
        "Model not found or error: {error}",
        error=str(e)
      )
    )

@router_public.delete("/api/models/{model_name}")
async def delete_model(
  model_name: str,
  module = Depends(get_ollama_module),
  _: str = Depends(require_api_key)
):
  """
  Elimina un model local.

  Security: Requires API key (destructive operation)

  Args:
    model_name: Nom del model a eliminar

  Returns:
    {"status": "ok", "message": "..."}
  """
  try:
    await module.delete_model(model_name)

    return {
      "status": "ok",
      "message": t_modular(
        "ollama_module.messages.model_deleted",
        "Model {model} deleted successfully",
        model=model_name
      )
    }

  except Exception as e:
    logger.error(
      _t_log(
        "delete_model_failed",
        "Failed to delete model: {error}",
        error=str(e),
      )
    )
    raise HTTPException(
      status_code=500,
      detail=t_modular(
        "ollama_module.errors.delete_failed",
        "Delete failed: {error}",
        error=str(e)
      )
    )

@router_public.get("/health")
async def health():
  """
  Health check del mòdul Ollama.

  Returns:
    {"status": "ok", "connected": bool}
  """
  try:
    from .health import get_health
    result = get_health()
    return result

  except Exception as e:
    logger.error(
      _t_log(
        "health_check_failed",
        "Health check failed: {error}",
        error=str(e),
      )
    )
    return {
      "status": "error",
      "connected": False,
      "error": str(e)
    }

@router_public.get("/info")
async def info(module = Depends(get_ollama_module)):
  """
  Informació del mòdul Ollama.

  Returns:
    Metadata del mòdul
  """
  return module.get_info()

MODULE_METADATA = {
  "name": "ollama_module",
  "version": "1.0.0",
  "description": t_modular(
    "ollama_module.metadata.description",
    "Ollama integration (local LLM option)"
  ),
  "router": router_public,
  "prefix": "/ollama",
  "tags": ["ollama", "llm", "chat", "local"],
  "ui_available": True,
  "ui_path": "/ui-control/ollama/",
  "type": "local_llm_option",
  "location": "core/tools/",
}

def get_router():
  """Retorna router públic del mòdul"""
  return router_public

def get_metadata():
  """Retorna metadata del mòdul"""
  return MODULE_METADATA
