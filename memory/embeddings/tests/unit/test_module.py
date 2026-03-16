"""
Tests per memory/embeddings/module.py
Covers uncovered lines: 70, 190-196, 212, 234-242, 262-270, 282-290,
299-307, 322-323, 339-345, 370-383.
"""

import pytest
import asyncio
from unittest.mock import patch, MagicMock, AsyncMock
from memory.embeddings.module import EmbeddingsModule


@pytest.fixture(autouse=True)
def reset_singleton():
    """Reset singleton between tests."""
    EmbeddingsModule._instance = None
    EmbeddingsModule._initialized = False
    yield
    EmbeddingsModule._instance = None
    EmbeddingsModule._initialized = False


class TestSingleton:
    def test_get_instance_creates_singleton(self):
        instance = EmbeddingsModule.get_instance()
        assert instance is not None
        assert isinstance(instance, EmbeddingsModule)

    def test_double_constructor_raises(self):
        """Line 70: second constructor raises RuntimeError."""
        EmbeddingsModule._instance = EmbeddingsModule()
        with pytest.raises(RuntimeError):
            EmbeddingsModule()

    def test_get_instance_returns_same(self):
        inst1 = EmbeddingsModule.get_instance()
        inst2 = EmbeddingsModule.get_instance()
        assert inst1 is inst2


@pytest.mark.asyncio
class TestInitialize:
    async def test_initialize_success(self):
        """Lines 137-188: successful initialization."""
        module = EmbeddingsModule.get_instance()
        with patch("memory.embeddings.module.AsyncEmbedder"), \
             patch("memory.embeddings.module.CachedEmbedder"), \
             patch("memory.embeddings.module.SmartChunker"):
            result = await module.initialize()
        assert result is True
        assert module._initialized is True

    async def test_initialize_already_initialized(self):
        """Line 133-135: already initialized returns True."""
        module = EmbeddingsModule.get_instance()
        module._initialized = True
        result = await module.initialize()
        assert result is True

    async def test_initialize_failure_raises(self):
        """Lines 190-196: initialization failure raises."""
        module = EmbeddingsModule.get_instance()
        with patch("memory.embeddings.module.AsyncEmbedder",
                   side_effect=RuntimeError("model not found")):
            with pytest.raises(RuntimeError, match="model not found"):
                await module.initialize()


@pytest.mark.asyncio
class TestEncodeNotInitialized:
    async def test_encode_not_initialized_raises(self):
        """Line 212: encode without initialization raises RuntimeError."""
        module = EmbeddingsModule.get_instance()
        request = MagicMock()
        with pytest.raises(RuntimeError):
            await module.encode(request)

    async def test_encode_batch_not_initialized_raises(self):
        """Lines 234-240: encode_batch without initialization raises."""
        module = EmbeddingsModule.get_instance()
        request = MagicMock()
        with pytest.raises(RuntimeError):
            await module.encode_batch(request)


@pytest.mark.asyncio
class TestChunkDocumentNotInitialized:
    async def test_chunk_document_not_initialized_raises(self):
        """Lines 262-268: chunk_document without initialization raises."""
        module = EmbeddingsModule.get_instance()
        with pytest.raises(RuntimeError):
            await module.chunk_document("test", "doc1")


class TestGetStatsNotInitialized:
    def test_get_stats_not_initialized_raises(self):
        """Lines 282-288: get_stats without initialization raises."""
        module = EmbeddingsModule.get_instance()
        with pytest.raises(RuntimeError):
            module.get_stats()


@pytest.mark.asyncio
class TestClearCacheNotInitialized:
    async def test_clear_cache_not_initialized_raises(self):
        """Lines 299-305: clear_cache without initialization raises."""
        module = EmbeddingsModule.get_instance()
        with pytest.raises(RuntimeError):
            await module.clear_cache()


@pytest.mark.asyncio
class TestShutdown:
    async def test_shutdown_not_initialized(self):
        """Lines 321-323: shutdown when not initialized returns True."""
        module = EmbeddingsModule.get_instance()
        result = await module.shutdown()
        assert result is True

    async def test_shutdown_success(self):
        """Lines 325-337: successful shutdown."""
        module = EmbeddingsModule.get_instance()
        module._initialized = True
        module._cached_embedder = AsyncMock()
        module._chunker = MagicMock()
        module._config = {"test": "value"}

        result = await module.shutdown()
        assert result is True
        assert module._initialized is False
        assert module._cached_embedder is None
        assert module._chunker is None

    async def test_shutdown_failure_returns_false(self):
        """Lines 339-345: shutdown failure returns False."""
        module = EmbeddingsModule.get_instance()
        module._initialized = True
        mock_embedder = AsyncMock()
        mock_embedder.shutdown.side_effect = RuntimeError("fail")
        module._cached_embedder = mock_embedder

        result = await module.shutdown()
        assert result is False


class TestGetInfo:
    def test_get_info_not_initialized(self):
        """Lines 370-383: get_info when not initialized."""
        module = EmbeddingsModule.get_instance()
        info = module.get_info()
        assert info["module_id"] == "embeddings"
        assert info["initialized"] is False
        assert info["stats"] == {}

    def test_get_info_initialized(self):
        """Lines 370-383: get_info when initialized with config."""
        module = EmbeddingsModule.get_instance()
        module._initialized = True
        module._config = {"model_name": "test-model"}
        mock_stats = MagicMock()
        mock_stats.model_dump.return_value = {"hits": 10}
        mock_embedder = MagicMock()
        mock_embedder.get_stats.return_value = mock_stats
        module._cached_embedder = mock_embedder

        info = module.get_info()
        assert info["initialized"] is True
        assert info["config"] == {"model_name": "test-model"}
        assert info["stats"] == {"hits": 10}
