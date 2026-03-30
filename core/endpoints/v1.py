"""
────────────────────────────────────
Server Nexe
Author: Jordi Goy 
Location: core/endpoints/v1.py
Description: API v1 Router - Base router for versioned API endpoints.

www.jgoy.net · https://server-nexe.org
────────────────────────────────────
"""

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse
import logging
from .chat import router as chat_router

logger = logging.getLogger(__name__)

router_v1 = APIRouter(prefix="/v1", tags=["v1"])
router_v1.include_router(chat_router)

@router_v1.get("", include_in_schema=True, summary="API v1 root — available endpoints and status")
@router_v1.get("/", include_in_schema=False)
async def v1_root(request: Request):
  """
  API v1 root endpoint - General versioned API information.

  Returns:
    JSONResponse: API v1 metadata
  """
  return JSONResponse({
    "api_version": "v1",
    "status": "operational",
    "description": "Nexe 0.9.0 Versioned API",
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
        "status": "implemented",
        "description": "RAG search endpoints",
      },
      "embeddings": {
        "base": "/v1/embeddings",
        "status": "implemented",
        "description": "Text embeddings endpoints",
      },
      "documents": {
        "base": "/v1/documents",
        "status": "implemented",
        "description": "Document processing endpoints",
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

@router_v1.get("/health", include_in_schema=True, summary="API v1 specific health check")
async def v1_health(request: Request):
  """
  Health check specific to API v1.

  Returns:
    JSONResponse: API v1 health status
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
  logger.warning("Could not import RAG API v1: %s", e)

try:
  from memory.embeddings.api.v1 import router as embeddings_v1_router
  router_v1.include_router(embeddings_v1_router)
except ImportError as e:
  logger.warning("Could not import Embeddings API v1: %s", e)

try:
  from memory.rag_sources.file.api.v1 import router as documents_v1_router
  router_v1.include_router(documents_v1_router)
except ImportError as e:
  logger.warning("Could not import Documents API v1: %s", e)

try:
  from memory.memory.api.v1 import router as memory_v1_router
  router_v1.include_router(memory_v1_router)
except ImportError as e:
  logger.warning("Could not import Memory API v1: %s", e)

__all__ = ['router_v1']