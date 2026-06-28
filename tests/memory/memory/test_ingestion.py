"""
────────────────────────────────────
Server Nexe
Author: Jordi Goy 
Location: memory/memory/tests/test_ingestion.py
Description: No description available.

www.jgoy.net · https://server-nexe.org
────────────────────────────────────
"""

import pytest
import asyncio
import tempfile
import shutil
from pathlib import Path

from memory.memory.pipeline.ingestion import IngestionPipeline
from memory.memory.engines.flash_memory import FlashMemory
from memory.memory.engines.persistence import PersistenceManager
from memory.memory.models.memory_entry import MemoryEntry
from memory.memory.models.memory_types import MemoryType
from memory.embeddings.paths import default_fastembed_cache_dir

_FASTEMBED_BARE_MODEL = "paraphrase-multilingual-mpnet-base-v2"


def _resolve_cached_fastembed_model(bare_name: str):
    """Return a fastembed-supported model id equivalent to ``bare_name`` that is
    already cached locally, or None when the real embedding path can't run offline.

    fastembed 0.8+ only accepts fully-qualified ids, so the bare slug is resolved
    against ``list_supported_models()``; the fastembed cache is then checked so the
    test never triggers a network download. Used to gate the real (non-test)
    embedding path with ``pytest.mark.skipif``.
    """
    try:
        from fastembed import TextEmbedding
    except ImportError:
        return None
    try:
        supported = {m["model"] for m in TextEmbedding.list_supported_models()}
    except Exception:
        return None

    slug = bare_name.rsplit("/", 1)[-1].lower()
    if bare_name in supported:
        resolved = bare_name
    else:
        resolved = next(
            (c for c in supported if c.rsplit("/", 1)[-1].lower() == slug),
            None,
        )
    if resolved is None:
        return None

    cache_dir = default_fastembed_cache_dir()
    if not cache_dir.is_dir():
        return None
    has_cache = any(
        p.is_dir() and p.name.lower().endswith(slug)
        for p in cache_dir.iterdir()
    )
    return resolved if has_cache else None


_RESOLVED_FASTEMBED_MODEL = _resolve_cached_fastembed_model(_FASTEMBED_BARE_MODEL)

@pytest.fixture
async def temp_pipeline():
  """Fixture: IngestionPipeline with temporary components"""
  flash = FlashMemory(default_ttl_seconds=1800)

  temp_dir = Path(tempfile.mkdtemp())
  db_path = temp_dir / "test_memory.db"
  qdrant_path = temp_dir / "test_qdrant"

  persistence = PersistenceManager(
    db_path=db_path,
    qdrant_path=qdrant_path,
    collection_name="test_collection",
    vector_size=768  # paraphrase-multilingual-mpnet-base-v2 produces 768-dim vectors
  )

  pipeline = IngestionPipeline(
    flash_memory=flash,
    persistence=persistence,
    embedding_model="paraphrase-multilingual-mpnet-base-v2"
  )

  yield pipeline

  pipeline.close()
  persistence.close()
  shutil.rmtree(temp_dir, ignore_errors=True)

@pytest.mark.asyncio
class TestIngestionPipeline:
  """Tests for IngestionPipeline"""

  async def test_initialization(self, temp_pipeline):
    """Initialisation with flash + persistence"""
    pipeline = temp_pipeline

    assert pipeline.flash is not None
    assert pipeline.persistence is not None
    assert pipeline.embedding_model == "paraphrase-multilingual-mpnet-base-v2"
    assert pipeline.deduplicator is not None
    assert pipeline.stats["total_ingested"] == 0

  async def test_ingest_single_entry(self, temp_pipeline):
    """Ingest a single entry"""
    pipeline = temp_pipeline

    entry = MemoryEntry(
      entry_type=MemoryType.EPISODIC,
      content="Test content",
      source="test"
    )

    result = await pipeline.ingest(entry)

    assert result is True
    assert pipeline.stats["total_ingested"] == 1
    assert pipeline.stats["duplicates_skipped"] == 0

    flash_entry = await pipeline.flash.get(entry.id)
    assert flash_entry is not None

    persist_entry = await pipeline.persistence.get(entry.id)
    assert persist_entry is not None

  async def test_deduplication(self, temp_pipeline):
    """Deduplication: same content is not ingested twice"""
    pipeline = temp_pipeline

    entry1 = MemoryEntry(
      entry_type=MemoryType.EPISODIC,
      content="Duplicate content",
      source="test"
    )

    result1 = await pipeline.ingest(entry1)
    assert result1 is True

    entry2 = MemoryEntry(
      entry_type=MemoryType.EPISODIC,
      content="Duplicate content",
      source="test"
    )
    result2 = await pipeline.ingest(entry2)
    assert result2 is False

    assert pipeline.stats["total_ingested"] == 1
    assert pipeline.stats["duplicates_skipped"] == 1

  async def test_embedding_generation(self, temp_pipeline):
    """Embedding generation returns dummy vector"""
    pipeline = temp_pipeline

    text = "Test text for embedding"
    embedding = await pipeline._generate_embedding(text)

    assert isinstance(embedding, list)
    assert len(embedding) == 768
    assert all(isinstance(x, float) for x in embedding)

  async def test_embedding_deterministic(self, temp_pipeline):
    """Embeddings are deterministic (same text = same vector)"""
    pipeline = temp_pipeline

    text = "Same text"
    embedding1 = await pipeline._generate_embedding(text)
    embedding2 = await pipeline._generate_embedding(text)

    assert embedding1 == embedding2

  async def test_ingest_batch(self, temp_pipeline):
    """Ingest batch of multiple entries"""
    pipeline = temp_pipeline

    entries = [
      MemoryEntry(
        entry_type=MemoryType.EPISODIC,
        content=f"Entry {i}",
        source="batch"
      )
      for i in range(5)
    ]

    batch_stats = await pipeline.ingest_batch(entries)

    assert batch_stats["success"] == 5
    assert batch_stats["duplicates"] == 0
    assert batch_stats["failures"] == 0

    assert pipeline.stats["total_ingested"] == 5

  async def test_ingest_batch_with_duplicates(self, temp_pipeline):
    """Batch with duplicates (same content)"""
    pipeline = temp_pipeline

    entries = [
      MemoryEntry(entry_type=MemoryType.EPISODIC, content="Same", source="test"),
      MemoryEntry(entry_type=MemoryType.EPISODIC, content="Same", source="test"),
      MemoryEntry(entry_type=MemoryType.EPISODIC, content="Different", source="test"),
    ]

    batch_stats = await pipeline.ingest_batch(entries)

    assert batch_stats["success"] == 2
    assert batch_stats["duplicates"] == 1

  async def test_cleanup_expired(self, temp_pipeline):
    """Cleanup of expired entries"""
    pipeline = temp_pipeline

    deleted = await pipeline.cleanup_expired()

    assert deleted == 0

  async def test_get_stats(self, temp_pipeline):
    """Get pipeline statistics"""
    pipeline = temp_pipeline

    for i in range(3):
      entry = MemoryEntry(
        entry_type=MemoryType.EPISODIC,
        content=f"Entry {i}",
        source="test"
      )
      await pipeline.ingest(entry)

    stats = pipeline.get_stats()

    assert stats["total_ingested"] == 3
    assert stats["duplicates_skipped"] == 0
    assert stats["failures"] == 0
    assert "deduplicator" in stats

  async def test_concurrent_ingestion(self, temp_pipeline):
    """Concurrent ingestion with asyncio.gather"""
    pipeline = temp_pipeline

    async def ingest_one(n):
      entry = MemoryEntry(
        entry_type=MemoryType.EPISODIC,
        content=f"Concurrent {n}",
        source="concurrent"
      )
      return await pipeline.ingest(entry)

    results = await asyncio.gather(*[ingest_one(i) for i in range(10)])

    success_count = sum(1 for r in results if r)
    assert success_count >= 8
    assert pipeline.stats["total_ingested"] >= 8

  async def test_pipeline_close(self, temp_pipeline):
    """Close pipeline (shutdown executor)"""
    pipeline = temp_pipeline

    pipeline.close()


@pytest.mark.asyncio
class TestIngestionAdditional:
    """Additional tests for uncovered lines in ingestion.py."""

    async def test_generate_embedding_ollama_empty_text(self, temp_pipeline):
        """Line 177: empty text raises ValueError."""
        pipeline = temp_pipeline
        pipeline.embedding_model = None  # use Ollama path

        with pytest.raises(ValueError, match="buit"):
            await pipeline._generate_embedding_ollama("   ")

    async def test_generate_embedding_ollama_success(self, temp_pipeline):
        """Lines 174-196: successful Ollama embedding."""
        from unittest.mock import patch, AsyncMock, MagicMock

        pipeline = temp_pipeline
        pipeline.embedding_model = None

        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {"embedding": [0.1] * 768}

        mock_client = AsyncMock()
        mock_client.post = AsyncMock(return_value=mock_response)
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)

        with patch("httpx.AsyncClient", return_value=mock_client):
            result = await pipeline._generate_embedding_ollama("test text")
            assert len(result) == 768

    async def test_generate_embedding_ollama_missing_embedding(self, temp_pipeline):
        """Lines 197-198: Ollama returns 200 but no embedding field."""
        from unittest.mock import patch, AsyncMock, MagicMock

        pipeline = temp_pipeline
        pipeline.embedding_model = None

        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {"no_embedding": True}

        mock_client = AsyncMock()
        mock_client.post = AsyncMock(return_value=mock_response)
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)

        with patch("httpx.AsyncClient", return_value=mock_client):
            with pytest.raises(ValueError, match="missing 'embedding'"):
                await pipeline._generate_embedding_ollama("test text")

    async def test_generate_embedding_ollama_error_status(self, temp_pipeline):
        """Lines 199-200: Ollama returns non-200."""
        from unittest.mock import patch, AsyncMock, MagicMock

        pipeline = temp_pipeline
        pipeline.embedding_model = None

        mock_response = MagicMock()
        mock_response.status_code = 500
        mock_response.text = "Internal Server Error"

        mock_client = AsyncMock()
        mock_client.post = AsyncMock(return_value=mock_response)
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)

        with patch("httpx.AsyncClient", return_value=mock_client):
            with pytest.raises(ValueError, match="Ollama error 500"):
                await pipeline._generate_embedding_ollama("test text")

    async def test_generate_embedding_ollama_timeout(self, temp_pipeline):
        """Lines 202-204: Ollama timeout."""
        from unittest.mock import patch, AsyncMock
        import httpx

        pipeline = temp_pipeline
        pipeline.embedding_model = None

        mock_client = AsyncMock()
        mock_client.post = AsyncMock(side_effect=httpx.TimeoutException("timeout"))
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)

        with patch("httpx.AsyncClient", return_value=mock_client):
            with pytest.raises(ValueError, match="timeout"):
                await pipeline._generate_embedding_ollama("test text")

    async def test_generate_embedding_ollama_generic_error(self, temp_pipeline):
        """Lines 205-207: generic error in Ollama path."""
        from unittest.mock import patch, AsyncMock

        pipeline = temp_pipeline
        pipeline.embedding_model = None

        mock_client = AsyncMock()
        mock_client.post = AsyncMock(side_effect=ConnectionError("connection refused"))
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)

        with patch("httpx.AsyncClient", return_value=mock_client):
            with pytest.raises(ConnectionError):
                await pipeline._generate_embedding_ollama("test text")

    async def test_generate_embedding_sync_test_mode(self, temp_pipeline):
        """Lines 224-225, 227-247: _generate_embedding_sync in test mode."""
        pipeline = temp_pipeline
        result = pipeline._generate_embedding_sync("test text")
        assert isinstance(result, list)
        assert len(result) == 768

    async def test_generate_embedding_sync_empty_text(self, temp_pipeline):
        """Lines 230-231: empty text raises ValueError (test mode)."""
        pipeline = temp_pipeline
        with pytest.raises(ValueError, match="buit"):
            pipeline._generate_test_embedding("   ")

    async def test_generate_embedding_via_executor(self, temp_pipeline):
        """Lines 149-156: _generate_embedding with embedding_model set uses executor."""
        pipeline = temp_pipeline
        assert pipeline.embedding_model is not None
        result = await pipeline._generate_embedding("test text for executor")
        assert isinstance(result, list)
        assert len(result) == 768


@pytest.mark.asyncio
class TestIngestionRealFastembed:
    """Real fastembed embedding path (no Ollama, no test-mode shortcut)."""

    @pytest.mark.skipif(
        _RESOLVED_FASTEMBED_MODEL is None,
        reason="fastembed model not cached locally; real embedding path skipped",
    )
    async def test_generate_embedding_sync_real_model(self, temp_pipeline, monkeypatch):
        """Lines 237-263: with the test-mode env vars removed (delenv),
        _generate_embedding_sync must load the real fastembed ONNX model and
        return a normalised 768-dim vector instead of the test shortcut."""
        import math

        monkeypatch.delenv("PYTEST_CURRENT_TEST", raising=False)
        monkeypatch.delenv("NEXE_ENV", raising=False)

        pipeline = temp_pipeline
        pipeline.embedding_model = _RESOLVED_FASTEMBED_MODEL

        result = pipeline._generate_embedding_sync("Real fastembed embedding test")

        assert isinstance(result, list)
        assert len(result) == 768
        assert all(isinstance(x, float) for x in result)
        # The sync path L2-normalises the vector before returning it.
        assert math.isclose(math.sqrt(sum(x * x for x in result)), 1.0, abs_tol=1e-3)

