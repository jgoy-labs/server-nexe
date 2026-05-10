"""Tests for memory/memory/cli/rag_viewer.py — coverage gaps."""
from unittest.mock import patch, MagicMock
from pathlib import Path


class TestFindLogPath:
    def test_primary_path_exists(self, tmp_path):
        log = tmp_path / "rag.log"
        log.touch()
        with patch("memory.memory.cli.rag_viewer.RAG_LOG_PATH", log):
            from memory.memory.cli.rag_viewer import find_log_path
            result = find_log_path()
        assert result == log

    def test_fallback_path_used(self, tmp_path):
        primary = tmp_path / "primary" / "rag.log"
        fallback = tmp_path / "fallback" / "rag.log"
        fallback.parent.mkdir(parents=True)
        fallback.touch()
        with patch("memory.memory.cli.rag_viewer.RAG_LOG_PATH", primary):
            with patch("memory.memory.cli.rag_viewer.FALLBACK_PATHS", [fallback]):
                from memory.memory.cli.rag_viewer import find_log_path
                result = find_log_path()
        assert result == fallback

    def test_creates_primary_when_nothing_exists(self, tmp_path):
        primary = tmp_path / "newlogs" / "rag.log"
        with patch("memory.memory.cli.rag_viewer.RAG_LOG_PATH", primary):
            with patch("memory.memory.cli.rag_viewer.FALLBACK_PATHS", []):
                from memory.memory.cli.rag_viewer import find_log_path
                result = find_log_path()
        assert result == primary
        assert primary.exists()
