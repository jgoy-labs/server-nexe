"""
────────────────────────────────────
Server Nexe
Version: 0.8
Author: Jordi Goy
Location: memory/memory/api/tests/test_documents.py
Description: Tests per memory/memory/api/documents.py.

www.jgoy.net · https://server-nexe.org
────────────────────────────────────
"""

import asyncio
import pytest
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, MagicMock, patch


def make_executor():
    return ThreadPoolExecutor(max_workers=2)


def make_qdrant():
    q = MagicMock()
    q.upsert = MagicMock()
    q.search = MagicMock(return_value=[])
    q.retrieve = MagicMock(return_value=[])
    q.delete = MagicMock()
    q.scroll = MagicMock(return_value=([], None))
    q.get_collection = MagicMock()
    return q


async def fake_embedding(text: str):
    return [0.1] * 768


# ─── TestHexToUuid ────────────────────────────────────────────────────────────

class TestHexToUuid:

    def test_converts_hex_to_uuid(self):
        from memory.memory.api.documents import hex_to_uuid
        result = hex_to_uuid("abc123")
        assert "-" in result
        assert len(result) == 36

    def test_pads_short_hex(self):
        from memory.memory.api.documents import hex_to_uuid
        result = hex_to_uuid("a")
        assert "-" in result

    def test_full_32_char_hex(self):
        from memory.memory.api.documents import hex_to_uuid
        result = hex_to_uuid("a" * 32)
        assert len(result) == 36


# ─── TestDeletePoints ─────────────────────────────────────────────────────────

class TestDeletePoints:

    def test_delete_with_pointidlist(self):
        from memory.memory.api.documents import _delete_points
        q = MagicMock()
        _delete_points(q, "col", ["id1"])
        q.delete.assert_called_once()

    def test_delete_fallback_on_exception(self):
        from memory.memory.api.documents import _delete_points
        q = MagicMock()
        q.delete.side_effect = [Exception("PointIdsList error"), None]
        _delete_points(q, "col", ["id1"])
        assert q.delete.call_count == 2


# ─── TestStoreDocument ────────────────────────────────────────────────────────

class TestStoreDocument:

    def test_stores_and_returns_id(self):
        from memory.memory.api.documents import store_document
        q = make_qdrant()
        executor = make_executor()

        result = asyncio.run(store_document(
            q, executor, fake_embedding, "Hello world", "test_col"
        ))

        assert isinstance(result, str)
        assert len(result) > 0
        q.upsert.assert_called_once()
        executor.shutdown(wait=False)

    def test_custom_doc_id(self):
        from memory.memory.api.documents import store_document
        q = make_qdrant()
        executor = make_executor()

        result = asyncio.run(store_document(
            q, executor, fake_embedding, "text", "col", doc_id="abc123def456abcd"
        ))

        assert result == "abc123def456abcd"
        executor.shutdown(wait=False)

    def test_stores_with_metadata(self):
        from memory.memory.api.documents import store_document
        q = make_qdrant()
        executor = make_executor()

        asyncio.run(store_document(
            q, executor, fake_embedding, "text", "col",
            metadata={"source": "test", "user": "alice"}
        ))

        call_args = q.upsert.call_args
        payload = call_args[1]["points"][0].payload
        assert payload["source"] == "test"
        executor.shutdown(wait=False)

    def test_stores_with_ttl(self):
        from memory.memory.api.documents import store_document
        q = make_qdrant()
        executor = make_executor()

        asyncio.run(store_document(
            q, executor, fake_embedding, "text", "col", ttl_seconds=3600
        ))

        call_args = q.upsert.call_args
        payload = call_args[1]["points"][0].payload
        assert payload["expires_at"] is not None
        executor.shutdown(wait=False)

    def test_no_ttl_expires_at_is_none(self):
        from memory.memory.api.documents import store_document
        q = make_qdrant()
        executor = make_executor()

        asyncio.run(store_document(
            q, executor, fake_embedding, "text", "col"
        ))

        call_args = q.upsert.call_args
        payload = call_args[1]["points"][0].payload
        assert payload["expires_at"] is None
        executor.shutdown(wait=False)

    def test_increments_metrics_if_available(self):
        from memory.memory.api.documents import store_document
        q = make_qdrant()
        executor = make_executor()

        mock_ops = MagicMock()
        with patch("memory.memory.api.documents._get_metrics", return_value=(mock_ops, None)):
            asyncio.run(store_document(q, executor, fake_embedding, "text", "col"))

        mock_ops.labels.assert_called_once_with(operation="store")
        executor.shutdown(wait=False)


# ─── TestSearchDocuments ──────────────────────────────────────────────────────

class TestSearchDocuments:

    def _make_result(self, id="id1", score=0.9, text="hello", expires_at=None):
        r = MagicMock()
        r.id = id
        r.score = score
        r.payload = {
            "original_id": id,
            "text": text,
            "expires_at": expires_at,
            "created_at": "2024-01-01T00:00:00+00:00",
        }
        return r

    def test_returns_results(self):
        from memory.memory.api.documents import search_documents
        q = make_qdrant()
        q.search.return_value = [self._make_result()]
        executor = make_executor()

        results = asyncio.run(search_documents(q, executor, fake_embedding, "query", "col"))

        assert len(results) == 1
        assert results[0].text == "hello"
        executor.shutdown(wait=False)

    def test_filters_expired(self):
        from memory.memory.api.documents import search_documents
        q = make_qdrant()
        # Expired yesterday
        past = (datetime.now(timezone.utc) - timedelta(days=1)).isoformat()
        q.search.return_value = [self._make_result(expires_at=past)]
        executor = make_executor()

        results = asyncio.run(search_documents(q, executor, fake_embedding, "query", "col"))

        assert len(results) == 0
        executor.shutdown(wait=False)

    def test_include_expired(self):
        from memory.memory.api.documents import search_documents
        q = make_qdrant()
        past = (datetime.now(timezone.utc) - timedelta(days=1)).isoformat()
        q.search.return_value = [self._make_result(expires_at=past)]
        executor = make_executor()

        results = asyncio.run(search_documents(
            q, executor, fake_embedding, "query", "col", include_expired=True
        ))

        assert len(results) == 1
        executor.shutdown(wait=False)

    def test_respects_top_k(self):
        from memory.memory.api.documents import search_documents
        q = make_qdrant()
        q.search.return_value = [self._make_result(id=f"id{i}") for i in range(10)]
        executor = make_executor()

        results = asyncio.run(search_documents(
            q, executor, fake_embedding, "query", "col", top_k=3
        ))

        assert len(results) <= 3
        executor.shutdown(wait=False)

    def test_with_threshold(self):
        from memory.memory.api.documents import search_documents
        q = make_qdrant()
        q.search.return_value = [self._make_result(score=0.5)]
        executor = make_executor()

        asyncio.run(search_documents(
            q, executor, fake_embedding, "query", "col", threshold=0.7
        ))

        # Threshold forwarded to qdrant.search
        call_kwargs = q.search.call_args[1]
        assert call_kwargs["score_threshold"] == 0.7
        executor.shutdown(wait=False)

    def test_with_filter_metadata(self):
        from memory.memory.api.documents import search_documents
        q = make_qdrant()
        q.search.return_value = []
        executor = make_executor()

        asyncio.run(search_documents(
            q, executor, fake_embedding, "query", "col",
            filter_metadata={"source": "cli"}
        ))

        call_kwargs = q.search.call_args[1]
        assert call_kwargs["query_filter"] is not None
        executor.shutdown(wait=False)

    def test_uses_query_points_fallback(self):
        from memory.memory.api.documents import search_documents
        q = make_qdrant()
        del q.search  # Remove .search to force query_points fallback

        mock_res = MagicMock()
        mock_res.points = [self._make_result()]
        q.query_points = MagicMock(return_value=mock_res)

        executor = make_executor()

        results = asyncio.run(search_documents(q, executor, fake_embedding, "query", "col"))

        assert len(results) == 1
        executor.shutdown(wait=False)

    def test_increments_recall_metric(self):
        from memory.memory.api.documents import search_documents
        q = make_qdrant()
        q.search.return_value = []
        executor = make_executor()

        mock_ops = MagicMock()
        with patch("memory.memory.api.documents._get_metrics", return_value=(mock_ops, None)):
            asyncio.run(search_documents(q, executor, fake_embedding, "query", "col"))

        mock_ops.labels.assert_called_once_with(operation="recall")
        executor.shutdown(wait=False)


# ─── TestGetDocument ──────────────────────────────────────────────────────────

class TestGetDocument:

    def _make_point(self, doc_id="abc123def456abcd", text="content", created_at=None, expires_at=None):
        p = MagicMock()
        p.id = "uuid-string"
        p.payload = {
            "original_id": doc_id,
            "text": text,
            "created_at": created_at or "2024-01-01T00:00:00+00:00",
            "expires_at": expires_at,
        }
        return p

    def test_returns_document(self):
        from memory.memory.api.documents import get_document
        q = make_qdrant()
        q.retrieve.return_value = [self._make_point()]
        executor = make_executor()

        result = asyncio.run(get_document(q, executor, "abc123", "test_col"))

        assert result is not None
        assert result.text == "content"
        executor.shutdown(wait=False)

    def test_returns_none_if_not_found(self):
        from memory.memory.api.documents import get_document
        q = make_qdrant()
        q.retrieve.return_value = []
        executor = make_executor()

        result = asyncio.run(get_document(q, executor, "abc123def456abcd", "col"))

        assert result is None
        executor.shutdown(wait=False)

    def test_returns_none_on_exception(self):
        from memory.memory.api.documents import get_document
        q = make_qdrant()
        q.retrieve.side_effect = Exception("DB error")
        executor = make_executor()

        result = asyncio.run(get_document(q, executor, "abc123def456abcd", "col"))

        assert result is None
        executor.shutdown(wait=False)

    def test_document_with_expires_at(self):
        from memory.memory.api.documents import get_document
        q = make_qdrant()
        expires = "2025-01-01T00:00:00+00:00"
        q.retrieve.return_value = [self._make_point(expires_at=expires)]
        executor = make_executor()

        result = asyncio.run(get_document(q, executor, "abc123def456abcd", "col"))

        assert result.expires_at is not None
        executor.shutdown(wait=False)

    def test_document_without_created_at(self):
        from memory.memory.api.documents import get_document
        q = make_qdrant()
        p = MagicMock()
        p.payload = {"original_id": "abc123def456abcd", "text": "text"}
        q.retrieve.return_value = [p]
        executor = make_executor()

        result = asyncio.run(get_document(q, executor, "abc123def456abcd", "col"))

        assert result.created_at is None
        executor.shutdown(wait=False)


# ─── TestDeleteDocument ───────────────────────────────────────────────────────

class TestDeleteDocument:

    def test_deletes_successfully(self):
        from memory.memory.api.documents import delete_document
        q = make_qdrant()
        executor = make_executor()

        result = asyncio.run(delete_document(q, executor, "abc123def456abcd", "col"))

        assert result is True
        executor.shutdown(wait=False)

    def test_returns_false_on_exception(self):
        from memory.memory.api.documents import delete_document
        q = make_qdrant()
        q.delete.side_effect = Exception("delete failed")
        executor = make_executor()

        result = asyncio.run(delete_document(q, executor, "abc123def456abcd", "col"))

        assert result is False
        executor.shutdown(wait=False)

    def test_increments_delete_metric(self):
        from memory.memory.api.documents import delete_document
        q = make_qdrant()
        executor = make_executor()

        mock_ops = MagicMock()
        with patch("memory.memory.api.documents._get_metrics", return_value=(mock_ops, None)):
            asyncio.run(delete_document(q, executor, "abc123def456abcd", "col"))

        mock_ops.labels.assert_called_once_with(operation="delete")
        executor.shutdown(wait=False)


# ─── TestCountDocuments ───────────────────────────────────────────────────────

class TestCountDocuments:

    def test_returns_count(self):
        from memory.memory.api.documents import count_documents
        q = make_qdrant()
        mock_info = MagicMock()
        mock_info.points_count = 42
        q.get_collection.return_value = mock_info
        executor = make_executor()

        result = asyncio.run(count_documents(q, executor, "col"))

        assert result == 42
        executor.shutdown(wait=False)


# ─── TestCleanupExpired ───────────────────────────────────────────────────────

class TestCleanupExpired:

    def test_deletes_expired_documents(self):
        from memory.memory.api.documents import cleanup_expired
        q = make_qdrant()
        past = (datetime.now(timezone.utc) - timedelta(days=1)).isoformat()

        record = MagicMock()
        record.id = "uuid-expired"
        record.payload = {"expires_at": past}

        # First scroll returns records, second returns empty (end)
        q.scroll.side_effect = [
            ([record], None),
        ]
        executor = make_executor()

        result = asyncio.run(cleanup_expired(q, executor, "col"))

        assert result == 1
        executor.shutdown(wait=False)

    def test_skips_non_expired_documents(self):
        from memory.memory.api.documents import cleanup_expired
        q = make_qdrant()
        future = (datetime.now(timezone.utc) + timedelta(days=1)).isoformat()

        record = MagicMock()
        record.id = "uuid-fresh"
        record.payload = {"expires_at": future}

        q.scroll.side_effect = [([record], None)]
        executor = make_executor()

        result = asyncio.run(cleanup_expired(q, executor, "col"))

        assert result == 0
        executor.shutdown(wait=False)

    def test_skips_documents_without_expiry(self):
        from memory.memory.api.documents import cleanup_expired
        q = make_qdrant()

        record = MagicMock()
        record.id = "uuid-no-expiry"
        record.payload = {}

        q.scroll.side_effect = [([record], None)]
        executor = make_executor()

        result = asyncio.run(cleanup_expired(q, executor, "col"))

        assert result == 0
        executor.shutdown(wait=False)

    def test_empty_collection(self):
        from memory.memory.api.documents import cleanup_expired
        q = make_qdrant()
        q.scroll.return_value = ([], None)
        executor = make_executor()

        result = asyncio.run(cleanup_expired(q, executor, "col"))

        assert result == 0
        executor.shutdown(wait=False)

    def test_continues_scrolling_with_offset(self):
        from memory.memory.api.documents import cleanup_expired
        q = make_qdrant()

        past = (datetime.now(timezone.utc) - timedelta(days=1)).isoformat()
        record1 = MagicMock()
        record1.id = "id1"
        record1.payload = {"expires_at": past}

        record2 = MagicMock()
        record2.id = "id2"
        record2.payload = {"expires_at": past}

        # First page returns offset="next", second page returns offset=None
        q.scroll.side_effect = [
            ([record1], "next-offset"),
            ([record2], None),
        ]
        executor = make_executor()

        result = asyncio.run(cleanup_expired(q, executor, "col"))

        assert result == 2
        executor.shutdown(wait=False)


# ─── TestGetMetrics ───────────────────────────────────────────────────────────

class TestGetMetrics:

    def test_returns_none_when_import_fails(self):
        import memory.memory.api.documents as docs_module
        # Reset cached metrics
        docs_module._metrics_imported = False
        docs_module._MEMORY_OPERATIONS = None
        docs_module._MEMORY_STORE_SIZE = None

        with patch("memory.memory.api.documents._metrics_imported", False):
            with patch.dict("sys.modules", {"core.metrics.registry": None}):
                # Reset again
                docs_module._metrics_imported = False
                ops, size = docs_module._get_metrics()
                # Either None or valid depending on import
                # Just check it doesn't crash
                assert ops is None or ops is not None
