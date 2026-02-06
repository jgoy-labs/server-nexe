"""
────────────────────────────────────
Server Nexe
Version: 0.8
Author: Jordi Goy 
Location: core/endpoints/v1.py
Description: API v1 Router - Base router for versioned API endpoints.

www.jgoy.net
────────────────────────────────────
"""

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse
import logging
from .chat import router as chat_router

logger = logging.getLogger(__name__)

router_v1 = APIRouter(prefix="/v1", tags=["v1"])
router_v1.include_router(chat_router)

def _t(request: Request, key: str, fallback: str, **kwargs) -> str:
  """Translate with fallback using app.state.i18n."""
  try:
    i18n = getattr(request.app.state, "i18n", None)
    if not i18n:
      return fallback.format(**kwargs) if kwargs else fallback
    value = i18n.t(key, **kwargs)
    if value == key:
      return fallback.format(**kwargs) if kwargs else fallback
    return value
  except Exception:
    return fallback.format(**kwargs) if kwargs else fallback

@router_v1.get("", include_in_schema=True)
async def v1_root(request: Request):
  """
  API v1 root endpoint - Informació general API versionada.

  Returns:
    JSONResponse: Metadata API v1
  """
  return JSONResponse({
    "api_version": "v1",
    "status": _t(request, "server_core.api.v1.status_operational", "operational"),
    "description": _t(request, "server_core.api.v1.description", "Nexe 0.8 Versioned API"),
    "endpoints": {
      "workflows": {
        "base": "/v1/workflows",
        "status": _t(request, "server_core.api.v1.status_implemented", "implemented"),
        "description": _t(request, "server_core.api.v1.endpoints.workflows.description", "Workflow management endpoints")
      },
      "chat": {
        "base": "/v1/chat",
        "status": _t(request, "server_core.api.v1.status_implemented", "implemented"),
        "description": _t(request, "server_core.api.v1.endpoints.chat.description", "Chat completion endpoints")
      },
      "rag": {
        "base": "/v1/rag",
        "status": _t(request, "server_core.api.v1.status_future", "future"),
        "description": _t(request, "server_core.api.v1.endpoints.rag.description", "RAG search endpoints (coming in FASE 15)"),
        "expected_date": "2025-12-15"
      },
      "embeddings": {
        "base": "/v1/embeddings",
        "status": _t(request, "server_core.api.v1.status_future", "future"),
        "description": _t(request, "server_core.api.v1.endpoints.embeddings.description", "Text embeddings endpoints (coming in FASE 15)"),
        "expected_date": "2025-12-15"
      },
      "documents": {
        "base": "/v1/documents",
        "status": _t(request, "server_core.api.v1.status_future", "future"),
        "description": _t(request, "server_core.api.v1.endpoints.documents.description", "Document processing endpoints (coming in FASE 15)"),
        "expected_date": "2025-12-15"
      },
      "memory": {
        "base": "/v1/memory",
        "status": _t(request, "server_core.api.v1.status_implemented", "implemented"),
        "description": _t(request, "server_core.api.v1.endpoints.memory.description", "Semantic memory store/search for chat")
      }
    },
    "documentation": {
      "openapi": "/docs",
      "redoc": "/redoc"
    },
    "support": {
      "issues": "https://github.com/jgoy/nexe/issues",
      "docs": "https://jgoy.net/docs"
    }
  })

@router_v1.get("/health", include_in_schema=True)
async def v1_health(request: Request):
  """
  Health check específic per API v1.

  Returns:
    JSONResponse: Status health API v1
  """
  return JSONResponse({
    "status": "healthy",
    "api_version": "v1",
    "timestamp": request.state.i18n.get_current_time() if hasattr(request.state, 'i18n') else None
  })

try:
  from memory.rag.api.v1 import router as rag_v1_router
  router_v1.include_router(rag_v1_router)
except ImportError as e:
  logger.warning(f"Could not import RAG API v1: {e}")

try:
  from memory.embeddings.api.v1 import router as embeddings_v1_router
  router_v1.include_router(embeddings_v1_router)
except ImportError as e:
  logger.warning(f"Could not import Embeddings API v1: {e}")

try:
  from memory.rag_sources.file.api.v1 import router as documents_v1_router
  router_v1.include_router(documents_v1_router)
except ImportError as e:
  logger.warning(f"Could not import Documents API v1: {e}")

try:
  from memory.memory.api.v1 import router as memory_v1_router
  router_v1.include_router(memory_v1_router)
except ImportError as e:
  logger.warning(f"Could not import Memory API v1: {e}")

__all__ = ['router_v1']
