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
from personality.i18n.resolve import t_modular

router = APIRouter(prefix="/documents", tags=["documents-v1", "future"])

@router.get("/")
async def list_documents_v1():
    """
    Llista documents disponibles (API v1).
    STATUS: NOT IMPLEMENTED (Coming in FASE 15)
    """
    raise HTTPException(
        status_code=501,
        detail={
            "error": t_modular("rag.api.not_implemented_error", "Not Implemented"),
            "message": t_modular("rag.api.documents_scheduled", "Documents API scheduled for FASE 15"),
            "expected_date": "2025-12-15"
        }
    )

__all__ = ['router']
