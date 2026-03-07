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

@router.post("/encode", summary="Generar embeddings vectorials per textos")
async def encode_embeddings_v1():
  """
  Genera embeddings per textos (API v1).

  STATUS: NOT IMPLEMENTED (coming soon)
  """
  raise HTTPException(
    status_code=501,
    detail={
      "error": "Not Implemented",
      "message": "Embeddings API not yet available",
      "expected_date": "2026-06-01"
    }
  )

@router.get("/models", summary="Llistar models d'embeddings disponibles")
async def list_embedding_models_v1():
  """
  Llista models d'embeddings disponibles (API v1).

  STATUS: NOT IMPLEMENTED (coming soon)
  """
  raise HTTPException(
    status_code=501,
    detail={
      "error": "Not Implemented",
      "message": "Embeddings models API not yet available",
      "expected_date": "2026-06-01"
    }
  )

__all__ = ['router']