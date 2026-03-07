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

@router_v1.get("", include_in_schema=True, summary="Arrel API v1 — endpoints disponibles i estat")
async def v1_root(request: Request):
  """
  API v1 root endpoint - Informació general API versionada.

  Returns:
    JSONResponse: Metadata API v1
  """
  return JSONResponse({
    "api_version": "v1",
    "status": "operational",
    "description": "Nexe 0.8 Versioned API",
    "endpoints": {
      "workflows": {
        "base": "/v1/workflows",
        "status": "implemented",
        "description": "Workflow management endpoints"
      },
      "chat": {
        "base": "/v1/chat",
        "status": "implemented",
        "description": "Chat completion endpoints"
      },
      "rag": {
        "base": "/v1/rag",
        "status": "future",
        "description": "RAG search endpoints (coming in FASE 15)",
        "expected_date": "2026-06-01"
      },
      "embeddings": {
        "base": "/v1/embeddings",
        "status": "future",
        "description": "Text embeddings endpoints (coming in FASE 15)",
        "expected_date": "2026-06-01"
      },
      "documents": {
        "base": "/v1/documents",
        "status": "future",
        "description": "Document processing endpoints (coming in FASE 15)",
        "expected_date": "2026-06-01"
      },
      "memory": {
        "base": "/v1/memory",
        "status": "implemented",
        "description": "Semantic memory store/search for chat"
      }
    },
    "documentation": {
      "openapi": "/docs",
      "redoc": "/redoc"
    },
    "support": {
      "issues": "https://github.com/jgoy-labs/server-nexe/issues",
      "docs": "https://github.com/jgoy-labs/server-nexe#readme"
    }
  })

@router_v1.get("/health", include_in_schema=True, summary="Health check específic de l'API v1")
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