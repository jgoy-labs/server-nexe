"""Tests for the helper functions extracted from _build_rag_context.

Covers: _build_rag_items_tuple, _filter_relevant_results,
        _format_rag_sections_by_language, _search_collection,
        _deduplicate_results.
"""

import hashlib
import logging
import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from plugins.web_ui_module.api.routes_chat import (
    _build_rag_items_tuple,
    _filter_relevant_results,
    _format_rag_sections_by_language,
)
from core.endpoints.chat_rag import (
    _search_collection,
    _deduplicate_results,
)


def _make_result(content, score, collection):
    return {
        "content": content,
        "score": score,
        "metadata": {"source_collection": collection},
    }


# ─── _build_rag_items_tuple ──────────────────────────────────────────────────

class TestBuildRagItemsTuple:
    def test_empty_list_returns_empty(self):
        assert _build_rag_items_tuple([]) == []

    def test_single_item_returns_tuple(self):
        item = _make_result("contingut", 0.85, "nexe_documentation")
        result = _build_rag_items_tuple([item])
        assert result == [("nexe_documentation", 0.85)]

    def test_multiple_items_preserves_order(self):
        items = [
            _make_result("a", 0.9, "nexe_documentation"),
            _make_result("b", 0.7, "user_knowledge"),
            _make_result("c", 0.5, "personal_memory"),
        ]
        result = _build_rag_items_tuple(items)
        assert result == [
            ("nexe_documentation", 0.9),
            ("user_knowledge", 0.7),
            ("personal_memory", 0.5),
        ]

    def test_missing_metadata_returns_unknown_collection(self):
        item = {"content": "text", "score": 0.6}
        result = _build_rag_items_tuple([item])
        assert result == [("?", 0.6)]

    def test_missing_score_defaults_to_zero(self):
        item = {"content": "text", "metadata": {"source_collection": "nexe_documentation"}}
        result = _build_rag_items_tuple([item])
        assert result == [("nexe_documentation", 0)]


# ─── _filter_relevant_results ─────────────────────────────────────────────────

class TestFilterRelevantResults:
    def setup_method(self):
        self.log = logging.getLogger("test")

    def test_empty_results_returns_three_empty_lists(self):
        doc, know, mem = _filter_relevant_results([], 0.25, self.log)
        assert doc == []
        assert know == []
        assert mem == []

    def test_all_below_threshold_returns_empty(self):
        items = [
            _make_result("a", 0.1, "nexe_documentation"),
            _make_result("b", 0.2, "user_knowledge"),
        ]
        doc, know, mem = _filter_relevant_results(items, 0.25, self.log)
        assert doc == []
        assert know == []
        assert mem == []

    def test_threshold_boundary_exact_match_included(self):
        item = _make_result("exacte", 0.25, "nexe_documentation")
        doc, know, mem = _filter_relevant_results([item], 0.25, self.log)
        assert len(doc) == 1
        assert know == []
        assert mem == []

    def test_splits_into_three_categories(self):
        items = [
            _make_result("doc", 0.8, "nexe_documentation"),
            _make_result("know", 0.7, "user_knowledge"),
            _make_result("mem", 0.6, "personal_memory"),
        ]
        doc, know, mem = _filter_relevant_results(items, 0.25, self.log)
        assert len(doc) == 1
        assert len(know) == 1
        assert len(mem) == 1

    def test_mixed_threshold_filters_correctly(self):
        items = [
            _make_result("doc ok", 0.9, "nexe_documentation"),
            _make_result("doc ko", 0.1, "nexe_documentation"),
            _make_result("know ok", 0.5, "user_knowledge"),
        ]
        doc, know, mem = _filter_relevant_results(items, 0.25, self.log)
        assert len(doc) == 1
        assert doc[0]["content"] == "doc ok"
        assert len(know) == 1
        assert mem == []


# ─── _format_rag_sections_by_language ────────────────────────────────────────

class TestFormatRagSectionsByLanguage:
    def test_all_empty_returns_empty_string(self):
        result = _format_rag_sections_by_language([], [], [], "ca")
        assert result == ""

    def test_only_doc_items_catala(self):
        docs = [_make_result("la doc", 0.9, "nexe_documentation")]
        result = _format_rag_sections_by_language(docs, [], [], "ca")
        assert "DOCUMENTACIO DEL SISTEMA" in result
        assert "la doc" in result
        assert "DOCUMENTACIO TECNICA" not in result

    def test_only_knowledge_items_espanyol(self):
        know = [_make_result("el coneixement", 0.8, "user_knowledge")]
        result = _format_rag_sections_by_language([], know, [], "es")
        assert "DOCUMENTACION TECNICA" in result
        assert "el coneixement" in result

    def test_only_memory_items_angles(self):
        mems = [_make_result("a memory", 0.7, "personal_memory")]
        result = _format_rag_sections_by_language([], [], mems, "en")
        assert "USER MEMORY" in result
        assert "a memory" in result

    def test_unknown_lang_falls_back_to_english(self):
        docs = [_make_result("doc text", 0.9, "nexe_documentation")]
        result = _format_rag_sections_by_language(docs, [], [], "xx")
        assert "SYSTEM DOCUMENTATION" in result

    def test_all_three_sections_present(self):
        docs = [_make_result("d", 0.9, "nexe_documentation")]
        know = [_make_result("k", 0.8, "user_knowledge")]
        mems = [_make_result("m", 0.7, "personal_memory")]
        result = _format_rag_sections_by_language(docs, know, mems, "ca")
        assert "DOCUMENTACIO DEL SISTEMA" in result
        assert "DOCUMENTACIO TECNICA" in result
        assert "MEMORIA DE L'USUARI" in result
        assert "d" in result
        assert "k" in result
        assert "m" in result

    def test_multiple_items_in_section(self):
        docs = [
            _make_result("primer", 0.9, "nexe_documentation"),
            _make_result("segon", 0.8, "nexe_documentation"),
        ]
        result = _format_rag_sections_by_language(docs, [], [], "en")
        assert "primer" in result
        assert "segon" in result


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
