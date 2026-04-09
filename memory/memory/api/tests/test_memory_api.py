"""
────────────────────────────────────
Server Nexe
Author: Jordi Goy
Location: memory/memory/api/tests/test_memory_api.py
Description: Tests per memory/memory/api/__init__.py (MemoryAPI).

www.jgoy.net · https://server-nexe.org
────────────────────────────────────
"""

import asyncio
import pytest
from unittest.mock import AsyncMock, MagicMock, patch


def make_mock_api():
    """Crea un MemoryAPI amb Qdrant i embedder mockejats."""
    from memory.memory.api import MemoryAPI
    api = MemoryAPI.__new__(MemoryAPI)
    api._qdrant = MagicMock()
    api._embedder = MagicMock()
    api._executor = MagicMock()
    api._initialized = True
    api._text_store = None
    api._crypto = None
    api.qdrant_url = "http://localhost:6333"
    api.qdrant_path = None
    api.embedding_model = "paraphrase-multilingual-mpnet-base-v2"
    api.vector_size = 768
    return api


# ─── TestMemoryAPIInit ─────────────────────────────────────────────────────────

class TestMemoryAPIInit:

    def test_default_qdrant_url(self, monkeypatch):
        monkeypatch.delenv("NEXE_QDRANT_URL", raising=False)
        monkeypatch.delenv("NEXE_QDRANT_HOST", raising=False)
        monkeypatch.delenv("NEXE_QDRANT_PORT", raising=False)
        from memory.memory.api import MemoryAPI
        api = MemoryAPI()
        assert "localhost" in api.qdrant_url

    def test_custom_qdrant_url(self):
        from memory.memory.api import MemoryAPI
        api = MemoryAPI(qdrant_url="http://custom:9999")
        assert api.qdrant_url == "http://custom:9999"

    def test_qdrant_path_mode(self, tmp_path):
        from memory.memory.api import MemoryAPI
        api = MemoryAPI(qdrant_path=tmp_path)
        assert api.qdrant_path == tmp_path

    def test_not_initialized_by_default(self):
        from memory.memory.api import MemoryAPI
        api = MemoryAPI()
        assert api._initialized is False

    def test_embedding_model_set(self):
        from memory.memory.api import MemoryAPI
        api = MemoryAPI(embedding_model="paraphrase-multilingual-mpnet-base-v2")
        assert api.embedding_model == "paraphrase-multilingual-mpnet-base-v2"


# ─── TestEnsureInitialized ─────────────────────────────────────────────────────

class TestEnsureInitialized:

    def test_raises_when_not_initialized(self):
        from memory.memory.api import MemoryAPI
        api = MemoryAPI()
        with pytest.raises(RuntimeError, match="not initialized"):
            api._ensure_initialized()

    def test_no_error_when_initialized(self):
        api = make_mock_api()
        api._ensure_initialized()  # Should not raise


# ─── TestMemoryAPIClose ────────────────────────────────────────────────────────

class TestMemoryAPIClose:

    def test_close_clears_state(self):
        api = make_mock_api()
        asyncio.run(api.close())
        assert api._qdrant is None
        assert api._embedder is None
        assert api._initialized is False

    def test_close_handles_qdrant_close_error(self):
        api = make_mock_api()
        api._qdrant.close.side_effect = Exception("close failed")
        # Should not raise
        asyncio.run(api.close())
        assert api._qdrant is None


# ─── TestContextManager ───────────────────────────────────────────────────────

class TestContextManager:

    def test_aenter_calls_initialize(self):
        from memory.memory.api import MemoryAPI
        api = MemoryAPI()

        async def run():
            with patch.object(api, "initialize", AsyncMock(return_value=True)) as mock_init, \
                 patch.object(api, "close", AsyncMock()):
                async with api as a:
                    assert a is api
                mock_init.assert_called_once()

        asyncio.run(run())

    def test_aexit_calls_close(self):
        from memory.memory.api import MemoryAPI
        api = MemoryAPI()

        async def run():
            with patch.object(api, "initialize", AsyncMock(return_value=True)), \
                 patch.object(api, "close", AsyncMock()) as mock_close:
                async with api:
                    pass
                mock_close.assert_called_once()

        asyncio.run(run())


# ─── TestCreateCollection ──────────────────────────────────────────────────────

class TestCreateCollection:

    def test_delegates_to_create_collection_op(self):
        api = make_mock_api()

        with patch("memory.memory.api.create_collection", AsyncMock(return_value=True)) as mock_cc:
            result = asyncio.run(api.create_collection("test_col", vector_size=768))

        assert result is True
        mock_cc.assert_called_once_with(api._qdrant, api._executor, "test_col", 768, "cosine")

    def test_raises_if_not_initialized(self):
        from memory.memory.api import MemoryAPI
        api = MemoryAPI()
        with pytest.raises(RuntimeError):
            asyncio.run(api.create_collection("col"))


# ─── TestDeleteCollection ─────────────────────────────────────────────────────

class TestDeleteCollection:

    def test_delegates_to_delete_collection_op(self):
        api = make_mock_api()

        with patch("memory.memory.api.delete_collection", AsyncMock(return_value=True)) as mock_dc:
            result = asyncio.run(api.delete_collection("test_col"))

        assert result is True
        mock_dc.assert_called_once_with(api._qdrant, api._executor, "test_col")


# ─── TestListCollections ──────────────────────────────────────────────────────

class TestListCollections:

    def test_returns_list(self):
        from memory.memory.api.models import CollectionInfo
        api = make_mock_api()
        mock_cols = [CollectionInfo(name="col1", vector_size=768, points_count=0)]

        with patch("memory.memory.api.list_collections", AsyncMock(return_value=mock_cols)):
            result = asyncio.run(api.list_collections())

        assert result == mock_cols


# ─── TestCollectionExists ─────────────────────────────────────────────────────

class TestCollectionExists:

    def test_returns_true_when_exists(self):
        api = make_mock_api()

        with patch("memory.memory.api.collection_exists", AsyncMock(return_value=True)):
            result = asyncio.run(api.collection_exists("test_col"))

        assert result is True

    def test_returns_false_when_not_exists(self):
        api = make_mock_api()

        with patch("memory.memory.api.collection_exists", AsyncMock(return_value=False)):
            result = asyncio.run(api.collection_exists("test_col"))

        assert result is False


# ─── TestStore ────────────────────────────────────────────────────────────────

class TestStore:

    def test_stores_to_existing_collection(self):
        api = make_mock_api()

        with patch("memory.memory.api.collection_exists", AsyncMock(return_value=True)), \
             patch("memory.memory.api.store_document", AsyncMock(return_value="doc-id-xyz")):
            result = asyncio.run(api.store(
                text="Test text",
                collection="test_col",
                metadata={"source": "test"}
            ))

        assert result == "doc-id-xyz"

    def test_raises_collection_not_found(self):
        from memory.memory.api import CollectionNotFoundError
        api = make_mock_api()

        with patch("memory.memory.api.collection_exists", AsyncMock(return_value=False)):
            with pytest.raises(CollectionNotFoundError):
                asyncio.run(api.store("text", "nonexistent_col"))


# ─── TestSearch ───────────────────────────────────────────────────────────────

class TestSearch:

    def test_returns_search_results(self):
        from memory.memory.api.models import SearchResult
        api = make_mock_api()
        mock_results = [SearchResult(id="id1", score=0.9, collection="test_col", text="Result")]

        with patch("memory.memory.api.collection_exists", AsyncMock(return_value=True)), \
             patch("memory.memory.api.search_documents", AsyncMock(return_value=mock_results)):
            results = asyncio.run(api.search("query", "test_col", top_k=3))

        assert len(results) == 1
        assert results[0].text == "Result"

    def test_raises_collection_not_found(self):
        from memory.memory.api import CollectionNotFoundError
        api = make_mock_api()

        with patch("memory.memory.api.collection_exists", AsyncMock(return_value=False)):
            with pytest.raises(CollectionNotFoundError):
                asyncio.run(api.search("query", "nonexistent_col"))


# ─── TestGet ──────────────────────────────────────────────────────────────────

class TestGet:

    def test_returns_document(self):
        from memory.memory.api.models import Document
        api = make_mock_api()
        mock_doc = Document(id="doc1", text="Content", collection="col")

        with patch("memory.memory.api.collection_exists", AsyncMock(return_value=True)), \
             patch("memory.memory.api.get_document", AsyncMock(return_value=mock_doc)):
            result = asyncio.run(api.get("doc1", "test_col"))

        assert result is mock_doc

    def test_raises_collection_not_found(self):
        from memory.memory.api import CollectionNotFoundError
        api = make_mock_api()

        with patch("memory.memory.api.collection_exists", AsyncMock(return_value=False)):
            with pytest.raises(CollectionNotFoundError):
                asyncio.run(api.get("doc1", "nonexistent_col"))


# ─── TestDelete ───────────────────────────────────────────────────────────────

class TestDelete:

    def test_deletes_document(self):
        api = make_mock_api()

        with patch("memory.memory.api.collection_exists", AsyncMock(return_value=True)), \
             patch("memory.memory.api.delete_document", AsyncMock(return_value=True)):
            result = asyncio.run(api.delete("doc1", "test_col"))

        assert result is True

    def test_raises_collection_not_found(self):
        from memory.memory.api import CollectionNotFoundError
        api = make_mock_api()

        with patch("memory.memory.api.collection_exists", AsyncMock(return_value=False)):
            with pytest.raises(CollectionNotFoundError):
                asyncio.run(api.delete("doc1", "nonexistent_col"))


# ─── TestCount ────────────────────────────────────────────────────────────────

class TestCount:

    def test_returns_count(self):
        api = make_mock_api()

        with patch("memory.memory.api.collection_exists", AsyncMock(return_value=True)), \
             patch("memory.memory.api.count_documents", AsyncMock(return_value=42)):
            result = asyncio.run(api.count("test_col"))

        assert result == 42

    def test_raises_collection_not_found(self):
        from memory.memory.api import CollectionNotFoundError
        api = make_mock_api()

        with patch("memory.memory.api.collection_exists", AsyncMock(return_value=False)):
            with pytest.raises(CollectionNotFoundError):
                asyncio.run(api.count("nonexistent_col"))


# ─── TestCleanupExpired ───────────────────────────────────────────────────────

class TestCleanupExpired:

    def test_cleans_up_expired(self):
        api = make_mock_api()

        with patch("memory.memory.api.collection_exists", AsyncMock(return_value=True)), \
             patch("memory.memory.api.cleanup_expired", AsyncMock(return_value=5)):
            result = asyncio.run(api.cleanup_expired("test_col"))

        assert result == 5

    def test_raises_collection_not_found(self):
        from memory.memory.api import CollectionNotFoundError
        api = make_mock_api()

        with patch("memory.memory.api.collection_exists", AsyncMock(return_value=False)):
            with pytest.raises(CollectionNotFoundError):
                asyncio.run(api.cleanup_expired("nonexistent_col"))


# ─── TestCleanupAllExpired ────────────────────────────────────────────────────

class TestCleanupAllExpired:

    def test_cleans_all_collections(self):
        from memory.memory.api.models import CollectionInfo
        api = make_mock_api()

        mock_cols = [
            CollectionInfo(name="col1", vector_size=768, points_count=0),
            CollectionInfo(name="col2", vector_size=768, points_count=0),
        ]

        with patch("memory.memory.api.list_collections", AsyncMock(return_value=mock_cols)), \
             patch.object(api, "cleanup_expired", AsyncMock(side_effect=[3, 0])):
            result = asyncio.run(api.cleanup_all_expired())

        assert result == {"col1": 3}  # col2 had 0, not included

    def test_returns_empty_when_nothing_expired(self):
        from memory.memory.api.models import CollectionInfo
        api = make_mock_api()

        mock_cols = [CollectionInfo(name="col1", vector_size=768, points_count=0)]

        with patch("memory.memory.api.list_collections", AsyncMock(return_value=mock_cols)), \
             patch.object(api, "cleanup_expired", AsyncMock(return_value=0)):
            result = asyncio.run(api.cleanup_all_expired())

        assert result == {}


# ─── TestHexToUuid ────────────────────────────────────────────────────────────

class TestHexToUuid:

    def test_delegates_to_hex_to_uuid(self):
        from memory.memory.api import MemoryAPI
        with patch("memory.memory.api.hex_to_uuid", return_value="uuid-result") as mock:
            result = MemoryAPI._hex_to_uuid("abc123")
        assert result == "uuid-result"
        mock.assert_called_once_with("abc123")


# ─── TestInitialize ─────────────────────────────────────────────────────────

class TestInitialize:

    def test_initialize_already_initialized(self):
        """Lines 115-117: already initialized returns True."""
        api = make_mock_api()
        result = asyncio.run(api.initialize())
        assert result is True

    def test_initialize_qdrant_path_mode(self, tmp_path):
        """Lines 121-123: qdrant path mode initialization."""
        from memory.memory.api import MemoryAPI
        api = MemoryAPI(qdrant_path=tmp_path / "qdrant_init_test")

        with patch.object(api, "_init_embedder", AsyncMock()):
            result = asyncio.run(api.initialize())
        assert result is True
        assert api._initialized is True
        asyncio.run(api.close())

    def test_initialize_url_mode(self):
        """Lines 124-126: URL mode initialization."""
        from memory.memory.api import MemoryAPI
        api = MemoryAPI(qdrant_url="http://localhost:6333")

        mock_client = MagicMock()
        # QdrantClient ja no s'importa a memory.memory.api (TYPE_CHECKING guard).
        # El client real ve de core.qdrant_pool.get_qdrant_client → patxem allà.
        with patch("core.qdrant_pool.get_qdrant_client", return_value=mock_client):
            with patch.object(api, "_init_embedder", AsyncMock()):
                result = asyncio.run(api.initialize())
        assert result is True
        assert api._initialized is True
        asyncio.run(api.close())

    def test_initialize_exception_raises(self):
        """Lines 132-134: exception during init is raised."""
        from memory.memory.api import MemoryAPI
        api = MemoryAPI(qdrant_url="http://localhost:6333")

        with patch("core.qdrant_pool.get_qdrant_client", side_effect=Exception("connection failed")):
            with pytest.raises(Exception, match="connection failed"):
                asyncio.run(api.initialize())

    def test_init_embedder_local_then_remote(self):
        """Lines 136-148: _init_embedder with local_files_only fallback."""
        import sys
        from memory.memory.api import MemoryAPI
        api = MemoryAPI()

        mock_model = MagicMock()
        mock_st_module = MagicMock()
        mock_st_module.SentenceTransformer = MagicMock(return_value=mock_model)

        async def run():
            orig = sys.modules.get("sentence_transformers")
            sys.modules["sentence_transformers"] = mock_st_module
            try:
                await api._init_embedder()
            finally:
                if orig is not None:
                    sys.modules["sentence_transformers"] = orig
                else:
                    sys.modules.pop("sentence_transformers", None)
            assert api._embedder is mock_model

        asyncio.run(run())

    def test_init_embedder_local_fails_downloads(self):
        """Lines 143-145: local_files_only fails, downloads model."""
        import sys
        from memory.memory.api import MemoryAPI
        api = MemoryAPI()

        mock_model = MagicMock()
        call_count = [0]
        def mock_st(*args, **kwargs):
            call_count[0] += 1
            if call_count[0] == 1 and kwargs.get("local_files_only"):
                raise Exception("not found locally")
            return mock_model

        mock_st_module = MagicMock()
        mock_st_module.SentenceTransformer = mock_st

        async def run():
            orig = sys.modules.get("sentence_transformers")
            sys.modules["sentence_transformers"] = mock_st_module
            try:
                await api._init_embedder()
            finally:
                if orig is not None:
                    sys.modules["sentence_transformers"] = orig
                else:
                    sys.modules.pop("sentence_transformers", None)
            assert api._embedder is mock_model

        asyncio.run(run())
