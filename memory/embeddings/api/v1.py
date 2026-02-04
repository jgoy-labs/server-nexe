"""
────────────────────────────────────
Server Nexe
Version: 0.8
Author: Jordi Goy 
Location: memory/embeddings/api/v1.py
Description: No description available.

www.jgoy.net
────────────────────────────────────
"""

from fastapi import APIRouter, HTTPException

router = APIRouter(prefix="/embeddings", tags=["embeddings-v1", "future"])

@router.post("/encode")
async def encode_embeddings_v1():
  """
  Genera embeddings per textos (API v1).

  STATUS: NOT IMPLEMENTED (Coming in FASE 15)
  """
  raise HTTPException(
    status_code=501,
    detail={
      "error": "Not Implemented",
      "message": "Embeddings API scheduled for FASE 15",
      "expected_date": "2025-12-15"
    }
  )

@router.get("/models")
async def list_embedding_models_v1():
  """
  Llista models d'embeddings disponibles (API v1).

  STATUS: NOT IMPLEMENTED (Coming in FASE 15)
  """
  raise HTTPException(
    status_code=501,
    detail={
      "error": "Not Implemented",
      "message": "Embeddings models API scheduled for FASE 15",
      "expected_date": "2025-12-15"
    }
  )

__all__ = ['router']