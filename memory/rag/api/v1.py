"""
────────────────────────────────────
Server Nexe
Version: 0.8
Author: Jordi Goy 
Location: memory/rag/api/v1.py
Description: RAG API v1 - Endpoints per cerca semàntica i gestió documents RAG.

www.jgoy.net
────────────────────────────────────
"""

from fastapi import APIRouter, HTTPException
from personality.i18n.resolve import t_modular
import logging

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/rag", tags=["rag-v1", "future"])

@router.post("/search")
async def rag_search_v1():
  """
  Cerca semàntica RAG (API v1).

  STATUS: NOT IMPLEMENTED (Coming in FASE 15)

  Request body:
    {
      "query": "What is the weather today?",
      "top_k": 5,
      "filters": {
        "source": "docs",
        "date_range": {"start": "2025-01-01", "end": "2025-12-31"}
      },
      "min_score": 0.7
    }

  Expected returns (FASE 15):
    {
      "results": [
        {
          "id": "doc-123",
          "text": "The weather today is sunny...",
          "score": 0.95,
          "metadata": {"source": "docs", "date": "2025-11-20"}
        }
      ],
      "total": 5,
      "query_time_ms": 42
    }
  """
  logger.warning(t_modular(
    "rag.logs.search_not_implemented",
    "RAG search endpoint called but not implemented yet"
  ))

  raise HTTPException(
    status_code=501,
    detail={
      "error": t_modular("rag.api.not_implemented_error", "Not Implemented"),
      "message": t_modular("rag.api.search_scheduled", "RAG search API scheduled for FASE 15"),
      "internal_status": t_modular("rag.api.internal_status", "RAGModule operational (internal use only)"),
      "expected_date": "2025-12-15",
      "reason": t_modular(
        "rag.api.reason_auth",
        "Waiting for granular auth (FASE 13) before exposing RAG HTTP API"
      ),
      "workaround": t_modular(
        "rag.api.workaround_direct_module",
        "Use RAGModule directly from Python: from memory.rag.module import RAGModule"
      )
    }
  )

@router.post("/add")
async def rag_add_documents_v1():
  """
  Afegeix documents al vector store RAG (API v1).

  STATUS: NOT IMPLEMENTED (Coming in FASE 15)

  Request body:
    {
      "documents": [
        {
          "text": "Document content here...",
          "metadata": {"source": "api", "type": "manual"}
        }
      ]
    }

  Expected returns (FASE 15):
    {
      "document_ids": ["doc-456", "doc-457"],
      "total_added": 2
    }
  """
  logger.warning(t_modular(
    "rag.logs.add_not_implemented",
    "RAG add documents endpoint called but not implemented yet"
  ))

  raise HTTPException(
    status_code=501,
    detail={
      "error": t_modular("rag.api.not_implemented_error", "Not Implemented"),
      "message": t_modular("rag.api.add_scheduled", "RAG document addition API scheduled for FASE 15"),
      "internal_status": t_modular("rag.api.internal_status", "RAGModule operational (internal use only)"),
      "expected_date": "2025-12-15"
    }
  )

@router.delete("/documents/{document_id}")
async def rag_delete_document_v1(document_id: str):
  """
  Elimina un document del vector store RAG (API v1).

  STATUS: NOT IMPLEMENTED (Coming in FASE 15)

  Path params:
    - document_id: ID del document a eliminar

  Expected returns (FASE 15):
    {
      "status": "deleted",
      "document_id": "doc-123"
    }

  Errors:
    - 404: Document not found
  """
  logger.warning(t_modular(
    "rag.logs.delete_not_implemented",
    "RAG delete document endpoint called for {document_id} but not implemented yet",
    document_id=document_id
  ))

  raise HTTPException(
    status_code=501,
    detail={
      "error": t_modular("rag.api.not_implemented_error", "Not Implemented"),
      "message": t_modular("rag.api.delete_scheduled", "RAG document deletion API scheduled for FASE 15"),
      "internal_status": t_modular("rag.api.internal_status", "RAGModule operational (internal use only)"),
      "expected_date": "2025-12-15"
    }
  )

__all__ = ['router']
