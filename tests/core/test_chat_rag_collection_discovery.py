"""
────────────────────────────────────
Server Nexe
Author: Jordi Goy
Location: tests/core/test_chat_rag_collection_discovery.py
Description: #896 — chat RAG discovers collections instead of a hardcoded
             3-item list, so a plugin's own collection is searched too.

www.jgoy.net · https://server-nexe.org
────────────────────────────────────
"""

from unittest.mock import AsyncMock, MagicMock

import pytest

from core.endpoints.chat_rag import (
    _discover_collection_names,
    build_rag_context,
)
from core.rag.collections import source_for
from core.memory_access import DOCS_COLLECTION, KNOWLEDGE_COLLECTION, MEMORY_COLLECTION


class _Info:
    def __init__(self, name):
        self.name = name


class _Result:
    def __init__(self, text, score=0.9, metadata=None):
        self.text = text
        self.score = score
        self.metadata = metadata or {}


def _memory(**methods):
    api = MagicMock()
    api.list_collections = AsyncMock(return_value=[])
    api.embed_query = AsyncMock(return_value=[0.1, 0.2])
    api.collection_exists = AsyncMock(return_value=True)
    api.search = AsyncMock(return_value=[])
    for name, value in methods.items():
        setattr(api, name, value)
    return api


class TestDiscoverCollectionNames:
    @pytest.mark.asyncio
    async def test_discovers_a_plugin_collection_beyond_the_3_system_ones(self):
        memory = _memory(list_collections=AsyncMock(return_value=[
            _Info(MEMORY_COLLECTION),
            _Info("agenda_notes"),  # a plugin's own collection — the #896 case
            _Info(DOCS_COLLECTION),
            _Info(KNOWLEDGE_COLLECTION),
        ]))
        names = await _discover_collection_names(memory)
        assert "agenda_notes" in names
        assert set(names) == {DOCS_COLLECTION, KNOWLEDGE_COLLECTION, MEMORY_COLLECTION, "agenda_notes"}

    @pytest.mark.asyncio
    async def test_the_3_known_collections_keep_their_fixed_order(self):
        memory = _memory(list_collections=AsyncMock(return_value=[
            _Info(MEMORY_COLLECTION), _Info(KNOWLEDGE_COLLECTION), _Info(DOCS_COLLECTION),
        ]))
        names = await _discover_collection_names(memory)
        assert names == [DOCS_COLLECTION, KNOWLEDGE_COLLECTION, MEMORY_COLLECTION]

    @pytest.mark.asyncio
    async def test_unknown_collection_is_appended_after_the_known_3(self):
        memory = _memory(list_collections=AsyncMock(return_value=[
            _Info("agenda_notes"), _Info(MEMORY_COLLECTION), _Info(DOCS_COLLECTION), _Info(KNOWLEDGE_COLLECTION),
        ]))
        names = await _discover_collection_names(memory)
        assert names == [DOCS_COLLECTION, KNOWLEDGE_COLLECTION, MEMORY_COLLECTION, "agenda_notes"]

    @pytest.mark.asyncio
    async def test_falls_back_to_system_collections_when_list_collections_raises(self):
        memory = _memory(list_collections=AsyncMock(side_effect=RuntimeError("qdrant down")))
        names = await _discover_collection_names(memory)
        assert names == [DOCS_COLLECTION, KNOWLEDGE_COLLECTION, MEMORY_COLLECTION]

    @pytest.mark.asyncio
    async def test_falls_back_to_system_collections_when_list_is_empty(self):
        memory = _memory(list_collections=AsyncMock(return_value=[]))
        names = await _discover_collection_names(memory)
        assert names == [DOCS_COLLECTION, KNOWLEDGE_COLLECTION, MEMORY_COLLECTION]

    @pytest.mark.asyncio
    async def test_falls_back_when_list_collections_returns_something_unusable(self):
        memory = _memory(list_collections=AsyncMock(return_value=MagicMock()))
        names = await _discover_collection_names(memory)
        assert names == [DOCS_COLLECTION, KNOWLEDGE_COLLECTION, MEMORY_COLLECTION]


class TestTunedParamsPerSource:
    """ADR-008 (E1a): the tuned parameters moved from `_rag_params_for` into
    the source that applies them. Same values, same pairing, asserted where
    they live now — `source_for` is what maps a collection name to them."""

    def test_known_collections_keep_their_tuned_params(self):
        from core.endpoints.chat_rag import RAG_DOCS_THRESHOLD, RAG_KNOWLEDGE_THRESHOLD, RAG_MEMORY_THRESHOLD
        docs = source_for(DOCS_COLLECTION)
        assert (docs.threshold, docs.top_k, docs.filter_by_lang) == (RAG_DOCS_THRESHOLD, 3, False)
        knowledge = source_for(KNOWLEDGE_COLLECTION)
        assert (knowledge.threshold, knowledge.top_k, knowledge.filter_by_lang) == (RAG_KNOWLEDGE_THRESHOLD, 3, True)
        memory = source_for(MEMORY_COLLECTION)
        assert (memory.threshold, memory.top_k, memory.filter_by_lang) == (RAG_MEMORY_THRESHOLD, 2, False)

    def test_unknown_collection_gets_generic_defaults(self):
        from core.endpoints.chat_rag import RAG_KNOWLEDGE_THRESHOLD
        unknown = source_for("agenda_notes")
        assert unknown.name() == "agenda_notes"
        assert (unknown.threshold, unknown.top_k, unknown.filter_by_lang) == (RAG_KNOWLEDGE_THRESHOLD, 3, False)


class TestBuildRagContextSearchesDiscoveredCollections:
    @pytest.mark.asyncio
    async def test_a_plugins_collection_is_actually_searched_not_silently_skipped(self, monkeypatch):
        """#896 end-to-end: before this fix, a 4th collection was invisible —
        chat_rag.py had 3 hardcoded literals and nothing else was ever queried.
        """
        memory = _memory(
            list_collections=AsyncMock(return_value=[
                _Info(DOCS_COLLECTION), _Info(KNOWLEDGE_COLLECTION), _Info(MEMORY_COLLECTION),
                _Info("agenda_notes"),
            ]),
        )

        async def _search(*, query, collection, top_k, threshold, **kwargs):
            if collection == "agenda_notes":
                return [_Result("Meeting with Jordi at 10am", metadata={"source": "agenda_notes"})]
            return []

        memory.search = AsyncMock(side_effect=_search)

        import core.endpoints.chat_rag as chat_rag_module
        monkeypatch.setattr(
            "memory.memory.api.v1.get_memory_api", AsyncMock(return_value=memory),
        )

        context, _rag_items = await chat_rag_module.build_rag_context("what's on my agenda?", app_state=None, server_lang="en")
        assert "Meeting with Jordi at 10am" in context

    @pytest.mark.asyncio
    async def test_only_the_3_system_collections_are_searched_when_nothing_else_exists(self, monkeypatch):
        memory = _memory(
            list_collections=AsyncMock(return_value=[
                _Info(DOCS_COLLECTION), _Info(KNOWLEDGE_COLLECTION), _Info(MEMORY_COLLECTION),
            ]),
        )
        searched = []

        async def _search(*, query, collection, top_k, threshold, **kwargs):
            searched.append(collection)
            return []

        memory.search = AsyncMock(side_effect=_search)
        monkeypatch.setattr(
            "memory.memory.api.v1.get_memory_api", AsyncMock(return_value=memory),
        )
        await build_rag_context("hello", app_state=None, server_lang="en")
        assert set(searched) == {DOCS_COLLECTION, KNOWLEDGE_COLLECTION, MEMORY_COLLECTION}
