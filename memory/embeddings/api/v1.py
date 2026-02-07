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
from personality.i18n.resolve import t_modular

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
      "error": t_modular("embeddings.api.not_implemented_error", "Not Implemented"),
      "message": t_modular("embeddings.api.scheduled", "Embeddings API scheduled for FASE 15"),
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
      "error": t_modular("embeddings.api.not_implemented_error", "Not Implemented"),
      "message": t_modular("embeddings.api.models_scheduled", "Embeddings models API scheduled for FASE 15"),
      "expected_date": "2025-12-15"
    }
  )

__all__ = ['router']
