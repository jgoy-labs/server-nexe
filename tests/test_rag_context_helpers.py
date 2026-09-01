"""Tests for the helper functions used by RAG context building.

Covers: _search_collection, _deduplicate_results (core.endpoints.chat_rag).

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

from core.endpoints.chat_rag import (
    _search_collection,
    _deduplicate_results,
)


# ─── _search_collection ───────────────────────────────────────────────────────

def _make_rag_obj(text: str):
    obj = MagicMock()
    obj.text = text
    return obj


class TestSearchCollection:
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
        result = await _search_collection(memory, "nexe_documentation", "query", 0.4, 3)
        assert result == []
        memory.search.assert_not_called()

    @pytest.mark.asyncio
    async def test_returns_results_when_found(self):
        items = [_make_rag_obj("text1"), _make_rag_obj("text2")]
        memory = self._make_memory(exists=True, search_results=items)
        result = await _search_collection(memory, "nexe_documentation", "query", 0.4, 3)
        assert result == items

    @pytest.mark.asyncio
    async def test_empty_search_returns_empty(self):
        memory = self._make_memory(exists=True, search_results=[])
        result = await _search_collection(memory, "user_knowledge", "query", 0.35, 3)
        assert result == []

    @pytest.mark.asyncio
    async def test_exception_returns_empty(self):
        memory = self._make_memory(exists=True, raises=RuntimeError("db error"))
        result = await _search_collection(memory, "personal_memory", "query", 0.3, 2)
        assert result == []

    @pytest.mark.asyncio
    async def test_filter_metadata_passed_to_search(self):
        items = [_make_rag_obj("doc")]
        memory = self._make_memory(exists=True, search_results=items)
        await _search_collection(memory, "user_knowledge", "q", 0.35, 3, {"lang": "ca"})
        _, kwargs = memory.search.call_args
        assert kwargs.get("filter_metadata") == {"lang": "ca"}

    @pytest.mark.asyncio
    async def test_no_filter_metadata_not_passed(self):
        items = [_make_rag_obj("doc")]
        memory = self._make_memory(exists=True, search_results=items)
        await _search_collection(memory, "nexe_documentation", "q", 0.4, 3, None)
        _, kwargs = memory.search.call_args
        assert "filter_metadata" not in kwargs


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
