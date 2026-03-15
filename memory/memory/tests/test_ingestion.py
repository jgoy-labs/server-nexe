"""
────────────────────────────────────
Server Nexe
Version: 0.8
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

@pytest.fixture
async def temp_pipeline():
  """Fixture: IngestionPipeline amb components temporals"""
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
  """Tests per IngestionPipeline"""

  async def test_initialization(self, temp_pipeline):
    """Inicialització amb flash + persistence"""
    pipeline = temp_pipeline

    assert pipeline.flash is not None
    assert pipeline.persistence is not None
    assert pipeline.embedding_model == "paraphrase-multilingual-mpnet-base-v2"
    assert pipeline.deduplicator is not None
    assert pipeline.stats["total_ingested"] == 0

  async def test_ingest_single_entry(self, temp_pipeline):
    """Ingestar una sola entry"""
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
    """Deduplicació: mateix content no s'ingesta dos cops"""
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
    """Generació d'embedding retorna dummy vector"""
    pipeline = temp_pipeline

    text = "Test text for embedding"
    embedding = await pipeline._generate_embedding(text)

    assert isinstance(embedding, list)
    assert len(embedding) == 768
    assert all(isinstance(x, float) for x in embedding)

  async def test_embedding_deterministic(self, temp_pipeline):
    """Embeddings són determinístics (mateix text = mateix vector)"""
    pipeline = temp_pipeline

    text = "Same text"
    embedding1 = await pipeline._generate_embedding(text)
    embedding2 = await pipeline._generate_embedding(text)

    assert embedding1 == embedding2

  async def test_ingest_batch(self, temp_pipeline):
    """Ingest batch de múltiples entries"""
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
    """Batch amb duplicats (mateix content)"""
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
    """Neteja d'entries expirades"""
    pipeline = temp_pipeline

    deleted = await pipeline.cleanup_expired()

    assert deleted == 0

  async def test_get_stats(self, temp_pipeline):
    """Obtenir estadístiques del pipeline"""
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
    """Ingesta concurrent amb asyncio.gather"""
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
    """Tancar pipeline (shutdown executor)"""
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

