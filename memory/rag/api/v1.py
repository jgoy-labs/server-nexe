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
import logging

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/rag", tags=["rag-v1", "future"])

@router.post("/search", summary="Cerca semàntica al vector store RAG")
async def rag_search_v1():
  """
  Cerca semàntica RAG (API v1).

  STATUS: NOT IMPLEMENTED (coming soon)

  Request body:
    {
      "query": "What is the weather today?",
      "top_k": 5,
      "filters": {
        "source": "docs",
        "date_range": {"start": "2026-01-01", "end": "2026-12-31"}
      },
      "min_score": 0.7
    }

  Expected returns:
    {
      "results": [
        {
          "id": "doc-123",
          "text": "The weather today is sunny...",
          "score": 0.95,
          "metadata": {"source": "docs", "date": "2026-03-07"}
        }
      ],
      "total": 5,
      "query_time_ms": 42
    }
  """
  logger.warning("RAG search endpoint called but not implemented yet")

  raise HTTPException(
    status_code=501,
    detail={
      "error": "Not Implemented",
      "message": "RAG search API not yet available",
      "internal_status": "RAGModule operational (internal use only)",
      "expected_date": "2026-06-01",
      "workaround": "Use RAGModule directly from Python: from memory.rag.module import RAGModule"
    }
  )

@router.post("/add", summary="Afegir documents al vector store RAG")
async def rag_add_documents_v1():
  """
  Afegeix documents al vector store RAG (API v1).

  STATUS: NOT IMPLEMENTED (coming soon)

  Request body:
    {
      "documents": [
        {
          "text": "Document content here...",
          "metadata": {"source": "api", "type": "manual"}
        }
      ]
    }

  Expected returns:
    {
      "document_ids": ["doc-456", "doc-457"],
      "total_added": 2
    }
  """
  logger.warning("RAG add documents endpoint called but not implemented yet")

  raise HTTPException(
    status_code=501,
    detail={
      "error": "Not Implemented",
      "message": "RAG document addition API not yet available",
      "internal_status": "RAGModule operational (internal use only)",
      "expected_date": "2026-06-01"
    }
  )

@router.delete("/documents/{document_id}", summary="Eliminar document del vector store RAG")
async def rag_delete_document_v1(document_id: str):
  """
  Elimina un document del vector store RAG (API v1).

  STATUS: NOT IMPLEMENTED (coming soon)

  Path params:
    - document_id: ID del document a eliminar

  Expected returns:
    {
      "status": "deleted",
      "document_id": "doc-123"
    }

  Errors:
    - 404: Document not found
  """
  logger.warning("RAG delete document endpoint called for %s but not implemented yet", document_id)

  raise HTTPException(
    status_code=501,
    detail={
      "error": "Not Implemented",
      "message": "RAG document deletion API not yet available",
      "internal_status": "RAGModule operational (internal use only)",
      "expected_date": "2026-06-01"
    }
  )

__all__ = ['router']