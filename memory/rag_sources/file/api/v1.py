"""
────────────────────────────────────
Server Nexe
Version: 0.8
Author: Jordi Goy 
Location: memory/rag_sources/file/api/v1.py
Description: API v1 per gestió de fitxers documentals (placeholder FASE 15).

www.jgoy.net
────────────────────────────────────
"""

from fastapi import APIRouter, HTTPException

router = APIRouter(prefix="/documents", tags=["documents-v1", "future"])

@router.get("/", summary="[FASE 15] Llistar documents disponibles al sistema de fitxers")
async def list_documents_v1():
    """
    Llista documents disponibles (API v1).
    STATUS: NOT IMPLEMENTED (Coming in FASE 15)
    """
    raise HTTPException(
        status_code=501,
        detail={
            "error": "Not Implemented",
            "message": "Documents API scheduled for FASE 15",
            "expected_date": "2025-12-15"
        }
    )

__all__ = ['router']
