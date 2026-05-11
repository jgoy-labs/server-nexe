"""Tests for memory/memory/pipeline/ingestion.py — coverage gaps."""
from unittest.mock import MagicMock, AsyncMock


class TestIngestionPipeline:
    def test_init(self):
        from memory.memory.pipeline.ingestion import IngestionPipeline
        pipeline = IngestionPipeline(
            flash_memory=MagicMock(),
            persistence=MagicMock(),
        )
        assert pipeline is not None

    def test_get_stats_initial(self):
        from memory.memory.pipeline.ingestion import IngestionPipeline
        pipeline = IngestionPipeline(
            flash_memory=MagicMock(),
            persistence=MagicMock(),
        )
        stats = pipeline.get_stats()
        assert stats["total_ingested"] == 0
        assert stats["duplicates_skipped"] == 0
        assert stats["failures"] == 0

    def test_close(self):
        from memory.memory.pipeline.ingestion import IngestionPipeline
        pipeline = IngestionPipeline(
            flash_memory=MagicMock(),
            persistence=MagicMock(),
        )
        pipeline.close()

    def test_generate_test_embedding(self):
        from memory.memory.pipeline.ingestion import IngestionPipeline
        emb = IngestionPipeline._generate_test_embedding("hello world")
        assert isinstance(emb, list)
        assert len(emb) > 0
        assert all(isinstance(x, float) for x in emb)

    def test_generate_test_embedding_deterministic(self):
        from memory.memory.pipeline.ingestion import IngestionPipeline
        e1 = IngestionPipeline._generate_test_embedding("same text")
        e2 = IngestionPipeline._generate_test_embedding("same text")
        assert e1 == e2

    def test_generate_test_embedding_different(self):
        from memory.memory.pipeline.ingestion import IngestionPipeline
        e1 = IngestionPipeline._generate_test_embedding("text a")
        e2 = IngestionPipeline._generate_test_embedding("text b")
        assert e1 != e2
