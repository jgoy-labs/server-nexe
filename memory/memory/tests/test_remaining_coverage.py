"""
Additional coverage tests for remaining memory/memory/ files.
Covers gaps in: flash_memory, module, persistence, ingestion, deduplicator,
                api/__init__.py, api/models.py, api/v1.py, models/memory_entry.py,
                metrics, router.py
"""

import asyncio
import pytest
from datetime import datetime, timezone, timedelta
from pathlib import Path
from unittest.mock import patch, MagicMock, AsyncMock, PropertyMock


# === flash_memory.py coverage ===

class TestFlashMemoryCoverage:

    def test_normalize_expiry_naive(self):
        from memory.memory.engines.flash_memory import _normalize_expiry
        naive_dt = datetime(2025, 1, 1)
        result = _normalize_expiry(naive_dt)
        assert result.tzinfo is not None

    def test_normalize_expiry_aware(self):
        from memory.memory.engines.flash_memory import _normalize_expiry
        aware_dt = datetime(2025, 1, 1, tzinfo=timezone.utc)
        result = _normalize_expiry(aware_dt)
        assert result == aware_dt

    def test_delete_existing(self):
        async def run():
            from memory.memory.engines.flash_memory import FlashMemory
            from memory.memory.models.memory_entry import MemoryEntry
            from memory.memory.models.memory_types import MemoryType
            flash = FlashMemory()
            entry = MemoryEntry(entry_type=MemoryType.EPISODIC, content="Test delete", source="test")
            await flash.store(entry)
            result = await flash.delete(entry.id)
            assert result is True
        asyncio.run(run())

    def test_delete_nonexistent(self):
        async def run():
            from memory.memory.engines.flash_memory import FlashMemory
            flash = FlashMemory()
            result = await flash.delete("nonexistent_id")
            assert result is False
        asyncio.run(run())

    def test_cleanup_expired_removes_entries(self):
        async def run():
            from memory.memory.engines.flash_memory import FlashMemory
            from memory.memory.models.memory_entry import MemoryEntry
            from memory.memory.models.memory_types import MemoryType
            flash = FlashMemory(default_ttl_seconds=1800)
            entry = MemoryEntry(entry_type=MemoryType.EPISODIC, content="Expired entry", source="test")
            await flash.store(entry)
            flash._expiry_heap = [(0.0, entry.id)]
            removed = await flash.cleanup_expired()
            assert removed == 1
            assert entry.id not in flash._store
        asyncio.run(run())

    def test_cleanup_expired_skips_already_removed(self):
        async def run():
            from memory.memory.engines.flash_memory import FlashMemory
            import heapq
            flash = FlashMemory()
            heapq.heappush(flash._expiry_heap, (0.0, "ghost_id"))
            removed = await flash.cleanup_expired()
            assert removed == 0
        asyncio.run(run())

    def test_get_stats(self):
        async def run():
            from memory.memory.engines.flash_memory import FlashMemory
            from memory.memory.models.memory_entry import MemoryEntry
            from memory.memory.models.memory_types import MemoryType
            flash = FlashMemory()
            entry = MemoryEntry(entry_type=MemoryType.EPISODIC, content="Stats test", source="test")
            await flash.store(entry)
            stats = await flash.get_stats()
            assert stats["total_entries"] == 1
            assert stats["expired_pending"] >= 1
        asyncio.run(run())

    def test_is_expired_true(self):
        async def run():
            from memory.memory.engines.flash_memory import FlashMemory
            from memory.memory.models.memory_entry import MemoryEntry
            from memory.memory.models.memory_types import MemoryType
            flash = FlashMemory(default_ttl_seconds=60)
            entry = MemoryEntry(
                entry_type=MemoryType.EPISODIC, content="Old entry", source="test",
                ttl_seconds=60, timestamp=datetime(2020, 1, 1, tzinfo=timezone.utc)
            )
            assert flash._is_expired(entry) is True
        asyncio.run(run())

    def test_get_expired_entry_removed(self):
        async def run():
            from memory.memory.engines.flash_memory import FlashMemory
            from memory.memory.models.memory_entry import MemoryEntry
            from memory.memory.models.memory_types import MemoryType
            flash = FlashMemory(default_ttl_seconds=60)
            entry = MemoryEntry(
                entry_type=MemoryType.EPISODIC, content="Will be expired", source="test",
                ttl_seconds=60, timestamp=datetime(2020, 1, 1, tzinfo=timezone.utc)
            )
            flash._store[entry.id] = entry
            result = await flash.get(entry.id)
            assert result is None
            assert entry.id not in flash._store
        asyncio.run(run())


# === deduplicator.py coverage ===

class TestDeduplicatorCoverage:

    def test_mark_as_seen(self):
        from memory.memory.pipeline.deduplicator import Deduplicator
        dedup = Deduplicator()
        dedup.mark_as_seen("test-id-123")
        assert "test-id-123" in dedup._seen_ids

    def test_clear_cache(self):
        from memory.memory.pipeline.deduplicator import Deduplicator
        dedup = Deduplicator()
        dedup.mark_as_seen("id1")
        dedup.clear_cache()
        assert len(dedup._seen_ids) == 0

    def test_compute_content_hash(self):
        from memory.memory.pipeline.deduplicator import Deduplicator
        hash1 = Deduplicator.compute_content_hash("test content")
        hash2 = Deduplicator.compute_content_hash("test content")
        hash3 = Deduplicator.compute_content_hash("different content")
        assert hash1 == hash2
        assert hash1 != hash3
        assert len(hash1) == 16


# === api/models.py coverage ===

class TestApiModelsCoverage:

    def test_coerce_aware_naive_dt(self):
        from memory.memory.api.models import _coerce_aware
        naive = datetime(2025, 1, 1)
        result = _coerce_aware(naive)
        assert result.tzinfo == timezone.utc

    def test_document_is_expired_naive_expires(self):
        from memory.memory.api.models import Document
        doc = Document(id="test", text="test", collection="col", expires_at=datetime(2020, 1, 1))
        assert doc.is_expired is True


# === models/memory_entry.py coverage ===

class TestMemoryEntryCoverage:

    def test_content_whitespace_only_raises(self):
        from memory.memory.models.memory_entry import MemoryEntry
        from memory.memory.models.memory_types import MemoryType
        with pytest.raises(Exception):
            MemoryEntry(entry_type=MemoryType.EPISODIC, content="   \n\t  ", source="test")


# === metrics.py coverage ===

class TestMetricsCoverage:

    def test_update_from_module_exception(self):
        from memory.memory.metrics import MemoryMetrics
        metrics = MemoryMetrics()
        mock_module = MagicMock()
        mock_module._initialized = True
        mock_module._flash_memory = None
        mock_module._pipeline = MagicMock()
        mock_module._pipeline.get_stats.side_effect = Exception("stats error")
        metrics.update_from_module(mock_module)


# === ingestion.py coverage ===

class TestIngestionCoverage:

    def test_ingest_exception(self):
        from memory.memory.pipeline.ingestion import IngestionPipeline
        from memory.memory.models.memory_entry import MemoryEntry
        from memory.memory.models.memory_types import MemoryType
        flash = MagicMock()
        persistence = MagicMock()
        pipeline = IngestionPipeline(flash, persistence)
        entry = MemoryEntry(entry_type=MemoryType.EPISODIC, content="Test entry", source="test")

        async def run():
            pipeline.deduplicator.is_duplicate = MagicMock(return_value=False)
            pipeline._generate_embedding = AsyncMock(side_effect=Exception("embedding error"))
            result = await pipeline.ingest(entry)
            assert result is False
            assert pipeline.stats["failures"] == 1
        asyncio.run(run())

    def test_ingest_batch_with_exception(self):
        from memory.memory.pipeline.ingestion import IngestionPipeline
        from memory.memory.models.memory_entry import MemoryEntry
        from memory.memory.models.memory_types import MemoryType
        flash = MagicMock()
        persistence = MagicMock()
        pipeline = IngestionPipeline(flash, persistence)
        entries = [
            MemoryEntry(entry_type=MemoryType.EPISODIC, content=f"Entry {i}", source="test")
            for i in range(3)
        ]

        async def run():
            results_iter = iter([True, False, Exception("fail")])
            async def mock_ingest(entry):
                val = next(results_iter)
                if isinstance(val, Exception):
                    raise val
                return val
            pipeline.ingest = mock_ingest
            stats = await pipeline.ingest_batch(entries)
            assert stats["success"] == 1
            assert stats["duplicates"] == 1
            assert stats["failures"] == 1
        asyncio.run(run())

    def test_generate_embedding_with_model(self):
        from memory.memory.pipeline.ingestion import IngestionPipeline
        flash = MagicMock()
        persistence = MagicMock()
        pipeline = IngestionPipeline(flash, persistence, embedding_model="test-model")
        with patch.dict("os.environ", {"PYTEST_CURRENT_TEST": "yes"}):
            result = pipeline._generate_embedding_sync("test text")
            assert isinstance(result, list)
            assert len(result) == 768

    def test_generate_test_embedding_empty(self):
        from memory.memory.pipeline.ingestion import IngestionPipeline
        with pytest.raises(ValueError):
            IngestionPipeline._generate_test_embedding("   ")


# === memory/memory/api/__init__.py coverage ===

class TestMemoryAPICoverage:

    def test_initialize_already_initialized(self):
        from memory.memory.api import MemoryAPI
        api = MemoryAPI.__new__(MemoryAPI)
        api._initialized = True
        api._qdrant = MagicMock()
        api._embedder = MagicMock()
        api._executor = MagicMock()
        api.qdrant_url = "http://localhost:6333"
        api.qdrant_path = None
        api.embedding_model = "test"
        api.vector_size = 768

        async def run():
            result = await api.initialize()
            assert result is True
        asyncio.run(run())

    def test_generate_embedding(self):
        from memory.memory.api import MemoryAPI
        from concurrent.futures import ThreadPoolExecutor
        api = MemoryAPI.__new__(MemoryAPI)
        api._initialized = True
        api._executor = ThreadPoolExecutor(max_workers=1)
        mock_embedder = MagicMock()
        mock_embedder.embed.return_value = iter([[0.6, 0.8]])
        api._embedder = mock_embedder

        async def run():
            result = await api._generate_embedding("test text")
            assert isinstance(result, list)
            assert len(result) == 2
        asyncio.run(run())
        api._executor.shutdown(wait=False)


# === memory/memory/router.py coverage ===

class TestMemoryRouterCoverage:

    def test_router_exists(self):
        from memory.memory.router import router_public
        assert router_public is not None

    def test_get_memory_info(self):
        from memory.memory.router import get_memory_info

        async def run():
            result = await get_memory_info()
            assert result["module"] == "Memory"
            assert "manifest" in result
        asyncio.run(run())
