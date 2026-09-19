"""
────────────────────────────────────
Server Nexe
Author: Jordi Goy
Location: core/rag/collections.py
Description: The three sources server-nexe ships with, one per collection.

ADR-008. Retrieval was ALREADY per-collection — `_rag_params_for` gave each
one its own threshold, top_k and metadata filter, and `_search_collection`
searched it — so these were three sources without saying so. This makes it
explicit: the parameters are not rewritten here, they are MOVED, values and
all, and what is left in `core/endpoints/chat_rag.py` is the orchestration
that spans every source (one normalization, one embedding, the gather, the
dedup, the RAM-derived limit, the labelled sections, the degradation).

The thresholds live here with the source they tune — a collection's
parameters belong in one place, not split across two files — and are
re-exported by `chat_rag` for the public surface that already depended on
them (`core/endpoints/chat.py.__all__`).

www.jgoy.net · https://server-nexe.org
────────────────────────────────────
"""

from __future__ import annotations

import logging
import os
from typing import Any, List

from core.memory_access import (
    DOCS_COLLECTION,
    KNOWLEDGE_COLLECTION,
    MEMORY_COLLECTION,
)
from core.rag.source import RAGQuery

logger = logging.getLogger(__name__)

# Cosine similarity thresholds (0-1, higher = more restrictive), read at
# import time from the environment — the semantics they have always had.
RAG_DOCS_THRESHOLD = float(os.environ.get('NEXE_RAG_DOCS_THRESHOLD', '0.4'))
RAG_KNOWLEDGE_THRESHOLD = float(os.environ.get('NEXE_RAG_KNOWLEDGE_THRESHOLD', '0.35'))
RAG_MEMORY_THRESHOLD = float(os.environ.get('NEXE_RAG_MEMORY_THRESHOLD', '0.3'))


class CollectionSource:
    """One Qdrant collection, searched with its own tuned parameters.

    One class with three instances rather than three classes: what separates
    the sources is DATA (which collection, how strict, how many, whether the
    turn's language filters it), not behaviour.

    The parameters are public and read-only by convention: they are the
    source's identity, not an implementation detail — the E1b registry will
    want to show them, and a test that pins the tuned values has somewhere
    honest to look.
    """

    def __init__(
        self,
        collection: str,
        *,
        threshold: float,
        top_k: int,
        filter_by_lang: bool = False,
    ) -> None:
        self.collection = collection
        self.threshold = threshold
        self.top_k = top_k
        self.filter_by_lang = filter_by_lang

    def name(self) -> str:
        return self.collection

    async def search(self, memory: Any, query: RAGQuery) -> List[Any]:
        """Search this collection, returning [] on error or no results.

        The existence guard stays, and stays BEFORE the search: `MemoryAPI`
        raises `CollectionNotFoundError` for a missing collection, and asking
        first is what turns "this install has no documentation collection"
        into an empty list instead of a warning on every single turn.
        """
        threshold = (
            query.threshold_override
            if query.threshold_override is not None
            else self.threshold
        )
        try:
            if await memory.collection_exists(self.collection):
                kwargs: dict = dict(
                    query=query.text,
                    collection=self.collection,
                    top_k=self.top_k,
                    threshold=threshold,
                )
                if self.filter_by_lang:
                    kwargs["filter_metadata"] = {"lang": query.lang}
                if query.embedding is not None:
                    kwargs["query_embedding"] = query.embedding
                results = await memory.search(**kwargs)
                if results:
                    logger.info("RAG: Found %d docs from %s", len(results), self.collection)
                    return results
        except Exception as e:
            # MC-017: a failing search is NOT the same as the legitimate
            # 0-results case — log at warning so a broken RAG (Qdrant down) is
            # visible in production instead of looking like an empty knowledge
            # base.
            logger.warning("RAG %s search failed: %s", self.collection, e)
        return []


DOCS_SOURCE = CollectionSource(
    DOCS_COLLECTION, threshold=RAG_DOCS_THRESHOLD, top_k=3,
)
KNOWLEDGE_SOURCE = CollectionSource(
    KNOWLEDGE_COLLECTION, threshold=RAG_KNOWLEDGE_THRESHOLD, top_k=3, filter_by_lang=True,
)
MEMORY_SOURCE = CollectionSource(
    MEMORY_COLLECTION, threshold=RAG_MEMORY_THRESHOLD, top_k=2,
)

_SYSTEM_SOURCES = {s.name(): s for s in (DOCS_SOURCE, KNOWLEDGE_SOURCE, MEMORY_SOURCE)}


def source_for(collection: str) -> CollectionSource:
    """The source that searches `collection`.

    #896: a collection a plugin registered at runtime has no tuned
    parameters, so it gets the middle ground (knowledge-grade recall, no
    language filter) instead of being skipped entirely — the same values
    `_UNKNOWN_COLLECTION_PARAMS` gave it before there were sources. E1b turns
    this into a registry a plugin can add to; today it is still the
    orchestrator that discovers the names.
    """
    known = _SYSTEM_SOURCES.get(collection)
    if known is not None:
        return known
    return CollectionSource(collection, threshold=RAG_KNOWLEDGE_THRESHOLD, top_k=3)
