"""
────────────────────────────────────
Server Nexe
Author: Jordi Goy
Location: tests/memory/memory/storage/test_vector_index_point_ids.py
Description: MC-079 — episodic ids (str(uuid4())[:16]) are NOT valid Qdrant
    point ids, so every vector sync failed silently and episodic memory was
    never indexed. These tests use a REAL embedded Qdrant (a MagicMock is
    exactly what masked the bug) to prove the id mapping round-trips.

www.jgoy.net · https://server-nexe.org
────────────────────────────────────
"""
import uuid

import pytest

from memory.memory.storage.vector_index import VectorIndex, _to_point_id, VECTOR_SIZE


class TestToPointId:
    def test_episodic_shaped_id_becomes_valid_uuid(self):
        # The exact shape produced by insert_episodic: str(uuid4())[:16].
        raw = str(uuid.uuid4())[:16]
        point_id = _to_point_id(raw)
        uuid.UUID(point_id)  # must not raise

    def test_mapping_is_deterministic(self):
        raw = "a1b2c3d4-e5f6-78"
        assert _to_point_id(raw) == _to_point_id(raw)

    def test_full_uuid_passes_through(self):
        raw = str(uuid.uuid4())
        assert _to_point_id(raw) == raw

    def test_arbitrary_string_maps_to_valid_uuid(self):
        point_id = _to_point_id("not-hex-at-all-™-id-123456789")
        uuid.UUID(point_id)

    def test_distinct_ids_do_not_collide(self):
        a = _to_point_id(str(uuid.uuid4())[:16])
        b = _to_point_id(str(uuid.uuid4())[:16])
        assert a != b


@pytest.fixture
def vindex(tmp_path):
    vi = VectorIndex(qdrant_path=str(tmp_path / "vectors"))
    if not vi.available:
        pytest.skip("embedded Qdrant unavailable in this environment")
    yield vi
    vi.close()


def _entry(raw_id, user_id="u1"):
    return {
        "id": raw_id,
        "rdbms_id": raw_id,
        "user_id": user_id,
        "namespace": "default",
        "memory_type": "fact",
        "state": "active",
        "importance": 0.7,
        "trust_level": "untrusted",
        "created_at": "2026-06-11T00:00:00Z",
    }


class TestRealQdrantRoundTrip:
    """Real embedded Qdrant — the sync that used to fail must now work."""

    def test_episodic_id_indexes_searches_and_deletes(self, vindex):
        raw_id = str(uuid.uuid4())[:16]  # the failing shape
        vector = [0.1] * VECTOR_SIZE

        indexed = vindex.index([_entry(raw_id)], [vector])
        assert indexed == 1
        assert vindex.count() == 1

        results = vindex.search(embedding=vector, user_id="u1", threshold=0.5)
        assert len(results) == 1
        # Consumers work with SQLite ids: search must return the original id.
        assert results[0]["id"] == raw_id
        assert results[0]["payload"]["rdbms_id"] == raw_id

        deleted = vindex.delete([raw_id])
        assert deleted >= 0  # adapter returns count or status; the proof is below
        assert vindex.count() == 0

    def test_reindex_same_id_upserts_not_duplicates(self, vindex):
        raw_id = str(uuid.uuid4())[:16]
        vector = [0.2] * VECTOR_SIZE
        vindex.index([_entry(raw_id)], [vector])
        vindex.index([_entry(raw_id)], [vector])
        assert vindex.count() == 1
