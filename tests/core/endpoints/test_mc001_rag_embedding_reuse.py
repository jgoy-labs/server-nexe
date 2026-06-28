"""MC-001: the RAG context builder searched three collections sequentially,
and each memory.search() recomputed the embedding for the SAME query — three
identical neural embeddings per /v1/chat request. The fix computes the query
embedding once and reuses it across the (now concurrent) collection searches.
"""
from unittest.mock import MagicMock

import core.endpoints.chat_rag as chat_rag


class _FakeMemory:
    def __init__(self, calls):
        self._calls = calls

    async def collection_exists(self, name):
        return True

    async def embed_query(self, text):
        self._calls["embed"] += 1
        return [0.1, 0.2, 0.3]

    async def search(
        self,
        query,
        collection,
        top_k=5,
        threshold=0.0,
        filter_metadata=None,
        include_expired=False,
        query_embedding=None,
    ):
        self._calls["search_q_emb"].append(query_embedding)
        return []


async def test_query_embedding_computed_once_and_reused(monkeypatch):
    calls = {"embed": 0, "search_q_emb": []}

    async def fake_get_memory_api():
        return _FakeMemory(calls)

    monkeypatch.setattr(
        "memory.memory.api.v1.get_memory_api", fake_get_memory_api
    )

    await chat_rag.build_rag_context("hola mon", MagicMock(), "ca")

    assert calls["embed"] == 1, f"embedding should be computed once, got {calls['embed']}"
    assert len(calls["search_q_emb"]) == 3, "expected one search per collection"
    assert all(
        e == [0.1, 0.2, 0.3] for e in calls["search_q_emb"]
    ), f"every search must reuse the precomputed embedding: {calls['search_q_emb']}"


async def test_search_order_preserved(monkeypatch):
    """gather must not reorder results: collections keep doc→knowledge→memory."""
    seen = []

    class _OrderMemory(_FakeMemory):
        async def search(self, query, collection, **kw):
            seen.append(collection)
            return []

    async def fake_get_memory_api():
        return _OrderMemory({"embed": 0, "search_q_emb": []})

    monkeypatch.setattr(
        "memory.memory.api.v1.get_memory_api", fake_get_memory_api
    )
    await chat_rag.build_rag_context("q", MagicMock(), "ca")
    assert seen == ["nexe_documentation", "user_knowledge", "personal_memory"]
