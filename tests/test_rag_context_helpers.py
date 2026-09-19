"""Tests for the helper functions used by RAG context building.

Covers: CollectionSource.search (core.rag.collections) and
_deduplicate_results (core.endpoints.chat_rag).

ADR-008 (E1a): searching ONE collection with its tuned parameters is a
source's job now, not a free function's — `_search_collection` became
`CollectionSource.search`. These tests are re-pointed, not rewritten: every
assertion below is the one it made before (the existence guard runs first and
short-circuits, a failure degrades to [], the language filter is passed only
when the source has one), because the behaviour is the thing that must not
have moved.

F-D block 3 (2026-08-31): _build_rag_items_tuple, _filter_relevant_results
and _format_rag_sections_by_language (plugins/web_ui_module) were deleted —
the UI route now delegates retrieval to core.endpoints.chat_rag.build_rag_context
(same per-collection thresholds, dedup and RAM-derived limit /v1 uses), so
there is nothing left there to unit-test in isolation. Their coverage lives
in tests/core/endpoints/test_fd_block3_rag_unified.py (the new gate) and
tests/core/test_chat_rag_collection_discovery.py.
"""

import pytest
from unittest.mock import AsyncMock, MagicMock

from core.endpoints.chat_rag import _deduplicate_results
from core.rag.collections import (
    DOCS_SOURCE,
    KNOWLEDGE_SOURCE,
    MEMORY_SOURCE,
)
from core.rag.source import RAGQuery


# ─── CollectionSource.search ─────────────────────────────────────────────────

def _make_rag_obj(text: str):
    obj = MagicMock()
    obj.text = text
    return obj


class TestCollectionSourceSearch:
    def _make_memory(self, exists: bool, search_results=None, raises=None):
        memory = MagicMock()
        memory.collection_exists = AsyncMock(return_value=exists)
        if raises:
            memory.search = AsyncMock(side_effect=raises)
        else:
            memory.search = AsyncMock(return_value=search_results or [])
        return memory

    @pytest.mark.asyncio
    async def test_collection_not_exists_returns_empty(self):
        memory = self._make_memory(exists=False)
        result = await DOCS_SOURCE.search(memory, RAGQuery(text="query"))
        assert result == []
        memory.search.assert_not_called()

    @pytest.mark.asyncio
    async def test_returns_results_when_found(self):
        items = [_make_rag_obj("text1"), _make_rag_obj("text2")]
        memory = self._make_memory(exists=True, search_results=items)
        result = await DOCS_SOURCE.search(memory, RAGQuery(text="query"))
        assert result == items

    @pytest.mark.asyncio
    async def test_empty_search_returns_empty(self):
        memory = self._make_memory(exists=True, search_results=[])
        result = await KNOWLEDGE_SOURCE.search(memory, RAGQuery(text="query"))
        assert result == []

    @pytest.mark.asyncio
    async def test_exception_returns_empty(self):
        memory = self._make_memory(exists=True, raises=RuntimeError("db error"))
        result = await MEMORY_SOURCE.search(memory, RAGQuery(text="query"))
        assert result == []

    @pytest.mark.asyncio
    async def test_filter_metadata_passed_to_search(self):
        items = [_make_rag_obj("doc")]
        memory = self._make_memory(exists=True, search_results=items)
        await KNOWLEDGE_SOURCE.search(memory, RAGQuery(text="q", lang="ca"))
        _, kwargs = memory.search.call_args
        assert kwargs.get("filter_metadata") == {"lang": "ca"}

    @pytest.mark.asyncio
    async def test_no_filter_metadata_not_passed(self):
        items = [_make_rag_obj("doc")]
        memory = self._make_memory(exists=True, search_results=items)
        await DOCS_SOURCE.search(memory, RAGQuery(text="q", lang="ca"))
        _, kwargs = memory.search.call_args
        assert "filter_metadata" not in kwargs

    @pytest.mark.asyncio
    async def test_each_source_searches_with_its_own_tuned_params(self):
        """The values that used to live in `_rag_params_for`, asserted where
        they live now. Not a new test: the pairing collection↔(threshold,
        top_k, filter) is what that function was, and losing it silently is
        the one way this refactor could have changed retrieval."""
        for source, top_k, filtered in (
            (DOCS_SOURCE, 3, False),
            (KNOWLEDGE_SOURCE, 3, True),
            (MEMORY_SOURCE, 2, False),
        ):
            memory = self._make_memory(exists=True, search_results=[_make_rag_obj("x")])
            await source.search(memory, RAGQuery(text="q", lang="ca"))
            _, kwargs = memory.search.call_args
            assert kwargs["collection"] == source.name()
            assert kwargs["top_k"] == top_k
            assert kwargs["threshold"] == source.threshold
            assert ("filter_metadata" in kwargs) is filtered

    @pytest.mark.asyncio
    async def test_the_override_replaces_the_tuned_threshold(self):
        """One slider, every source — and the tuned top_k/filter untouched."""
        memory = self._make_memory(exists=True, search_results=[_make_rag_obj("x")])
        await KNOWLEDGE_SOURCE.search(
            memory, RAGQuery(text="q", lang="ca", threshold_override=0.9),
        )
        _, kwargs = memory.search.call_args
        assert kwargs["threshold"] == 0.9
        assert kwargs["top_k"] == 3
        assert kwargs["filter_metadata"] == {"lang": "ca"}


# ─── _deduplicate_results ─────────────────────────────────────────────────────

class TestDeduplicateResults:
    def test_empty_returns_empty(self):
        assert _deduplicate_results([]) == []

    def test_no_duplicates_preserves_all(self):
        items = [_make_rag_obj("text1"), _make_rag_obj("text2")]
        result = _deduplicate_results(items)
        assert len(result) == 2

    def test_duplicates_removed(self):
        obj1 = _make_rag_obj("same content")
        obj2 = _make_rag_obj("same content")
        result = _deduplicate_results([obj1, obj2])
        assert len(result) == 1
        assert result[0] is obj1

    def test_dedup_uses_first_500_chars(self):
        long_text = "A" * 501
        obj1 = _make_rag_obj(long_text)
        obj2 = _make_rag_obj(long_text[:-1] + "B")
        result = _deduplicate_results([obj1, obj2])
        # The first 500 chars are identical → duplicate
        assert len(result) == 1

    def test_preserves_order(self):
        items = [_make_rag_obj(f"text{i}") for i in range(5)]
        result = _deduplicate_results(items)
        assert [r.text for r in result] == [f"text{i}" for i in range(5)]
