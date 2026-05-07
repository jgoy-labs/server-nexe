"""
────────────────────────────────────
Server Nexe
Author: Jordi Goy 
Location: memory/rag_sources/file/api/v1.py
Description: API v1 for documentary file management (not yet available).

www.jgoy.net · https://server-nexe.org
────────────────────────────────────
"""

from fastapi import APIRouter, HTTPException

router = APIRouter(prefix="/documents", tags=["documents-v1", "future"])

@router.get("/", summary="Llistar documents disponibles al sistema de fitxers", operation_id="rag_files_list_v1")
async def list_documents_v1():
    """
    List available documents (API v1).
    STATUS: NOT IMPLEMENTED (coming soon)
    """
    raise HTTPException(
        status_code=501,
        detail={
            "error": "Not Implemented",
            "message": "Documents API not yet available",
        }
    )

__all__ = ['router']
