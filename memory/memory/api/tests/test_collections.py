"""
────────────────────────────────────
Server Nexe
Version: 0.8
Author: Jordi Goy
Location: memory/memory/api/tests/test_collections.py
Description: Tests per memory/memory/api/collections.py.

www.jgoy.net · https://server-nexe.org
────────────────────────────────────
"""

import asyncio
import pytest
from concurrent.futures import ThreadPoolExecutor
from unittest.mock import MagicMock


def make_executor():
    return ThreadPoolExecutor(max_workers=2)


def make_qdrant(collection_names=None):
    q = MagicMock()
    cols = []
    for name in (collection_names or []):
        c = MagicMock()
        c.name = name
        cols.append(c)
    mock_collections = MagicMock()
    mock_collections.collections = cols
    q.get_collections.return_value = mock_collections
    q.create_collection = MagicMock()
    q.delete_collection = MagicMock()

    # Default get_collection info
    mock_info = MagicMock()
    mock_info.config.params.vectors.size = 384
    mock_info.points_count = 0
    q.get_collection.return_value = mock_info

    return q


# ─── TestCreateCollection ─────────────────────────────────────────────────────

class TestCreateCollection:

    def test_creates_new_collection(self):
        from memory.memory.api.collections import create_collection
        q = make_qdrant()
        executor = make_executor()

        result = asyncio.run(create_collection(q, executor, "nexe_test"))

        assert result is True
        q.create_collection.assert_called_once()
        executor.shutdown(wait=False)

    def test_returns_false_if_exists(self):
        from memory.memory.api.collections import create_collection
        q = make_qdrant(collection_names=["nexe_test"])
        executor = make_executor()

        result = asyncio.run(create_collection(q, executor, "nexe_test"))

        assert result is False
        q.create_collection.assert_not_called()
        executor.shutdown(wait=False)

    def test_uses_vector_size(self):
        from memory.memory.api.collections import create_collection
        q = make_qdrant()
        executor = make_executor()

        asyncio.run(create_collection(q, executor, "nexe_test", vector_size=768))

        call_kwargs = q.create_collection.call_args[1]
        assert call_kwargs["vectors_config"].size == 768
        executor.shutdown(wait=False)

    def test_invalid_name_raises(self):
        from memory.memory.api.collections import create_collection
        from memory.memory.api.models import InvalidCollectionNameError
        q = make_qdrant()
        executor = make_executor()

        with pytest.raises(InvalidCollectionNameError):
            asyncio.run(create_collection(q, executor, "invalid-name!"))
        executor.shutdown(wait=False)

    def test_cosine_distance(self):
        from memory.memory.api.collections import create_collection
        from qdrant_client.models import Distance
        q = make_qdrant()
        executor = make_executor()

        asyncio.run(create_collection(q, executor, "nexe_test", distance="cosine"))

        call_kwargs = q.create_collection.call_args[1]
        assert call_kwargs["vectors_config"].distance == Distance.COSINE
        executor.shutdown(wait=False)

    def test_euclid_distance(self):
        from memory.memory.api.collections import create_collection
        from qdrant_client.models import Distance
        q = make_qdrant()
        executor = make_executor()

        asyncio.run(create_collection(q, executor, "nexe_test", distance="euclid"))

        call_kwargs = q.create_collection.call_args[1]
        assert call_kwargs["vectors_config"].distance == Distance.EUCLID
        executor.shutdown(wait=False)

    def test_dot_distance(self):
        from memory.memory.api.collections import create_collection
        from qdrant_client.models import Distance
        q = make_qdrant()
        executor = make_executor()

        asyncio.run(create_collection(q, executor, "nexe_test", distance="dot"))

        call_kwargs = q.create_collection.call_args[1]
        assert call_kwargs["vectors_config"].distance == Distance.DOT
        executor.shutdown(wait=False)


# ─── TestDeleteCollection ─────────────────────────────────────────────────────

class TestDeleteCollection:

    def test_deletes_existing(self):
        from memory.memory.api.collections import delete_collection
        q = make_qdrant(collection_names=["nexe_test"])
        executor = make_executor()

        result = asyncio.run(delete_collection(q, executor, "nexe_test"))

        assert result is True
        q.delete_collection.assert_called_once()
        executor.shutdown(wait=False)

    def test_returns_false_if_not_exists(self):
        from memory.memory.api.collections import delete_collection
        q = make_qdrant()
        executor = make_executor()

        result = asyncio.run(delete_collection(q, executor, "nonexistent"))

        assert result is False
        q.delete_collection.assert_not_called()
        executor.shutdown(wait=False)


# ─── TestListCollections ──────────────────────────────────────────────────────

class TestListCollections:

    def test_returns_collection_infos(self):
        from memory.memory.api.collections import list_collections
        q = make_qdrant(collection_names=["col1", "col2"])
        executor = make_executor()

        results = asyncio.run(list_collections(q, executor))

        assert len(results) == 2
        names = [r.name for r in results]
        assert "col1" in names
        assert "col2" in names
        executor.shutdown(wait=False)

    def test_empty_collections(self):
        from memory.memory.api.collections import list_collections
        q = make_qdrant()
        executor = make_executor()

        results = asyncio.run(list_collections(q, executor))

        assert results == []
        executor.shutdown(wait=False)


# ─── TestCollectionExists ─────────────────────────────────────────────────────

class TestCollectionExists:

    def test_returns_true_when_exists(self):
        from memory.memory.api.collections import collection_exists
        q = make_qdrant(collection_names=["my_col"])
        executor = make_executor()

        result = asyncio.run(collection_exists(q, executor, "my_col"))

        assert result is True
        executor.shutdown(wait=False)

    def test_returns_false_when_not_exists(self):
        from memory.memory.api.collections import collection_exists
        q = make_qdrant()
        executor = make_executor()

        result = asyncio.run(collection_exists(q, executor, "missing"))

        assert result is False
        executor.shutdown(wait=False)
