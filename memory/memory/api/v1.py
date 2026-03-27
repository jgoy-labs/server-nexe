"""
────────────────────────────────────
Server Nexe
Version: 0.8
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

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/memory", tags=["memory-v1"])

class MemoryStoreRequest(BaseModel):
    """Request body for storing content in memory."""
    content: str
    metadata: Optional[Dict[str, Any]] = None
    collection: str = "nexe_chat_memory"

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
        # Ensure default collection exists
        try:
            if not await _memory_api.collection_exists("nexe_chat_memory"):
                await _memory_api.create_collection("nexe_chat_memory", vector_size=DEFAULT_VECTOR_SIZE)
                logger.info("Created default collection: nexe_chat_memory")
        except Exception as e:
            logger.warning("Could not create default collection: %s", e)
    return _memory_api

@router.post("/store", response_model=MemoryStoreResponse, dependencies=[Depends(require_api_key)], summary="Guardar contingut a la memòria semàntica (🔒 API key)")
async def memory_store(request: Request, body: MemoryStoreRequest):
    """
    Store content in semantic memory (RAG).

    Used by /save command in chat CLI.

    Args:
        body: Content to store with optional metadata

    Returns:
        MemoryStoreResponse with document_id if successful
    """
    try:
        memory = await get_memory_api()

        # Ensure collection exists
        if not await memory.collection_exists(body.collection):
            await memory.create_collection(body.collection, vector_size=DEFAULT_VECTOR_SIZE)
            logger.info("Created collection on demand: %s", body.collection)

        # Store the content
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

    except Exception as e:
        logger.error("Memory store failed: %s", e, exc_info=True)
        raise HTTPException(
            status_code=500,
            detail="Internal error. Check server logs."
        )

@router.post("/search", response_model=MemorySearchResponse, dependencies=[Depends(require_api_key)], summary="Cercar a la memòria semàntica per similitud vectorial (🔒 API key)")
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
        memory = await get_memory_api()

        # Determinar col·leccions a cercar
        if body.collections:
            cols = body.collections
        elif body.collection:
            cols = [body.collection]
        else:
            cols = ["nexe_documentation", "nexe_web_ui", "user_knowledge", "nexe_chat_memory"]

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

    except Exception as e:
        logger.error("Memory search failed: %s", e, exc_info=True)
        raise HTTPException(
            status_code=500,
            detail="Internal error. Check server logs."
        )

@router.get("/health", summary="Health check del subsistema de memòria i col·leccions Qdrant")
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
