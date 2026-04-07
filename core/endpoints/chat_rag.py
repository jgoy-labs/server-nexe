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
    from memory.rag_sources.base import SearchRequest

    context_text = ""

    try:
        # Try MemoryAPI first (same as /v1/memory/store uses)
        try:
            from memory.memory.api.v1 import get_memory_api
            memory = await get_memory_api()

            all_results = []

            # 1. Search documentation first (nexe_documentation)
            try:
                if await memory.collection_exists("nexe_documentation"):
                    doc_results = await memory.search(
                        query=last_user_msg,
                        collection="nexe_documentation",
                        top_k=3,
                        threshold=RAG_DOCS_THRESHOLD
                    )
                    if doc_results:
                        all_results.extend(doc_results)
                        logger.info("RAG: Found %d docs from documentation", len(doc_results))
            except Exception as e:
                logger.debug("RAG docs search failed: %s", e)

            # 2. Search user knowledge (custom documents in knowledge/ folder)
            try:
                if await memory.collection_exists("user_knowledge"):
                    knowledge_results = await memory.search(
                        query=last_user_msg,
                        collection="user_knowledge",
                        top_k=3,
                        threshold=RAG_KNOWLEDGE_THRESHOLD,
                        filter_metadata={"lang": server_lang}
                    )
                    if knowledge_results:
                        all_results.extend(knowledge_results)
                        logger.info("RAG: Found %d docs from user knowledge", len(knowledge_results))
            except Exception as e:
                logger.debug("RAG knowledge search failed: %s", e)

            # 3. Search user memory (personal_memory - conversations)
            try:
                if await memory.collection_exists("personal_memory"):
                    mem_results = await memory.search(
                        query=last_user_msg,
                        collection="personal_memory",
                        top_k=2,
                        threshold=RAG_MEMORY_THRESHOLD
                    )
                    if mem_results:
                        all_results.extend(mem_results)
                        logger.info("RAG: Found %d docs from chat memory", len(mem_results))
            except Exception as e:
                logger.debug("RAG chat memory search failed: %s", e)

            if all_results:
                # Deduplicate results by content hash
                seen_hashes = set()
                unique_results = []
                for r in all_results:
                    content_hash = hashlib.sha256(r.text[:500].encode()).hexdigest()
                    if content_hash not in seen_hashes:
                        seen_hashes.add(content_hash)
                        unique_results.append(r)
                # Build context with clear source headers
                context_parts = []
                for r in unique_results[:5]:
                    source = getattr(r, 'metadata', {}).get('source', 'unknown') if hasattr(r, 'metadata') else 'unknown'
                    context_parts.append(f"[Font: {source}]\n{r.text}")
                context_text = "\n\n".join(context_parts)
                logger.info("RAG Context found (MemoryAPI): %d chars, %d results", len(context_text), len(all_results))
        except Exception as mem_err:
            logger.debug("MemoryAPI not available: %s", mem_err)

            # Fallback to RAG module if MemoryAPI fails
            rag_module = None
            if hasattr(app_state, 'modules'):
                rag_module = app_state.modules.get('rag')

            if rag_module and hasattr(rag_module, 'search'):
                search_request = SearchRequest(query=last_user_msg, top_k=3)
                results = await rag_module.search(search_request, source="personality")

                if results:
                    if isinstance(results, list):
                        context_text = "\n".join([_rag_result_to_text(r) for r in results])
                    else:
                        context_text = str(results)
                    logger.info("RAG Context found (RAG module): %d chars", len(context_text))
                else:
                    logger.info("RAG Search returned no results")
            else:
                logger.debug("No RAG source available")

    except Exception as e:
        logger.error("RAG Error: %s", e)
        # Continue without context rather than failing

    return context_text
