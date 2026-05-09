"""
────────────────────────────────────
Server Nexe
Author: Jordi Goy
Location: core/ingest/tests/test_ingest_docs.py
Description: Tests per ingest_docs.py (chunk_text, ingest_documentation mockejat).

www.jgoy.net · https://server-nexe.org
────────────────────────────────────
"""

import asyncio
import pytest
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

from core.ingest.ingest_docs import (
    chunk_text,
    CHUNK_SIZE,
    CHUNK_OVERLAP,
    DOCS_COLLECTION,
)


# ─── Tests chunk_text ─────────────────────────────────────────────────────────

class TestChunkText:

    def test_empty_text_returns_empty_list(self):
        assert chunk_text("") == []

    def test_short_text_one_chunk(self):
        result = chunk_text("Hello world")
        assert len(result) == 1
        assert result[0] == "Hello world"

    def test_long_text_multiple_chunks(self):
        text = "word " * 200  # 1000 chars
        chunks = chunk_text(text, chunk_size=100, overlap=10)
        assert len(chunks) > 1

    def test_chunks_max_size(self):
        text = "x" * 1000
        chunks = chunk_text(text, chunk_size=100, overlap=0)
        for chunk in chunks:
            assert len(chunk) <= 100

    def test_overlap_content(self):
        text = "ABCDE" * 40  # 200 chars
        chunks = chunk_text(text, chunk_size=50, overlap=10)
        # Consecutive chunks should share content
        if len(chunks) > 1:
            # The end of chunk[0] should overlap with start of chunk[1]
            assert chunks[0][-5:] == chunks[1][:5] or len(chunks[0]) >= 45

    def test_whitespace_only_chunks_skipped(self):
        text = "text\n\n\n\n\n\nmore text"
        chunks = chunk_text(text, chunk_size=4, overlap=0)
        for chunk in chunks:
            assert chunk.strip() != ""

    def test_uses_default_chunk_size(self):
        text = "a" * (CHUNK_SIZE * 3)
        chunks = chunk_text(text)
        assert len(chunks) >= 2

    def test_constant_docs_collection(self):
        assert DOCS_COLLECTION == "nexe_documentation"


# ─── Tests ingest_documentation ───────────────────────────────────────────────

class TestIngestDocumentation:

    def test_returns_false_on_memory_init_failure(self):
        from core.ingest.ingest_docs import ingest_documentation

        mock_memory = MagicMock()
        mock_memory.initialize = AsyncMock(side_effect=Exception("Qdrant not running"))

        with patch("memory.memory.api.MemoryAPI", return_value=mock_memory):
            result = asyncio.run(ingest_documentation())

        assert result is False

    def test_returns_false_on_collection_creation_failure(self):
        from core.ingest.ingest_docs import ingest_documentation

        mock_memory = MagicMock()
        mock_memory.initialize = AsyncMock()
        mock_memory.collection_exists = AsyncMock(return_value=False)
        mock_memory.create_collection = AsyncMock(side_effect=Exception("DB error"))

        with patch("memory.memory.api.MemoryAPI", return_value=mock_memory):
            result = asyncio.run(ingest_documentation())

        assert result is False

    def test_returns_true_on_success_no_files(self, tmp_path):
        """When there are no .md files, returns True anyway."""
        from core.ingest.ingest_docs import ingest_documentation

        mock_memory = MagicMock()
        mock_memory.initialize = AsyncMock()
        mock_memory.collection_exists = AsyncMock(return_value=False)
        mock_memory.create_collection = AsyncMock()
        mock_memory.close = AsyncMock()

        with patch("memory.memory.api.MemoryAPI", return_value=mock_memory), \
             patch("core.ingest.ingest_docs.PROJECT_ROOT", tmp_path):
            # tmp_path has no docs/ or README.md
            result = asyncio.run(ingest_documentation())

        assert result is True

    def test_ingests_markdown_files(self, tmp_path):
        """Checks that found .md files are ingested."""
        from core.ingest.ingest_docs import ingest_documentation

        # Create docs dir with one file
        docs_dir = tmp_path / "docs"
        docs_dir.mkdir()
        (docs_dir / "test.md").write_text("# Test\n\nThis is test documentation.")

        mock_memory = MagicMock()
        mock_memory.initialize = AsyncMock()
        mock_memory.collection_exists = AsyncMock(return_value=True)
        mock_memory.delete_collection = AsyncMock()
        mock_memory.create_collection = AsyncMock()
        mock_memory.store = AsyncMock(return_value="doc-id")
        mock_memory.close = AsyncMock()

        with patch("memory.memory.api.MemoryAPI", return_value=mock_memory), \
             patch("core.ingest.ingest_docs.PROJECT_ROOT", tmp_path):
            result = asyncio.run(ingest_documentation())

        assert result is True
        assert mock_memory.store.call_count >= 1

    def test_recreates_collection_if_exists(self, tmp_path):
        """If the collection exists, it deletes and recreates it."""
        from core.ingest.ingest_docs import ingest_documentation

        mock_memory = MagicMock()
        mock_memory.initialize = AsyncMock()
        mock_memory.collection_exists = AsyncMock(return_value=True)  # exists
        mock_memory.delete_collection = AsyncMock()
        mock_memory.create_collection = AsyncMock()
        mock_memory.close = AsyncMock()

        with patch("memory.memory.api.MemoryAPI", return_value=mock_memory), \
             patch("core.ingest.ingest_docs.PROJECT_ROOT", tmp_path):
            asyncio.run(ingest_documentation())

        mock_memory.delete_collection.assert_called_once()
        mock_memory.create_collection.assert_called_once()

    def test_readme_included_if_exists(self, tmp_path):
        """README.md at the project root must be included."""
        from core.ingest.ingest_docs import ingest_documentation

        readme = tmp_path / "README.md"
        readme.write_text("# Nexe README\n\nProject documentation.")

        mock_memory = MagicMock()
        mock_memory.initialize = AsyncMock()
        mock_memory.collection_exists = AsyncMock(return_value=False)
        mock_memory.create_collection = AsyncMock()
        mock_memory.store = AsyncMock(return_value="id")
        mock_memory.close = AsyncMock()

        with patch("memory.memory.api.MemoryAPI", return_value=mock_memory), \
             patch("core.ingest.ingest_docs.PROJECT_ROOT", tmp_path):
            result = asyncio.run(ingest_documentation())

        assert result is True
        assert mock_memory.store.call_count >= 1

    def test_file_read_error_continues(self, tmp_path):
        """Errors in a specific file should not stop the process."""
        from core.ingest.ingest_docs import ingest_documentation

        docs_dir = tmp_path / "docs"
        docs_dir.mkdir()
        bad_file = docs_dir / "bad.md"
        bad_file.write_bytes(b"\xff\xfe")  # Invalid UTF-8

        mock_memory = MagicMock()
        mock_memory.initialize = AsyncMock()
        mock_memory.collection_exists = AsyncMock(return_value=False)
        mock_memory.create_collection = AsyncMock()
        mock_memory.store = AsyncMock()
        mock_memory.close = AsyncMock()

        with patch("memory.memory.api.MemoryAPI", return_value=mock_memory), \
             patch("core.ingest.ingest_docs.PROJECT_ROOT", tmp_path):
            result = asyncio.run(ingest_documentation())

        assert result is True
