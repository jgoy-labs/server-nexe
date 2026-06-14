"""
────────────────────────────────────
Server Nexe
Author: Jordi Goy
Location: core/endpoints/chat_rag.py
Description: RAG context building and helpers for Chat endpoint.

www.jgoy.net · https://server-nexe.org
────────────────────────────────────
"""

import hashlib
import logging
import os
import unicodedata
from typing import Any

logger = logging.getLogger(__name__)

# Cosine similarity thresholds (0-1, higher = more restrictive)
# Configurable via env vars
RAG_DOCS_THRESHOLD = float(os.environ.get('NEXE_RAG_DOCS_THRESHOLD', '0.4'))
RAG_KNOWLEDGE_THRESHOLD = float(os.environ.get('NEXE_RAG_KNOWLEDGE_THRESHOLD', '0.35'))
RAG_MEMORY_THRESHOLD = float(os.environ.get('NEXE_RAG_MEMORY_THRESHOLD', '0.3'))

# RAG context labels per language (must match system prompt references)
_RAG_CONTEXT_LABELS = {
    "ca": {
        "docs": "DOCUMENTACIO DEL SISTEMA",
        "knowledge": "DOCUMENTACIO TECNICA",
        "memory": "MEMORIA DE L'USUARI",
        "intro": "Usa aquesta informació recuperada per respondre si és rellevant:",
    },
    "es": {
        "docs": "DOCUMENTACION DEL SISTEMA",
        "knowledge": "DOCUMENTACION TECNICA",
        "memory": "MEMORIA DEL USUARIO",
        "intro": "Usa esta información recuperada para responder si es relevante:",
    },
    "en": {
        "docs": "SYSTEM DOCUMENTATION",
        "knowledge": "TECHNICAL DOCUMENTATION",
        "memory": "USER MEMORY",
        "intro": "Use this retrieved information to answer if relevant:",
    },
}


def _rag_result_to_text(result: Any) -> str:
    """Normalize RAG results to plain text for context injection."""
    if isinstance(result, dict):
        return result.get("content") or result.get("text") or str(result)
    if hasattr(result, "text"):
        return result.text
    return str(result)


async def build_rag_context(
    last_user_msg: str,
    app_state: Any,
    server_lang: str,
) -> str:
    """
    Build RAG context from MemoryAPI collections, with fallback to RAG module.

    Args:
        last_user_msg: The last user message to search for
        app_state: FastAPI app state
        server_lang: Server language code (e.g. "ca", "en")

    Returns:
        Context text string (empty if no results)
    """
    # NFKC-normalize the query to mirror the ingest path.
    # Documents are NFKC-normalized at ingest via MemoryService.remember().
    # Single normalization here covers the three downstream memory.search() calls.
    last_user_msg = unicodedata.normalize("NFKC", last_user_msg)

    context_text = ""

    try:
        try:
            from memory.memory.api.v1 import get_memory_api
            memory = await get_memory_api()

            collections = [
                ("nexe_documentation", RAG_DOCS_THRESHOLD, 3, None),
                ("user_knowledge", RAG_KNOWLEDGE_THRESHOLD, 3, {"lang": server_lang}),
                ("personal_memory", RAG_MEMORY_THRESHOLD, 2, None),
            ]

            all_results: list = []
            for name, threshold, top_k, filter_md in collections:
                all_results.extend(
                    await _search_collection(memory, name, last_user_msg, threshold, top_k, filter_md)
                )

            if all_results:
                context_text = _build_context_from_results(all_results)
                logger.info(
                    "RAG Context found (MemoryAPI): %d chars, %d results",
                    len(context_text), len(all_results),
                )
        except Exception as mem_err:
            logger.debug("MemoryAPI not available: %s", mem_err)
            context_text = await _rag_module_fallback(app_state, last_user_msg)

    except Exception as e:
        logger.error("RAG Error: %s", e)
        # Continue without context rather than failing

    return context_text


# ─── Private helpers ─────────────────────────────────────────────────────────


async def _search_collection(
    memory: Any,
    name: str,
    query: str,
    threshold: float,
    top_k: int,
    filter_metadata: dict | None = None,
) -> list:
    """Search a single MemoryAPI collection, returning [] on error or no results."""
    try:
        if await memory.collection_exists(name):
            kwargs: dict = dict(query=query, collection=name, top_k=top_k, threshold=threshold)
            if filter_metadata:
                kwargs["filter_metadata"] = filter_metadata
            results = await memory.search(**kwargs)
            if results:
                logger.info("RAG: Found %d docs from %s", len(results), name)
                return results
    except Exception as e:
        logger.debug("RAG %s search failed: %s", name, e)
    return []


def _deduplicate_results(results: list) -> list:
    """Remove results with duplicate content (sha256 of first 500 chars)."""
    seen: set = set()
    unique = []
    for r in results:
        h = hashlib.sha256(r.text[:500].encode()).hexdigest()
        if h not in seen:
            seen.add(h)
            unique.append(r)
    return unique


def _build_context_from_results(all_results: list) -> str:
    """Deduplicate and format up to 5 results into the context string."""
    unique = _deduplicate_results(all_results)
    parts = []
    for r in unique[:5]:
        source = getattr(r, 'metadata', {}).get('source', 'unknown') if hasattr(r, 'metadata') else 'unknown'
        parts.append(f"[Font: {source}]\n{r.text}")
    return "\n\n".join(parts)


async def _rag_module_fallback(app_state: Any, query: str) -> str:
    """Fallback to legacy RAG module if MemoryAPI is unavailable."""
    from memory.rag_sources.base import SearchRequest

    rag_module = app_state.modules.get('rag') if hasattr(app_state, 'modules') else None
    if not (rag_module and hasattr(rag_module, 'search')):
        logger.debug("No RAG source available")
        return ""

    search_request = SearchRequest(query=query, top_k=3)
    results = await rag_module.search(search_request, source="personality")

    if not results:
        # B114: the legacy PersonalityRAG fallback is a structurally-empty dead
        # loop (superseded by MemoryAPI/Qdrant). Make the empty result audible
        # so the dead path is observable instead of silently swallowed.
        logger.warning("RAG Search returned no results")
        return ""

    if isinstance(results, list):
        context_text = "\n".join([_rag_result_to_text(r) for r in results])
    else:
        context_text = str(results)
    logger.info("RAG Context found (RAG module): %d chars", len(context_text))
    return context_text
