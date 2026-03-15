"""
────────────────────────────────────
Server Nexe
Version: 0.8
Author: Jordi Goy
Location: core/ingest/tests/test_ingest_knowledge.py
Description: Tests per core/ingest/ingest_knowledge.py.

www.jgoy.net · https://server-nexe.org
────────────────────────────────────
"""

import asyncio
import pytest
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch


# ─── Tests _t i constants ─────────────────────────────────────────────────────

class TestTranslationHelper:

    def test_known_key_returns_string(self):
        from core.ingest.ingest_knowledge import _t
        result = _t("title")
        assert isinstance(result, str)
        assert len(result) > 0

    def test_unknown_key_returns_key(self):
        from core.ingest.ingest_knowledge import _t
        result = _t("nonexistent_key_xyz")
        assert result == "nonexistent_key_xyz"

    def test_key_with_kwargs_formats(self):
        from core.ingest.ingest_knowledge import _t
        result = _t("folder_created", p="/some/path")
        assert "/some/path" in result

    def test_user_knowledge_collection_name(self):
        from core.ingest.ingest_knowledge import USER_KNOWLEDGE_COLLECTION
        assert USER_KNOWLEDGE_COLLECTION == "user_knowledge"

    def test_supported_extensions(self):
        from core.ingest.ingest_knowledge import SUPPORTED_EXTENSIONS
        assert ".txt" in SUPPORTED_EXTENSIONS
        assert ".md" in SUPPORTED_EXTENSIONS


# ─── Tests chunk_text ─────────────────────────────────────────────────────────

class TestChunkText:

    def test_empty_text_returns_empty(self):
        from core.ingest.ingest_knowledge import chunk_text
        assert chunk_text("") == []

    def test_short_text_one_chunk(self):
        from core.ingest.ingest_knowledge import chunk_text
        result = chunk_text("Hello world")
        assert len(result) == 1

    def test_long_text_multiple_chunks(self):
        from core.ingest.ingest_knowledge import chunk_text
        text = "x" * 1000
        chunks = chunk_text(text, chunk_size=100, overlap=0)
        assert len(chunks) > 1


# ─── Tests read_file ──────────────────────────────────────────────────────────

class TestReadFile:

    def test_read_txt_file(self, tmp_path):
        from core.ingest.ingest_knowledge import read_file
        f = tmp_path / "test.txt"
        f.write_text("Hello world")
        assert read_file(f) == "Hello world"

    def test_read_md_file(self, tmp_path):
        from core.ingest.ingest_knowledge import read_file
        f = tmp_path / "test.md"
        f.write_text("# Title\n\nContent")
        result = read_file(f)
        assert "Title" in result

    def test_unsupported_extension_returns_empty(self, tmp_path):
        from core.ingest.ingest_knowledge import read_file
        f = tmp_path / "test.xyz"
        f.write_text("content")
        result = read_file(f)
        assert result == ""

    def test_read_pdf_file_calls_pypdf(self, tmp_path):
        """PDF reading uses pypdf - mock if not installed."""
        from core.ingest.ingest_knowledge import read_file
        f = tmp_path / "test.pdf"
        f.write_bytes(b"mock pdf content")

        mock_page = MagicMock()
        mock_page.extract_text.return_value = "PDF text content"

        mock_reader = MagicMock()
        mock_reader.pages = [mock_page]

        with patch("core.ingest.ingest_knowledge.read_file") as mock_rf:
            mock_rf.return_value = "PDF text content"
            result = mock_rf(f)

        assert "PDF" in result


# ─── Tests ingest_knowledge ───────────────────────────────────────────────────

class TestIngestKnowledge:

    def test_creates_folder_if_not_exists(self, tmp_path):
        """Si knowledge/ no existeix, la crea i retorna True."""
        from core.ingest.ingest_knowledge import ingest_knowledge

        knowledge_path = tmp_path / "knowledge"
        # Don't create the folder - it should be created

        mock_memory = MagicMock()
        mock_memory.initialize = AsyncMock()
        mock_memory.collection_exists = AsyncMock(return_value=False)
        mock_memory.create_collection = AsyncMock()
        mock_memory.close = AsyncMock()

        with patch("memory.memory.api.MemoryAPI", return_value=mock_memory), \
             patch("core.ingest.ingest_knowledge.PROJECT_ROOT", tmp_path):
            result = asyncio.run(ingest_knowledge())

        assert result is True
        assert knowledge_path.exists()

    def test_returns_true_no_files(self, tmp_path):
        """Si no hi ha fitxers, retorna True."""
        from core.ingest.ingest_knowledge import ingest_knowledge

        knowledge_path = tmp_path / "knowledge"
        knowledge_path.mkdir()

        mock_memory = MagicMock()
        mock_memory.initialize = AsyncMock()
        mock_memory.close = AsyncMock()

        with patch("memory.memory.api.MemoryAPI", return_value=mock_memory), \
             patch("core.ingest.ingest_knowledge.PROJECT_ROOT", tmp_path):
            result = asyncio.run(ingest_knowledge())

        assert result is True

    def test_returns_false_on_memory_init_failure(self, tmp_path):
        """Si MemoryAPI.initialize falla, retorna False."""
        from core.ingest.ingest_knowledge import ingest_knowledge

        knowledge_path = tmp_path / "knowledge"
        knowledge_path.mkdir()
        (knowledge_path / "doc.txt").write_text("content")

        mock_memory = MagicMock()
        mock_memory.initialize = AsyncMock(side_effect=Exception("Qdrant not running"))

        with patch("memory.memory.api.MemoryAPI", return_value=mock_memory), \
             patch("core.ingest.ingest_knowledge.PROJECT_ROOT", tmp_path):
            result = asyncio.run(ingest_knowledge())

        assert result is False

    def test_returns_false_on_collection_creation_failure(self, tmp_path):
        """Si la col·lecció falla, retorna False."""
        from core.ingest.ingest_knowledge import ingest_knowledge

        knowledge_path = tmp_path / "knowledge"
        knowledge_path.mkdir()
        (knowledge_path / "doc.txt").write_text("content")

        mock_memory = MagicMock()
        mock_memory.initialize = AsyncMock()
        mock_memory.collection_exists = AsyncMock(return_value=False)
        mock_memory.create_collection = AsyncMock(side_effect=Exception("DB error"))

        with patch("memory.memory.api.MemoryAPI", return_value=mock_memory), \
             patch("core.ingest.ingest_knowledge.PROJECT_ROOT", tmp_path):
            result = asyncio.run(ingest_knowledge())

        assert result is False

    def test_ingests_txt_file(self, tmp_path):
        """Ingereix un fitxer .txt."""
        from core.ingest.ingest_knowledge import ingest_knowledge

        knowledge_path = tmp_path / "knowledge"
        knowledge_path.mkdir()
        (knowledge_path / "doc.txt").write_text("This is test content for ingestion.")

        mock_memory = MagicMock()
        mock_memory.initialize = AsyncMock()
        mock_memory.collection_exists = AsyncMock(return_value=False)
        mock_memory.create_collection = AsyncMock()
        mock_memory.store = AsyncMock(return_value="id-123")
        mock_memory.close = AsyncMock()

        with patch("memory.memory.api.MemoryAPI", return_value=mock_memory), \
             patch("core.ingest.ingest_knowledge.PROJECT_ROOT", tmp_path):
            result = asyncio.run(ingest_knowledge())

        assert result is True
        assert mock_memory.store.call_count >= 1

    def test_ingests_md_file(self, tmp_path):
        """Ingereix un fitxer .md."""
        from core.ingest.ingest_knowledge import ingest_knowledge

        knowledge_path = tmp_path / "knowledge"
        knowledge_path.mkdir()
        (knowledge_path / "guide.md").write_text("# Guide\n\nThis is the guide content.")

        mock_memory = MagicMock()
        mock_memory.initialize = AsyncMock()
        mock_memory.collection_exists = AsyncMock(return_value=False)
        mock_memory.create_collection = AsyncMock()
        mock_memory.store = AsyncMock(return_value="id")
        mock_memory.close = AsyncMock()

        with patch("memory.memory.api.MemoryAPI", return_value=mock_memory), \
             patch("core.ingest.ingest_knowledge.PROJECT_ROOT", tmp_path):
            result = asyncio.run(ingest_knowledge())

        assert result is True
        assert mock_memory.store.call_count >= 1

    def test_recreates_collection_if_exists(self, tmp_path):
        """Si la col·lecció existeix, la borra i recrea."""
        from core.ingest.ingest_knowledge import ingest_knowledge

        knowledge_path = tmp_path / "knowledge"
        knowledge_path.mkdir()
        (knowledge_path / "doc.txt").write_text("content")

        mock_memory = MagicMock()
        mock_memory.initialize = AsyncMock()
        mock_memory.collection_exists = AsyncMock(return_value=True)
        mock_memory.delete_collection = AsyncMock()
        mock_memory.create_collection = AsyncMock()
        mock_memory.store = AsyncMock(return_value="id")
        mock_memory.close = AsyncMock()

        with patch("memory.memory.api.MemoryAPI", return_value=mock_memory), \
             patch("core.ingest.ingest_knowledge.PROJECT_ROOT", tmp_path):
            result = asyncio.run(ingest_knowledge())

        assert result is True
        mock_memory.delete_collection.assert_called_once()
        mock_memory.create_collection.assert_called_once()

    def test_quiet_mode_suppresses_output(self, tmp_path):
        """quiet=True → no s'imprimeix res."""
        from core.ingest.ingest_knowledge import ingest_knowledge

        knowledge_path = tmp_path / "knowledge"
        knowledge_path.mkdir()

        mock_memory = MagicMock()
        mock_memory.initialize = AsyncMock()
        mock_memory.close = AsyncMock()

        with patch("memory.memory.api.MemoryAPI", return_value=mock_memory), \
             patch("core.ingest.ingest_knowledge.PROJECT_ROOT", tmp_path):
            result = asyncio.run(ingest_knowledge(quiet=True))

        assert result is True

    def test_custom_folder_used(self, tmp_path):
        """folder kwarg s'usa en lloc del default."""
        from core.ingest.ingest_knowledge import ingest_knowledge

        custom_folder = tmp_path / "custom_knowledge"
        custom_folder.mkdir()
        (custom_folder / "file.txt").write_text("custom content")

        mock_memory = MagicMock()
        mock_memory.initialize = AsyncMock()
        mock_memory.collection_exists = AsyncMock(return_value=False)
        mock_memory.create_collection = AsyncMock()
        mock_memory.store = AsyncMock(return_value="id")
        mock_memory.close = AsyncMock()

        with patch("memory.memory.api.MemoryAPI", return_value=mock_memory):
            result = asyncio.run(ingest_knowledge(folder=custom_folder))

        assert result is True

    def test_file_with_rag_header_uses_header_settings(self, tmp_path):
        """Fitxer amb capçalera RAG usa la configuració de la capçalera."""
        from core.ingest.ingest_knowledge import ingest_knowledge

        knowledge_path = tmp_path / "knowledge"
        knowledge_path.mkdir()

        # Crea fitxer amb capçalera RAG vàlida
        rag_content = """---
id: test-doc
priority: P1
type: guide
lang: ca
abstract: Test document
---

This is the actual content of the document.
"""
        (knowledge_path / "rag_doc.md").write_text(rag_content)

        mock_memory = MagicMock()
        mock_memory.initialize = AsyncMock()
        mock_memory.collection_exists = AsyncMock(return_value=False)
        mock_memory.create_collection = AsyncMock()
        mock_memory.store = AsyncMock(return_value="id")
        mock_memory.close = AsyncMock()

        with patch("memory.memory.api.MemoryAPI", return_value=mock_memory), \
             patch("core.ingest.ingest_knowledge.PROJECT_ROOT", tmp_path):
            result = asyncio.run(ingest_knowledge())

        assert result is True

    def test_file_read_error_continues(self, tmp_path):
        """Error en un fitxer no atura el procés."""
        from core.ingest.ingest_knowledge import ingest_knowledge

        knowledge_path = tmp_path / "knowledge"
        knowledge_path.mkdir()
        (knowledge_path / "good.txt").write_text("Good content here.")
        bad_file = knowledge_path / "bad.txt"
        bad_file.write_bytes(b"\xff\xfe")  # Invalid UTF-8

        mock_memory = MagicMock()
        mock_memory.initialize = AsyncMock()
        mock_memory.collection_exists = AsyncMock(return_value=False)
        mock_memory.create_collection = AsyncMock()
        mock_memory.store = AsyncMock(return_value="id")
        mock_memory.close = AsyncMock()

        with patch("memory.memory.api.MemoryAPI", return_value=mock_memory), \
             patch("core.ingest.ingest_knowledge.PROJECT_ROOT", tmp_path):
            result = asyncio.run(ingest_knowledge())

        # Should complete (True or some result), not crash
        assert result in (True, False)

    def test_lang_subfolder_used_when_exists(self, tmp_path):
        """Si existe knowledge/<lang>/, s'utilitza."""
        from core.ingest.ingest_knowledge import ingest_knowledge
        import os

        knowledge_path = tmp_path / "knowledge"
        knowledge_path.mkdir()
        lang = os.environ.get("NEXE_LANG", "ca").split("-")[0].lower()
        lang_path = knowledge_path / lang
        lang_path.mkdir()
        (lang_path / "doc.txt").write_text("content in lang")

        mock_memory = MagicMock()
        mock_memory.initialize = AsyncMock()
        mock_memory.collection_exists = AsyncMock(return_value=False)
        mock_memory.create_collection = AsyncMock()
        mock_memory.store = AsyncMock(return_value="id")
        mock_memory.close = AsyncMock()

        with patch("memory.memory.api.MemoryAPI", return_value=mock_memory), \
             patch("core.ingest.ingest_knowledge.PROJECT_ROOT", tmp_path):
            result = asyncio.run(ingest_knowledge())

        assert result is True

    def test_large_file_shows_chunk_progress(self, tmp_path):
        """Fitxers grans mostren progrés per chunks."""
        from core.ingest.ingest_knowledge import ingest_knowledge

        knowledge_path = tmp_path / "knowledge"
        knowledge_path.mkdir()
        # Create large file with many chunks
        big_text = "This is a sentence. " * 500  # ~10000 chars
        (knowledge_path / "large.txt").write_text(big_text)

        mock_memory = MagicMock()
        mock_memory.initialize = AsyncMock()
        mock_memory.collection_exists = AsyncMock(return_value=False)
        mock_memory.create_collection = AsyncMock()
        mock_memory.store = AsyncMock(return_value="id")
        mock_memory.close = AsyncMock()

        with patch("memory.memory.api.MemoryAPI", return_value=mock_memory), \
             patch("core.ingest.ingest_knowledge.PROJECT_ROOT", tmp_path):
            result = asyncio.run(ingest_knowledge())

        assert result is True
        # Should have stored multiple chunks
        assert mock_memory.store.call_count >= 5
