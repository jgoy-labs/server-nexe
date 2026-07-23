"""
────────────────────────────────────
Server Nexe
Author: Jordi Goy
Location: memory/rag/routers/endpoints.py
Description: API endpoints for the RAG module (health/info introspection).

WS6-01/WS6-02: the standalone /rag/{document,search,upload,files/stats}
surface was retired — it was an ephemeral in-memory substring matcher plus
a file-upload path whose FileRAGSource never existed (permanent 501). The
real RAG lives in the chat pipeline (MemoryAPI/Qdrant); the public
contract keeps only the /v1/rag/* 501 stubs documented in API.md.

www.jgoy.net · https://server-nexe.org
────────────────────────────────────
"""

import structlog
from fastapi import HTTPException
from fastapi.responses import JSONResponse


logger = structlog.get_logger()


async def health_endpoint():
  """Health check for the RAG module."""
  from ..module import RAGModule

  try:
    module = RAGModule.get_instance()
    health = module.get_health()
    status_code = 200 if health["status"] == "healthy" else 503
    return JSONResponse(content=health, status_code=status_code)

  except Exception as e:
    logger.error("Error checking health via API: %s", e, exc_info=True)
    return JSONResponse(content={"status": "error", "error": str(e)}, status_code=500)

async def info_endpoint():
  """Information about the RAG module."""
  from ..module import RAGModule

  try:
    module = RAGModule.get_instance()
    return JSONResponse(content=module.get_info())

  except Exception as e:
    logger.error("Error getting info via API: %s", e, exc_info=True)
    raise HTTPException(status_code=500, detail="Internal server error.")

__all__ = [
  "health_endpoint",
  "info_endpoint",
]
