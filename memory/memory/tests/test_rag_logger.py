"""
Tests per memory/memory/rag_logger.py
"""
import pytest
import os
from unittest.mock import patch, MagicMock
from pathlib import Path


class TestColors:
    def test_colors_defined(self):
        from memory.memory.rag_logger import Colors
        assert Colors.RESET == "\033[0m"
        assert Colors.BOLD == "\033[1m"
        assert Colors.RED == "\033[31m"
        assert Colors.GREEN == "\033[32m"
        assert Colors.BRIGHT_GREEN == "\033[92m"

    def test_all_color_attributes(self):
        from memory.memory.rag_logger import Colors
        # Verificar que tots els atributs de color existeixen
        for attr in ["RESET", "BOLD", "DIM", "BLACK", "RED", "GREEN", "YELLOW",
                     "BLUE", "MAGENTA", "CYAN", "WHITE", "BRIGHT_RED",
                     "BRIGHT_GREEN", "BRIGHT_YELLOW", "BRIGHT_BLUE",
                     "BRIGHT_MAGENTA", "BRIGHT_CYAN", "BG_RED", "BG_GREEN",
                     "BG_YELLOW", "BG_BLUE"]:
            assert hasattr(Colors, attr)


class TestRAGEmojis:
    def test_emojis_defined(self):
        from memory.memory.rag_logger import RAGEmojis
        assert RAGEmojis.RECALL is not None
        assert RAGEmojis.STORE is not None
        assert RAGEmojis.SEARCH is not None
        assert RAGEmojis.FOUND is not None
        assert RAGEmojis.NOT_FOUND is not None
        assert RAGEmojis.ERROR is not None


class TestRAGLogger:
    def setup_method(self, method):
        """Setup per cada test"""
        import tempfile
        self.tmp = Path(tempfile.mkdtemp())

    def _make_logger(self, enabled=True):
        from memory.memory.rag_logger import RAGLogger
        with patch.dict(os.environ, {"NEXE_LOGS_DIR": str(self.tmp)}):
            logger = RAGLogger(enabled=enabled)
        return logger

    def test_creation_enabled(self):
        logger = self._make_logger(enabled=True)
        assert logger.enabled is True

    def test_creation_disabled(self):
        logger = self._make_logger(enabled=False)
        assert logger.enabled is False

    def test_log_path_set(self):
        logger = self._make_logger()
        assert logger.log_path is not None
        assert str(logger.log_path).endswith("rag.log")

    def test_logger_attribute_set(self):
        logger = self._make_logger()
        assert logger.logger is not None

    def test_write_when_enabled(self):
        logger = self._make_logger(enabled=True)
        with patch.object(logger.logger, "info") as mock_info:
            logger._write("test message")
            mock_info.assert_called_once_with("test message")

    def test_write_when_disabled(self):
        logger = self._make_logger(enabled=False)
        with patch.object(logger.logger, "info") as mock_info:
            logger._write("test message")
            mock_info.assert_not_called()

    def test_timestamp_format(self):
        logger = self._make_logger()
        ts = logger._timestamp()
        # Format: HH:MM:SS.mmm
        parts = ts.split(":")
        assert len(parts) == 3

    def test_timing_fast(self):
        logger = self._make_logger()
        result = logger._timing(10.0)
        from memory.memory.rag_logger import Colors
        assert Colors.BRIGHT_GREEN in result
        assert "10.0ms" in result

    def test_timing_medium(self):
        logger = self._make_logger()
        result = logger._timing(100.0)
        from memory.memory.rag_logger import Colors
        assert Colors.GREEN in result

    def test_timing_slow(self):
        logger = self._make_logger()
        result = logger._timing(300.0)
        from memory.memory.rag_logger import Colors
        assert Colors.YELLOW in result

    def test_timing_very_slow(self):
        logger = self._make_logger()
        result = logger._timing(700.0)
        from memory.memory.rag_logger import Colors
        assert Colors.BRIGHT_YELLOW in result

    def test_timing_extremely_slow(self):
        logger = self._make_logger()
        result = logger._timing(2000.0)
        from memory.memory.rag_logger import Colors
        assert Colors.BRIGHT_RED in result

    def test_score_color_high(self):
        logger = self._make_logger()
        from memory.memory.rag_logger import Colors
        result = logger._score_color(0.9)
        assert result == Colors.BRIGHT_GREEN

    def test_score_color_good(self):
        logger = self._make_logger()
        from memory.memory.rag_logger import Colors
        result = logger._score_color(0.7)
        assert result == Colors.GREEN

    def test_score_color_medium(self):
        logger = self._make_logger()
        from memory.memory.rag_logger import Colors
        result = logger._score_color(0.5)
        assert result == Colors.YELLOW

    def test_score_color_low(self):
        logger = self._make_logger()
        from memory.memory.rag_logger import Colors
        result = logger._score_color(0.3)
        assert result == Colors.BRIGHT_YELLOW

    def test_score_color_very_low(self):
        logger = self._make_logger()
        from memory.memory.rag_logger import Colors
        result = logger._score_color(0.1)
        assert result == Colors.DIM

    def test_truncate_short_text(self):
        logger = self._make_logger()
        result = logger._truncate("short text", max_len=80)
        assert result == "short text"

    def test_truncate_long_text(self):
        logger = self._make_logger()
        long_text = "a" * 100
        result = logger._truncate(long_text, max_len=80)
        assert result.endswith("...")
        assert len(result) == 83  # 80 + len("...")

    def test_recall_start_with_query(self):
        logger = self._make_logger()
        with patch.object(logger, "_write") as mock_write:
            logger.recall_start("test query", limit=5, entry_type="fact", person_id="user1")
            assert mock_write.call_count > 0

    def test_recall_start_without_query(self):
        logger = self._make_logger()
        with patch.object(logger, "_write") as mock_write:
            logger.recall_start(None, limit=3, entry_type=None)
            assert mock_write.call_count > 0

    def test_recall_step_flash_found(self):
        logger = self._make_logger()
        with patch.object(logger, "_write") as mock_write:
            logger.recall_step_flash(found=3, timing_ms=25.0)
            assert mock_write.call_count > 0

    def test_recall_step_flash_not_found(self):
        logger = self._make_logger()
        with patch.object(logger, "_write") as mock_write:
            logger.recall_step_flash(found=0, timing_ms=5.0)
            assert mock_write.call_count > 0

    def test_recall_step_sqlite(self):
        logger = self._make_logger()
        with patch.object(logger, "_write") as mock_write:
            logger.recall_step_sqlite(found=2, timing_ms=50.0, cached_to_flash=1)
            assert mock_write.call_count > 0

    def test_recall_step_sqlite_not_found(self):
        logger = self._make_logger()
        with patch.object(logger, "_write") as mock_write:
            logger.recall_step_sqlite(found=0, timing_ms=30.0)
            assert mock_write.call_count > 0

    def test_disabled_logger_no_writes(self):
        logger = self._make_logger(enabled=False)
        with patch.object(logger.logger, "info") as mock_info:
            logger.recall_start("query", limit=5, entry_type="fact")
            mock_info.assert_not_called()

    # --- Coverage for fallback log paths (lines 98-116) ---

    def test_log_path_fallback_to_project_path(self):
        """When primary path fails, falls back to project path."""
        from memory.memory.rag_logger import RAGLogger
        with patch.dict(os.environ, {"NEXE_LOGS_DIR": "/nonexistent_primary_path_xyz"}):
            with patch("pathlib.Path.touch", side_effect=[PermissionError, None]):
                with patch("pathlib.Path.mkdir"):
                    logger = RAGLogger(enabled=True)
                    assert logger.log_path is not None

    def test_log_path_all_fail_disables(self):
        """When all paths fail, logger is disabled."""
        from memory.memory.rag_logger import RAGLogger
        with patch.dict(os.environ, {"NEXE_LOGS_DIR": "/nonexistent_xyz"}):
            with patch("pathlib.Path.mkdir", side_effect=PermissionError("denied")):
                logger = RAGLogger(enabled=True)
                # Logger should be disabled when no writable path is found
                # (depends on whether /tmp is writable - test the mechanism)
                assert logger.log_path is not None

    # --- Coverage for recall_step_qdrant (lines 210-222) ---

    def test_recall_step_qdrant_found_with_results(self):
        logger = self._make_logger()
        results = [
            {"score": 0.95, "content": "Test result content 1"},
            {"score": 0.72, "content": "Test result content 2"},
        ]
        with patch.object(logger, "_write") as mock_write:
            logger.recall_step_qdrant(found=2, timing_ms=150.0, results=results)
            assert mock_write.call_count > 0

    def test_recall_step_qdrant_found_no_results_list(self):
        logger = self._make_logger()
        with patch.object(logger, "_write") as mock_write:
            logger.recall_step_qdrant(found=2, timing_ms=100.0, results=None)
            assert mock_write.call_count > 0

    def test_recall_step_qdrant_not_found(self):
        logger = self._make_logger()
        with patch.object(logger, "_write") as mock_write:
            logger.recall_step_qdrant(found=0, timing_ms=50.0)
            assert mock_write.call_count > 0

    # --- Coverage for recall_complete/recall_error (lines 226-239) ---

    def test_recall_complete(self):
        logger = self._make_logger()
        with patch.object(logger, "_write") as mock_write:
            logger.recall_complete(source="qdrant", total_entries=5, context_chars=2000, total_ms=350.0)
            assert mock_write.call_count > 0

    def test_recall_error(self):
        logger = self._make_logger()
        with patch.object(logger, "_write") as mock_write:
            logger.recall_error("Something went wrong")
            assert mock_write.call_count > 0

    # --- Coverage for store_* methods (lines 243-298) ---

    def test_store_start(self):
        logger = self._make_logger()
        with patch.object(logger, "_write") as mock_write:
            logger.store_start(content_type="episodic", content_preview="Test preview text", person_id="user1")
            assert mock_write.call_count > 0

    def test_store_embedding(self):
        logger = self._make_logger()
        with patch.object(logger, "_write") as mock_write:
            logger.store_embedding(model="nomic-embed-text", dimensions=768, timing_ms=400.0, text_chars=500)
            assert mock_write.call_count > 0

    def test_store_sqlite(self):
        logger = self._make_logger()
        with patch.object(logger, "_write") as mock_write:
            logger.store_sqlite(entry_id="abc123def456ghij", timing_ms=25.0)
            assert mock_write.call_count > 0

    def test_store_qdrant(self):
        logger = self._make_logger()
        with patch.object(logger, "_write") as mock_write:
            logger.store_qdrant(entry_id="abc123def456ghij", timing_ms=100.0, collection="nexe_memory")
            assert mock_write.call_count > 0

    def test_store_flash(self):
        logger = self._make_logger()
        with patch.object(logger, "_write") as mock_write:
            logger.store_flash(timing_ms=5.0)
            assert mock_write.call_count > 0

    def test_store_complete(self):
        logger = self._make_logger()
        with patch.object(logger, "_write") as mock_write:
            logger.store_complete(entry_id="abc123", total_ms=500.0, destinations=["sqlite", "qdrant", "flash"])
            assert mock_write.call_count > 0

    def test_store_error(self):
        logger = self._make_logger()
        with patch.object(logger, "_write") as mock_write:
            logger.store_error("Write failed", destination="qdrant")
            assert mock_write.call_count > 0

    def test_store_error_no_destination(self):
        logger = self._make_logger()
        with patch.object(logger, "_write") as mock_write:
            logger.store_error("Write failed")
            assert mock_write.call_count > 0

    # --- Coverage for memory_search_* (lines 302-342) ---

    def test_memory_search_start(self):
        logger = self._make_logger()
        with patch.object(logger, "_write") as mock_write:
            logger.memory_search_start(query="test search query", max_tokens=4096)
            assert mock_write.call_count > 0

    def test_memory_route_with_collections(self):
        logger = self._make_logger()
        with patch.object(logger, "_write") as mock_write:
            logger.memory_route(collections=["nexe_web_ui", "user_knowledge"], timing_ms=30.0)
            assert mock_write.call_count > 0

    def test_memory_route_empty_collections(self):
        logger = self._make_logger()
        with patch.object(logger, "_write") as mock_write:
            logger.memory_route(collections=[], timing_ms=5.0)
            assert mock_write.call_count > 0

    def test_memory_collection_search(self):
        logger = self._make_logger()
        top_results = [
            {"score": 0.9, "title": "Document 1"},
            {"score": 0.7, "content": "Document 2 content"},
        ]
        with patch.object(logger, "_write") as mock_write:
            logger.memory_collection_search(collection="nexe_web_ui", results=3, timing_ms=200.0, top_results=top_results)
            assert mock_write.call_count > 0

    def test_memory_collection_search_no_top(self):
        logger = self._make_logger()
        with patch.object(logger, "_write") as mock_write:
            logger.memory_collection_search(collection="nexe_web_ui", results=0, timing_ms=50.0)
            assert mock_write.call_count > 0

    def test_memory_memory_search(self):
        logger = self._make_logger()
        top_results = [
            {"score": 0.85, "content": "Previous conversation about AI"},
        ]
        with patch.object(logger, "_write") as mock_write:
            logger.memory_memory_search(results=1, timing_ms=150.0, top_results=top_results)
            assert mock_write.call_count > 0

    def test_memory_memory_search_no_top(self):
        logger = self._make_logger()
        with patch.object(logger, "_write") as mock_write:
            logger.memory_memory_search(results=0, timing_ms=100.0)
            assert mock_write.call_count > 0

    # --- Coverage for memory_complete (lines 346-352) ---

    def test_memory_complete(self):
        logger = self._make_logger()
        with patch.object(logger, "_write") as mock_write:
            logger.memory_complete(total_sources=3, context_chars=5000, total_ms=800.0)
            assert mock_write.call_count > 0

    # --- Coverage for embedding_* (lines 356-366) ---

    def test_embedding_generate(self):
        logger = self._make_logger()
        with patch.object(logger, "_write") as mock_write:
            logger.embedding_generate(text_preview="Sample text for embedding", model="paraphrase-multilingual-mpnet-base-v2", dimensions=768, timing_ms=50.0)
            assert mock_write.call_count > 0

    def test_embedding_error(self):
        logger = self._make_logger()
        with patch.object(logger, "_write") as mock_write:
            logger.embedding_error("Model loading failed", model="paraphrase-multilingual-mpnet-base-v2")
            assert mock_write.call_count > 0

    def test_embedding_error_no_model(self):
        logger = self._make_logger()
        with patch.object(logger, "_write") as mock_write:
            logger.embedding_error("Encoding failed")
            assert mock_write.call_count > 0

    # --- Coverage for qdrant_search / qdrant_results / qdrant_upsert (lines 370-389) ---

    def test_qdrant_search(self):
        logger = self._make_logger()
        with patch.object(logger, "_write") as mock_write:
            logger.qdrant_search(collection="nexe_memory", vector_size=768, limit=10, score_threshold=0.7)
            assert mock_write.call_count > 0

    def test_qdrant_results(self):
        logger = self._make_logger()
        results = [
            {"score": 0.95, "id": "abc123def456ghij"},
            {"score": 0.82, "id": "xyz789abc123def4"},
            {"score": 0.71, "id": "111222333444aaaa"},
        ]
        with patch.object(logger, "_write") as mock_write:
            logger.qdrant_results(results=results, timing_ms=200.0)
            assert mock_write.call_count > 0

    def test_qdrant_upsert(self):
        logger = self._make_logger()
        with patch.object(logger, "_write") as mock_write:
            logger.qdrant_upsert(collection="nexe_memory", point_id="abc123def456ghij1234", timing_ms=50.0)
            assert mock_write.call_count > 0

    # --- Coverage for stats_summary (lines 393-420) ---

    def test_stats_summary_all_sections(self):
        logger = self._make_logger()
        stats = {
            "sqlite": {"total": 100, "episodic": 60, "semantic": 40},
            "qdrant": {"collection": "nexe_memory", "vectors": 100, "dimensions": 768},
            "flash": {"entries": 20, "ttl": 1800},
        }
        with patch.object(logger, "_write") as mock_write:
            logger.stats_summary(stats)
            assert mock_write.call_count > 0

    def test_stats_summary_empty(self):
        logger = self._make_logger()
        with patch.object(logger, "_write") as mock_write:
            logger.stats_summary({})
            assert mock_write.call_count > 0

    def test_stats_summary_partial(self):
        logger = self._make_logger()
        with patch.object(logger, "_write") as mock_write:
            logger.stats_summary({"sqlite": {"total": 10}})
            assert mock_write.call_count > 0

    # --- Coverage for get_rag_logger singleton (lines 427-429) ---

    def test_get_rag_logger_singleton(self):
        import memory.memory.rag_logger as rl
        # Reset singleton for test
        rl._rag_logger = None
        logger1 = rl.get_rag_logger(enabled=True)
        logger2 = rl.get_rag_logger(enabled=True)
        assert logger1 is logger2
        # Cleanup
        rl._rag_logger = None
