"""
────────────────────────────────────
Server Nexe
Author: Jordi Goy 
Location: memory/embeddings/api/v1.py
Description: No description available.

www.jgoy.net · https://server-nexe.org
────────────────────────────────────
"""

from fastapi import APIRouter, Depends, HTTPException
from plugins.security.core.auth_dependencies import require_api_key

router = APIRouter(prefix="/embeddings", tags=["embeddings-v1", "future"], dependencies=[Depends(require_api_key)])

@router.post("/encode", summary="Generar embeddings vectorials per textos", operation_id="embeddings_encode_v1")
async def encode_embeddings_v1():
  """
  Generates embeddings for texts (API v1).

  STATUS: NOT IMPLEMENTED (coming soon)
  """
  raise HTTPException(
    status_code=501,
    detail={
      "error": "Not Implemented",
      "message": "Embeddings API not yet available",
    }
  )

@router.get("/models", summary="Llistar models d'embeddings disponibles", operation_id="embeddings_models_v1")
async def list_embedding_models_v1():
  """
  Lists available embeddings models (API v1).

  STATUS: NOT IMPLEMENTED (coming soon)
  """
  raise HTTPException(
    status_code=501,
    detail={
      "error": "Not Implemented",
      "message": "Embeddings models API not yet available",
    }
  )

__all__ = ['router']