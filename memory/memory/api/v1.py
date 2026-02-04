"""
────────────────────────────────────
Server Nexe
Version: 0.8
Author: Jordi Goy
Location: memory/memory/api/v1.py
Description: Memory HTTP API v1 - Endpoints for /save and /recall from chat.

www.jgoy.net
────────────────────────────────────
"""

from fastapi import APIRouter, HTTPException, Request, Depends
from pydantic import BaseModel
from typing import Optional, Dict, Any, List
import logging
from plugins.security.core.auth_dependencies import require_api_key

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
    collection: str = "nexe_chat_memory"

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
                await _memory_api.create_collection("nexe_chat_memory", vector_size=384)
                logger.info("Created default collection: nexe_chat_memory")
        except Exception as e:
            logger.warning("Could not create default collection: %s", e)
    return _memory_api

@router.post("/store", response_model=MemoryStoreResponse, dependencies=[Depends(require_api_key)])
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
            await memory.create_collection(body.collection, vector_size=384)
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
        logger.error("Memory store failed: %s", e)
        raise HTTPException(
            status_code=500,
            detail={
                "error": "Store failed",
                "message": str(e),
                "hint": "Ensure Qdrant is running (./nexe go starts it automatically)"
            }
        )

@router.post("/search", response_model=MemorySearchResponse, dependencies=[Depends(require_api_key)])
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

        # Check if collection exists
        if not await memory.collection_exists(body.collection):
            return MemorySearchResponse(results=[], total=0)

        # Search
        results = await memory.search(
            query=body.query,
            collection=body.collection,
            top_k=body.limit,
            threshold=0.3
        )

        formatted_results = [
            MemorySearchResult(
                content=r.text,
                score=r.score,
                metadata=r.metadata or {}
            )
            for r in results
        ]

        logger.debug("Memory search for '%s' returned %d results", body.query[:50], len(formatted_results))

        return MemorySearchResponse(
            results=formatted_results,
            total=len(formatted_results)
        )

    except Exception as e:
        logger.error("Memory search failed: %s", e)
        raise HTTPException(
            status_code=500,
            detail={
                "error": "Search failed",
                "message": str(e),
                "hint": "Ensure Qdrant is running (./nexe go starts it automatically)"
            }
        )

@router.get("/health")
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
        return {
            "status": "unhealthy",
            "error": str(e),
            "hint": "Ensure Qdrant is running"
        }

__all__ = ['router']
