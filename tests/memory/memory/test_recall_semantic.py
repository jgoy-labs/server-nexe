"""
────────────────────────────────────
Server Nexe
Author: Jordi Goy
Location: tests/memory/memory/test_recall_semantic.py
Description: B112 — behavioral tests for MemoryService.recall() semantic mode.
    Proves recall() actually USES the query (vector hit beats recency), hydrates
    real content from SQLite (not the placeholder), degrades to recency when no
    embedder is injected or the semantic layer is empty, and never leaks
    forgotten ids. Uses fake embedder/vector doubles — no model download.

www.jgoy.net · https://server-nexe.org
────────────────────────────────────
"""

import pytest

from memory.memory.memory_service import MemoryService


class FakeEmbedder:
    """Deterministic embedder double (no model download)."""

    def encode(self, text: str):
        return [0.1, 0.2, 0.3]


class FakeVectorIndex:
    """VectorIndex double returning canned candidates regardless of query."""

    available = True

    def __init__(self, candidates):
        self._candidates = candidates

    def search(self, embedding, user_id, threshold, limit, namespace=None):
        return list(self._candidates)


def _cand(entry_id, score, content=None):
    """A search hit. By default the payload carries NO content (mirrors the real
    VectorIndex, which stores metadata only) so hydration from SQLite is exercised."""
    payload = {"rdbms_id": entry_id, "user_id": "u1", "state": "active"}
    if content is not None:
        payload["content"] = content
    return {"id": entry_id, "score": score, "payload": payload}


@pytest.fixture
def svc(tmp_path):
    """MemoryService with temp SQLite, no Qdrant."""
    return MemoryService(db_path=tmp_path / "sem.db", qdrant_path=None)


class TestRecallSemantic:

    @pytest.mark.asyncio
    async def test_semantic_returns_hydrated_real_content(self, svc):
        """A vector hit becomes a card with the REAL SQLite content, not the
        [episodic:<id>] placeholder. Mutation gate for the retriever.py:107 bug."""
        await svc.initialize()
        eid = svc._store.insert_episodic(
            user_id="u1", content="I love climbing in the Pyrenees"
        )
        # payload deliberately has NO content → forces SQLite hydration
        svc._vector_index = FakeVectorIndex([_cand(eid, 0.9)])
        svc.set_embedder(FakeEmbedder())

        cards = await svc.recall(user_id="u1", query="mountain hobbies")

        assert any(
            c.entry_id == eid and c.content == "I love climbing in the Pyrenees"
            for c in cards
        )
        assert all(not c.content.startswith("[episodic:") for c in cards)

    @pytest.mark.asyncio
    async def test_vector_hit_beats_recency(self, svc):
        """The vector hit re-ranks the episodic layer above mere recency: with a
        single-card limit the relevant (older) memory wins over the newer one.
        This proves delegation + merge + trim with FAKE doubles (the fake search
        ignores the query). Actual relevance ranking with REAL embeddings is
        covered in test_recall_semantic_real.py."""
        await svc.initialize()
        relevant = svc._store.insert_episodic(
            user_id="u1", content="I love climbing in the Pyrenees"
        )
        # newer + irrelevant — recency would surface THIS first
        svc._store.insert_episodic(user_id="u1", content="I bought milk today")
        svc._vector_index = FakeVectorIndex([_cand(relevant, 0.9)])
        svc.set_embedder(FakeEmbedder())

        cards = await svc.recall(user_id="u1", query="mountain hobbies", limit=1)

        assert len(cards) == 1
        assert cards[0].entry_id == relevant
        assert "Pyrenees" in cards[0].content

    @pytest.mark.asyncio
    async def test_semantic_keeps_all_profile_facts(self, svc):
        """B112 regression guard (P2-A): enabling semantic search must NOT drop a
        durable profile fact just because it doesn't match the query. Semantic
        recall is a superset of the recency baseline."""
        await svc.initialize()
        svc._store.upsert_profile(user_id="u1", attribute="city", value="Barcelona")
        hit = svc._store.insert_episodic(user_id="u1", content="I love the Pyrenees")
        svc._vector_index = FakeVectorIndex([_cand(hit, 0.9)])
        svc.set_embedder(FakeEmbedder())

        cards = await svc.recall(user_id="u1", query="totally unrelated query", limit=5)

        # the non-matching profile fact survives, and renders decoded (no quotes)
        assert any(
            c.source_store == "profile" and c.content == "city: Barcelona"
            for c in cards
        )

    @pytest.mark.asyncio
    async def test_semantic_keeps_recent_episodic_during_lag(self, svc):
        """B112 regression guard (P2-B): a just-stored episodic memory that is
        not yet in the vector index must still be recalled (the recency baseline
        is always present), even when the semantic layer returns a different,
        already-indexed hit."""
        await svc.initialize()
        indexed = svc._store.insert_episodic(user_id="u1", content="an indexed memory")
        # newer, NOT yet indexed (vector search won't return it)
        recent_unindexed = svc._store.insert_episodic(
            user_id="u1", content="a brand new unindexed memory"
        )
        svc._vector_index = FakeVectorIndex([_cand(indexed, 0.9)])  # only the indexed one
        svc.set_embedder(FakeEmbedder())

        cards = await svc.recall(user_id="u1", query="memory", limit=5)

        ids = {c.entry_id for c in cards}
        assert recent_unindexed in ids  # recency baseline kept it
        assert indexed in ids  # semantic hit present too

    @pytest.mark.asyncio
    async def test_semantic_empty_falls_back_to_recency(self, svc):
        """When the semantic layer yields nothing (cold start / no match) recall
        falls back to recency so the caller is never stranded."""
        await svc.initialize()
        eid = svc._store.insert_episodic(user_id="u1", content="a recent thing")
        svc._vector_index = FakeVectorIndex([])  # no semantic hits
        svc.set_embedder(FakeEmbedder())

        cards = await svc.recall(user_id="u1", query="anything at all")

        assert any(c.entry_id == eid for c in cards)

    @pytest.mark.asyncio
    async def test_semantic_drops_forgotten_ids(self, svc):
        """A vector hit whose id is gone from SQLite (forgotten / tombstoned) is
        dropped, never returned as a placeholder — no leak of a removed memory."""
        await svc.initialize()
        svc._vector_index = FakeVectorIndex([_cand("ghostid000000000", 0.9)])
        svc.set_embedder(FakeEmbedder())

        cards = await svc.recall(user_id="u1", query="anything")

        assert all(c.entry_id != "ghostid000000000" for c in cards)
        assert all(not c.content.startswith("[episodic:") for c in cards)

    @pytest.mark.asyncio
    async def test_no_embedder_uses_recency(self, svc):
        """Without an injected embedder, recall stays recency-only and never
        consults the vector index (and never triggers a model load)."""
        await svc.initialize()
        eid = svc._store.insert_episodic(user_id="u1", content="hello world")
        # vector index available but NO embedder injected
        svc._vector_index = FakeVectorIndex(
            [_cand("other", 0.9, content="should not appear")]
        )

        cards = await svc.recall(user_id="u1", query="x")

        assert svc._semantic_available() is False
        assert any(c.entry_id == eid for c in cards)
        assert all("should not appear" not in c.content for c in cards)
