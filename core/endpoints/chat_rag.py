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
import functools
import hashlib
import logging
import os
import unicodedata
from typing import Any, Optional

from core.memory_access import (
    DOCS_COLLECTION,
    KNOWLEDGE_COLLECTION,
    MEMORY_COLLECTION,
    SYSTEM_COLLECTIONS,
)

logger = logging.getLogger(__name__)

# Cosine similarity thresholds (0-1, higher = more restrictive)
# Configurable via env vars
RAG_DOCS_THRESHOLD = float(os.environ.get('NEXE_RAG_DOCS_THRESHOLD', '0.4'))
RAG_KNOWLEDGE_THRESHOLD = float(os.environ.get('NEXE_RAG_KNOWLEDGE_THRESHOLD', '0.35'))
RAG_MEMORY_THRESHOLD = float(os.environ.get('NEXE_RAG_MEMORY_THRESHOLD', '0.3'))

# Default search params for a collection outside the 3 system ones (#896):
# a plugin's own collection has no tuned threshold, so it gets the middle
# ground (knowledge-grade recall) instead of being skipped entirely.
_UNKNOWN_COLLECTION_PARAMS = (RAG_KNOWLEDGE_THRESHOLD, 3, None)


@functools.lru_cache(maxsize=1)
def system_rag_limit() -> int:
    """How many results (across all collections, after dedup) make the
    context (F-D block 3 — ported from the UI route, which alone had this).

    RAM-derived: virtual_memory().total is invariant at runtime, so cache it
    instead of recomputing via psutil on every chat request.
    """
    try:
        import psutil
        ram_gb = psutil.virtual_memory().total / (1024 ** 3)
        return 3 if ram_gb < 12 else 5
    except Exception:
        return 5


def _rag_params_for(
    name: str, server_lang: str, threshold_override: Optional[float] = None
) -> tuple[float, int, dict | None]:
    """(threshold, top_k, filter_metadata) for one collection, by name.

    ``threshold_override`` (F-D block 3, ported from the UI's per-turn
    ``rag_threshold`` — a slider in app.js persisted to localStorage, also a
    CLI flag): applies the SAME threshold to every collection, same as the
    single flat threshold the UI's old implementation had — only the tuned
    per-collection top_k/filter stay untouched. ``None`` (the default) keeps
    the 3 tuned thresholds.
    """
    if name == DOCS_COLLECTION:
        return (threshold_override if threshold_override is not None else RAG_DOCS_THRESHOLD, 3, None)
    if name == KNOWLEDGE_COLLECTION:
        return (
            threshold_override if threshold_override is not None else RAG_KNOWLEDGE_THRESHOLD,
            3, {"lang": server_lang},
        )
    if name == MEMORY_COLLECTION:
        return (threshold_override if threshold_override is not None else RAG_MEMORY_THRESHOLD, 2, None)
    return (
        threshold_override if threshold_override is not None else _UNKNOWN_COLLECTION_PARAMS[0],
        _UNKNOWN_COLLECTION_PARAMS[1], _UNKNOWN_COLLECTION_PARAMS[2],
    )


# MC-001's docs→knowledge→memory order (not SYSTEM_COLLECTIONS's docs→memory→
# knowledge, tuned for a different caller): all_results below keeps this
# order, and _build_context_from_results truncates to 5 — so this decides
# which sources get dropped first when a turn pulls in more than 5 hits.
_KNOWN_ORDER = {DOCS_COLLECTION: 0, KNOWLEDGE_COLLECTION: 1, MEMORY_COLLECTION: 2}


async def _discover_collection_names(memory: Any) -> list[str]:
    """Live collection names via list_collections(); SYSTEM_COLLECTIONS if that fails.

    #896: this is what makes a plugin's own collection show up in chat search
    without editing this file — the list used to be 3 hardcoded literals.
    The 3 known collections keep MC-001's fixed order; anything discovered
    beyond them (a plugin's own collection) is searched too, appended after.
    """
    try:
        infos = await memory.list_collections()
        names = [getattr(info, "name", None) for info in infos] if isinstance(infos, (list, tuple)) else []
        names = [n for n in names if isinstance(n, str) and n]
    except Exception as list_err:
        logger.debug("RAG: collection discovery unavailable, using system defaults: %s", list_err)
        names = []
    names = names or list(SYSTEM_COLLECTIONS)
    return sorted(names, key=lambda n: (_KNOWN_ORDER.get(n, len(_KNOWN_ORDER)), n))

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
    *,
    collections: Optional[list[str]] = None,
    limit: Optional[int] = None,
    threshold_override: Optional[float] = None,
) -> tuple[str, list[tuple[str, float]]]:
    """
    Build RAG context from MemoryAPI collections, with fallback to RAG module.

    Args:
        last_user_msg: The last user message to search for
        app_state: FastAPI app state
        server_lang: Server language code (e.g. "ca", "en")
        collections: F-D block 3 (ported from the UI's per-turn toggle) — when
            given, search ONLY these collection names instead of discovering
            everything. ``None`` (the default) searches everything, same as
            before this parameter existed.
        limit: how many results (after dedup) make the context. ``None``
            defaults to :func:`system_rag_limit` (RAM-derived, ported from
            the UI, which alone had this before F-D block 3).
        threshold_override: F-D block 3 (ported from the UI's per-turn
            ``rag_threshold`` — a slider in app.js, also a CLI flag).
            Applies the same threshold to every collection. ``None`` (the
            default) keeps the 3 tuned per-collection thresholds.

    Returns:
        (context_text, rag_items) — rag_items is [(collection, score), ...]
        for the results actually used, for a caller that wants to show or
        save which sources answered (message stats, RAG toggle counts).
    """
    # NFKC-normalize the query to mirror the ingest path.
    # Documents are NFKC-normalized at ingest via MemoryService.remember().
    # Single normalization here covers the three downstream memory.search() calls.
    last_user_msg = unicodedata.normalize("NFKC", last_user_msg)

    context_text = ""
    rag_items: list[tuple[str, float]] = []

    try:
        try:
            from memory.memory.api.v1 import get_memory_api
            memory = await get_memory_api()

            # F-D block 3: an explicit toggle searches only those collections;
            # #896's discovery (a plugin's own collection included) stays the
            # default when no toggle narrows it. `is not None` (not truthiness):
            # an empty list means "the user disabled every source", which must
            # search nothing — not fall through to "no restriction" (privacy
            # regression: personal_memory would answer despite the toggle).
            names = list(collections) if collections is not None else await _discover_collection_names(memory)
            search_plan = [
                (name, *_rag_params_for(name, server_lang, threshold_override)) for name in names
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
                for name, threshold, top_k, filter_md in search_plan
            ))
            all_results: list = []
            for results in per_collection:
                all_results.extend(results)

            if all_results:
                _effective_limit = limit if limit is not None else system_rag_limit()
                unique = _deduplicate_results(all_results)[:_effective_limit]
                context_text = _format_results(unique, server_lang)
                rag_items = [(getattr(r, "collection", "?"), getattr(r, "score", 0.0)) for r in unique]
                logger.info(
                    "RAG Context found (MemoryAPI): %d chars, %d results",
                    len(context_text), len(unique),
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

    return context_text, rag_items


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


def _format_results(results: list, server_lang: str = "en") -> str:
    """Format already-deduplicated, already-limited results into labelled,
    per-collection sections.

    The system prompt (server.toml, ca/es/en) tells the model to look for
    [DOCUMENTACIO DEL SISTEMA]/[MEMORIA DE L'USUARI]/etc. — those section
    markers must actually be in the context, or the model can deny having
    information it does have. `_RAG_CONTEXT_LABELS` already carries these
    labels (used elsewhere only for its "intro" key); this is the other use.
    `[Font: source]` stays per-item inside each section for traceability.
    """
    labels = _RAG_CONTEXT_LABELS.get(server_lang, _RAG_CONTEXT_LABELS["en"])
    buckets: dict[str, list[str]] = {"docs": [], "knowledge": [], "memory": []}
    for r in results:
        collection = getattr(r, "collection", None)
        key = (
            "docs" if collection == DOCS_COLLECTION
            else "memory" if collection == MEMORY_COLLECTION
            else "knowledge"
        )
        source = getattr(r, 'metadata', {}).get('source', 'unknown') if hasattr(r, 'metadata') else 'unknown'
        buckets[key].append(f"[Font: {source}]\n{r.text}")
    sections = [
        f"[{labels[key]}]\n" + "\n\n".join(buckets[key])
        for key in ("docs", "knowledge", "memory") if buckets[key]
    ]
    return "\n\n".join(sections)
