"""Tests for memory/memory/api/text_store.py — coverage gaps."""
import pytest
from pathlib import Path


class TestTextStore:
    @pytest.fixture
    def store(self, tmp_path):
        from memory.memory.api.text_store import TextStore
        db = tmp_path / "test_text.db"
        return TextStore(db_path=db)

    def test_put_and_get(self, store):
        store.put("doc1", "coll1", "Hello world", metadata={"source": "test"})
        result = store.get("doc1", "coll1")
        assert result is not None
        assert result["text"] == "Hello world"
        assert result["metadata"]["source"] == "test"

    def test_get_nonexistent(self, store):
        result = store.get("nonexistent", "coll1")
        assert result is None

    def test_put_replaces(self, store):
        store.put("doc1", "coll1", "Version 1")
        store.put("doc1", "coll1", "Version 2")
        result = store.get("doc1", "coll1")
        assert result["text"] == "Version 2"

    def test_get_many(self, store):
        store.put("a", "c", "Text A")
        store.put("b", "c", "Text B")
        store.put("x", "c", "Text X")
        results = store.get_many(["a", "b"], "c")
        assert len(results) == 2
        assert results["a"]["text"] == "Text A"
        assert results["b"]["text"] == "Text B"

    def test_get_many_empty(self, store):
        results = store.get_many([], "c")
        assert results == {}

    def test_delete(self, store):
        store.put("doc1", "coll1", "To delete")
        assert store.delete("doc1", "coll1") is True
        assert store.get("doc1", "coll1") is None

    def test_delete_nonexistent(self, store):
        assert store.delete("nonexistent", "coll1") is False

    def test_delete_collection(self, store):
        store.put("a", "coll1", "A")
        store.put("b", "coll1", "B")
        store.put("c", "coll2", "C")
        deleted = store.delete_collection("coll1")
        assert deleted == 2
        assert store.get("a", "coll1") is None
        assert store.get("c", "coll2") is not None

    def test_close_noop(self, store):
        store.close()

    def test_put_without_metadata(self, store):
        store.put("doc1", "coll1", "No meta")
        result = store.get("doc1", "coll1")
        assert result["metadata"] == {}

    def test_put_with_timestamps(self, store):
        store.put("doc1", "coll1", "Timed", created_at="2026-01-01", expires_at="2027-01-01")
        result = store.get("doc1", "coll1")
        assert result["created_at"] == "2026-01-01"
        assert result["expires_at"] == "2027-01-01"
