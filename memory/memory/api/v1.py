"""
────────────────────────────────────
Server Nexe
Author: Jordi Goy
Location: memory/memory/api/v1.py
Description: Memory HTTP API v1 - Endpoints for /save and /recall from chat.

www.jgoy.net · https://server-nexe.org
────────────────────────────────────
"""

from fastapi import APIRouter, HTTPException, Request, Depends
from pydantic import BaseModel
from typing import Optional, Dict, Any, List
import logging
from plugins.security.core.auth_dependencies import require_api_key
from ..constants import DEFAULT_VECTOR_SIZE
from .models import validate_collection_name, InvalidCollectionNameError

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/memory", tags=["memory-v1"])

class MemoryStoreRequest(BaseModel):
    """Request body for storing content in memory."""
    content: str
    metadata: Optional[Dict[str, Any]] = None
    collection: str = "personal_memory"
    force: bool = False  # Bypass Gate heuristic (skip min-length check)

class MemoryStoreResponse(BaseModel):
    """Response for store operation."""
    success: bool
    document_id: Optional[str] = None
    message: str

class MemorySearchRequest(BaseModel):
    """Request body for searching memory."""
    query: str
    limit: int = 5
    collection: Optional[str] = None
    collections: Optional[List[str]] = None

class MemorySearchResult(BaseModel):
    """Single search result."""
    content: str
    score: float
    metadata: Dict[str, Any] = {}

class MemorySearchResponse(BaseModel):
    """Response for search operation."""
    results: List[MemorySearchResult]
    total: int

# Global memory API instance (initialized on first use)
_memory_api = None

async def get_memory_api():
    """Get or create MemoryAPI instance."""
    global _memory_api
    if _memory_api is None:
        from . import MemoryAPI
        _memory_api = MemoryAPI()
        await _memory_api.initialize()
        # Les 3 col·leccions canòniques ("passadissos de la biblioteca RAG"):
        # - nexe_documentation: knowhow del propi nexe (knowledge/ folder auto-ingest)
        # - user_knowledge: documents ad-hoc que l'usuari puja al chat
        # - personal_memory: fets que el chat recorda de l'usuari (MEM_SAVE/RECALL)
        #
        # Nota: la col·lecció de memòria personal es deia "nexe_web_ui" fins
        # al refactor del 2026-04-08 (origen tècnic del plugin web_ui_module).
        # Renombrada a "personal_memory" per alinear el nom amb la funció.
        #
        # Ensure canonical collections exist (F5 fix). Previously only
        # the personal memory collection was created and nexe_documentation
        # was a silent skip in recall_from_memory(), making the "Base de
        # coneixement" sidebar permanently empty.
        canonical_collections = (
            "nexe_documentation", # corporate know-how from knowledge/ folder
            "user_knowledge",     # ad-hoc docs uploaded via chat UI
            "personal_memory",    # personal memory MEM_SAVE (was nexe_web_ui pre-2026-04-08)
        )
        for col in canonical_collections:
            try:
                if not await _memory_api.collection_exists(col):
                    await _memory_api.create_collection(col, vector_size=DEFAULT_VECTOR_SIZE)
                    logger.info("Created canonical collection: %s", col)
            except Exception as e:
                logger.warning("Could not create canonical collection %s: %s", col, e)
    return _memory_api

@router.post("/store", response_model=MemoryStoreResponse, dependencies=[Depends(require_api_key)], summary="Store content in semantic memory (API key required)")
async def memory_store(request: Request, body: MemoryStoreRequest):
    """
    Store content in semantic memory (RAG).

    Uses MemoryService.remember() if available, falls back to direct Qdrant.
    """
    try:
        validate_collection_name(body.collection)

        # Try MemoryService first (v1 pipeline)
        try:
            from ..module import get_memory_service
            svc = get_memory_service()
        except Exception:
            svc = None
        if svc and svc.initialized:
            metadata = body.metadata or {}
            user_id = metadata.get("user_id", "default")
            entry_id = await svc.remember(
                user_id=user_id,
                text=body.content,
                source="api",
                trust_level="untrusted",
                force=body.force,
            )
            return MemoryStoreResponse(
                success=entry_id is not None,
                document_id=entry_id,
                message="Content processed via MemoryService"
                if entry_id
                else "Content rejected by pipeline",
            )

        # Fallback to direct Qdrant
        memory = await get_memory_api()

        if not await memory.collection_exists(body.collection):
            await memory.create_collection(body.collection, vector_size=DEFAULT_VECTOR_SIZE)
            logger.info("Created collection on demand: %s", body.collection)

        metadata = body.metadata or {}
        metadata["source"] = metadata.get("source", "chat-cli")

        doc_id = await memory.store(
            text=body.content,
            collection=body.collection,
            metadata=metadata
        )

        logger.info("Stored document %s in collection %s", doc_id, body.collection)

        return MemoryStoreResponse(
            success=True,
            document_id=doc_id,
            message="Content stored successfully"
        )

    except InvalidCollectionNameError:
        raise HTTPException(status_code=400, detail="Invalid collection name. Must follow pattern 'module_type' with only lowercase, numbers and underscores.")
    except Exception as e:
        logger.error("Memory store failed: %s", e, exc_info=True)
        raise HTTPException(
            status_code=500,
            detail="Internal error. Check server logs."
        )

@router.post("/search", response_model=MemorySearchResponse, dependencies=[Depends(require_api_key)], summary="Search semantic memory by vector similarity (API key required)")
async def memory_search(request: Request, body: MemorySearchRequest):
    """
    Search semantic memory (RAG).

    Used by /recall command in chat CLI and for automatic RAG context.

    Args:
        body: Search query and parameters

    Returns:
        MemorySearchResponse with matching results
    """
    try:
        # Validate collection names
        if body.collection:
            validate_collection_name(body.collection)
        if body.collections:
            for col in body.collections:
                validate_collection_name(col)

        memory = await get_memory_api()

        # Determinar col·leccions a cercar
        if body.collections:
            cols = body.collections
        elif body.collection:
            cols = [body.collection]
        else:
            cols = ["nexe_documentation", "personal_memory", "user_knowledge"]

        formatted_results = []
        search_errors = 0
        cols_searched = 0
        last_error = None
        for col in cols:
            try:
                if not await memory.collection_exists(col):
                    continue
                cols_searched += 1
                results = await memory.search(
                    query=body.query,
                    collection=col,
                    top_k=body.limit,
                    threshold=0.3
                )
                for r in results:
                    meta = r.metadata or {} if hasattr(r, 'metadata') else {}
                    if isinstance(meta, dict):
                        meta["source_collection"] = col
                    formatted_results.append(MemorySearchResult(
                        content=r.text if hasattr(r, 'text') else str(r),
                        score=r.score,
                        metadata=meta
                    ))
            except Exception as e:
                search_errors += 1
                last_error = e
                logger.warning("Search failed for collection %s: %s", col, e)
                continue

        # Si totes les cerques van fallar, propagar l'error
        if cols_searched > 0 and search_errors == cols_searched and last_error:
            raise last_error

        formatted_results.sort(key=lambda x: x.score, reverse=True)
        formatted_results = formatted_results[:body.limit]

        logger.debug("Memory search for '%s' returned %d results from %d collections", body.query[:50], len(formatted_results), len(cols))

        return MemorySearchResponse(
            results=formatted_results,
            total=len(formatted_results)
        )

    except InvalidCollectionNameError:
        raise HTTPException(status_code=400, detail="Invalid collection name. Must follow pattern 'module_type' with only lowercase, numbers and underscores.")
    except Exception as e:
        logger.error("Memory search failed: %s", e, exc_info=True)
        raise HTTPException(
            status_code=500,
            detail="Internal error. Check server logs."
        )

@router.get("/health", summary="Health check for memory subsystem and Qdrant collections")
async def memory_health():
    """Health check for memory subsystem."""
    try:
        memory = await get_memory_api()
        collections = await memory.list_collections()
        return {
            "status": "healthy",
            "collections": len(collections),
            "initialized": True
        }
    except Exception as e:
        logger.error("Memory health check failed: %s", e)
        return {
            "status": "unhealthy",
            "hint": "Ensure Qdrant is running"
        }

__all__ = ['router']
