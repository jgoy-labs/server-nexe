"""
────────────────────────────────────
Server Nexe
Author: Jordi Goy
Location: tests/memory/memory/test_recall_semantic_real.py
Description: B112 — REAL end-to-end test of MemoryService.recall() semantic mode.
    No fakes: real SimpleEmbedder + real Qdrant VectorIndex + real SQLite
    hydration. Proves recall() ranks a semantically-relevant memory above
    unrelated (and newer) ones, with real content hydrated from SQLite.
    Skips cleanly when the fastembed model is not cached.

www.jgoy.net · https://server-nexe.org
────────────────────────────────────
"""

import os
from datetime import datetime, timezone
from pathlib import Path

import pytest

from memory.memory.memory_service import MemoryService


# ── skip guard: only run when the embedding model is already cached ──────────
_FASTEMBED_CACHE = os.environ.get(
    "FASTEMBED_CACHE_PATH", os.path.expanduser("~/.cache/fastembed")
)


def _fastembed_available() -> bool:
    cache = Path(_FASTEMBED_CACHE)
    if not cache.exists():
        return False
    for pattern in (
        "models--xenova--paraphrase-multilingual*",
        "paraphrase-multilingual*",
        "sentence-transformers--paraphrase-multilingual*",
    ):
        if list(cache.glob(pattern)):
            return True
    return False


pytestmark = pytest.mark.skipif(
    not _fastembed_available(),
    reason="fastembed model not in cache — run the installer or set FASTEMBED_CACHE_PATH",
)


def _index_episodic(svc, embedder, rows):
    """Index already-inserted episodic rows into the REAL vector index, the same
    way DreamingCycle does (entry dicts + encode_batch + VectorIndex.index)."""
    now = datetime.now(timezone.utc).isoformat()
    entries = [
        {
            "id": eid,
            "user_id": "u1",
            "namespace": "default",
            "memory_type": "fact",
            "state": "active",
            "importance": 0.5,
            "trust_level": "untrusted",
            "created_at": now,
        }
        for (eid, _content) in rows
    ]
    embeddings = embedder.encode_batch([content for (_eid, content) in rows])
    return svc._vector_index.index(entries, embeddings)


class TestRecallSemanticReal:

    @pytest.mark.asyncio
    async def test_semantic_ranks_relevant_above_recent_real(self, tmp_path):
        from memory.embeddings.constants import DEFAULT_EMBEDDING_MODEL
        from memory.embeddings.simple_embedder import get_embedder

        embedder = get_embedder(DEFAULT_EMBEDDING_MODEL)
        qdir = tmp_path / "vectors"
        qdir.mkdir(parents=True, exist_ok=True)
        svc = MemoryService(db_path=tmp_path / "m.db", qdrant_path=str(qdir))
        await svc.initialize()
        assert svc.vector_index_available, "real Qdrant index must open for this test"

        # Insert real episodic memories. The relevant one is inserted FIRST
        # (oldest) so recency alone would NOT surface it — only true semantic
        # matching can put it on top.
        relevant = svc._store.insert_episodic(
            "u1", "M'encanta escalar muntanyes altes als Pirineus el cap de setmana"
        )
        groceries = svc._store.insert_episodic(
            "u1", "Avui he comprat llet, ous i pa al supermercat del barri"
        )
        bills = svc._store.insert_episodic(
            "u1", "La factura de la llum d'aquest mes venç divendres que ve"
        )
        rows = [
            (relevant, "M'encanta escalar muntanyes altes als Pirineus el cap de setmana"),
            (groceries, "Avui he comprat llet, ous i pa al supermercat del barri"),
            (bills, "La factura de la llum d'aquest mes venç divendres que ve"),
        ]
        indexed = _index_episodic(svc, embedder, rows)
        assert indexed == 3

        svc.set_embedder(embedder)
        assert svc._semantic_available() is True

        cards = await svc.recall(
            user_id="u1", query="afició a fer alpinisme i pujar cims", limit=3
        )

        # Real semantic ranking: the mountaineering memory must be FIRST, with
        # its real content hydrated from SQLite (not a placeholder), and ranked
        # above the newer, unrelated groceries/bills entries.
        assert cards, "semantic recall returned nothing for a clearly relevant query"
        assert cards[0].entry_id == relevant
        assert "Pirineus" in cards[0].content
        assert not cards[0].content.startswith("[episodic:")
        assert cards[0].entry_id not in {groceries, bills} or cards[0].entry_id == relevant

    @pytest.mark.asyncio
    async def test_irrelevant_query_does_not_rank_unrelated_first_real(self, tmp_path):
        """A query about a DIFFERENT topic should surface the topically-closest
        memory, proving the query genuinely drives the result with real vectors."""
        from memory.embeddings.constants import DEFAULT_EMBEDDING_MODEL
        from memory.embeddings.simple_embedder import get_embedder

        embedder = get_embedder(DEFAULT_EMBEDDING_MODEL)
        qdir = tmp_path / "vectors"
        qdir.mkdir(parents=True, exist_ok=True)
        svc = MemoryService(db_path=tmp_path / "m.db", qdrant_path=str(qdir))
        await svc.initialize()
        assert svc.vector_index_available

        mountains = svc._store.insert_episodic(
            "u1", "M'encanta escalar muntanyes altes als Pirineus el cap de setmana"
        )
        groceries = svc._store.insert_episodic(
            "u1", "Avui he comprat llet, ous i pa al supermercat del barri"
        )
        rows = [
            (mountains, "M'encanta escalar muntanyes altes als Pirineus el cap de setmana"),
            (groceries, "Avui he comprat llet, ous i pa al supermercat del barri"),
        ]
        _index_episodic(svc, embedder, rows)
        svc.set_embedder(embedder)

        cards = await svc.recall(
            user_id="u1", query="què he comprat per menjar al súper", limit=2
        )

        assert cards
        assert cards[0].entry_id == groceries
        assert "supermercat" in cards[0].content
