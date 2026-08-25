"""
────────────────────────────────────
Server Nexe
Author: Jordi Goy
Location: core/endpoints/chat_rag.py
Description: RAG context building and helpers for Chat endpoint.

www.jgoy.net · https://server-nexe.org
────────────────────────────────────
"""

import asyncio
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

            # MC-001: embed the (already NFKC-normalized) query ONCE and reuse it
            # for every collection instead of recomputing the identical embedding
            # three times. Falls back to per-search embedding if this fails.
            query_embedding = None
            try:
                query_embedding = await memory.embed_query(last_user_msg)
            except Exception as emb_err:
                logger.debug("RAG: query embedding precompute unavailable: %s", emb_err)

            # MC-001: run the per-collection searches concurrently (was serial).
            # gather preserves argument order, so all_results keeps the original
            # docs→knowledge→memory ordering that dedup/context rely on.
            per_collection = await asyncio.gather(*(
                _search_collection(memory, name, last_user_msg, threshold, top_k, filter_md, query_embedding)
                for name, threshold, top_k, filter_md in collections
            ))
            all_results: list = []
            for results in per_collection:
                all_results.extend(results)

            if all_results:
                context_text = _build_context_from_results(all_results)
                logger.info(
                    "RAG Context found (MemoryAPI): %d chars, %d results",
                    len(context_text), len(all_results),
                )
        except Exception as mem_err:
            # #899: aquí hi queia `_rag_module_fallback` (el RAG legacy,
            # PersonalityRAG), que ADR-002:68 ja descriu com estructuralment
            # buit: sempre tornava "" i el seu únic senyal era el WARNING que
            # B114 li va posar perquè el camí mort fos audible. Retirat el camí,
            # el senyal es queda — el que importa no era el fallback sinó que
            # el torn es respon SENSE CONTEXT i això no pot passar en silenci.
            # Ara surt sempre que MemoryAPI cau, no només quan hi havia un
            # mòdul `rag` registrat.
            logger.warning(
                "RAG: no context this turn — MemoryAPI unavailable: %s", mem_err,
            )

    except Exception as e:
        logger.error("RAG Error: %s", e, exc_info=True)
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
    query_embedding: "list[float] | None" = None,
) -> list:
    """Search a single MemoryAPI collection, returning [] on error or no results."""
    try:
        if await memory.collection_exists(name):
            kwargs: dict = dict(query=query, collection=name, top_k=top_k, threshold=threshold)
            if filter_metadata:
                kwargs["filter_metadata"] = filter_metadata
            if query_embedding is not None:
                kwargs["query_embedding"] = query_embedding
            results = await memory.search(**kwargs)
            if results:
                logger.info("RAG: Found %d docs from %s", len(results), name)
                return results
    except Exception as e:
        # MC-017: a failing search is NOT the same as the legitimate 0-results
        # case — log at warning so a broken RAG (Qdrant down) is visible in
        # production instead of looking like an empty knowledge base.
        logger.warning("RAG %s search failed: %s", name, e)
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
