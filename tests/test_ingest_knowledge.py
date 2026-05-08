"""Tests per a les funcions helper extretes d'ingest_knowledge."""
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from core.ingest.ingest_knowledge import (
    _discover_documents,
    _emit_final_summary,
    _ensure_collection,
    _initialize_memory,
    _print_ingestion_header,
    _process_file_batch,
    _resolve_knowledge_path,
    _try_precomputed_kb,
)


# ─── _resolve_knowledge_path ─────────────────────────────────────────────────

class TestResolveKnowledgePath:
    def test_none_folder_returns_project_root_knowledge(self):
        from core.ingest.ingest_knowledge import PROJECT_ROOT
        # Use a lang code that doesn't exist as subfolder
        result = _resolve_knowledge_path(None, "zz")
        assert result == PROJECT_ROOT / "knowledge"

    def test_custom_folder_returned_when_no_lang_subdir(self, tmp_path):
        result = _resolve_knowledge_path(tmp_path, "ca")
        assert result == tmp_path

    def test_lang_subfolder_used_when_exists(self, tmp_path):
        lang_dir = tmp_path / "ca"
        lang_dir.mkdir()
        result = _resolve_knowledge_path(tmp_path, "ca")
        assert result == lang_dir

    def test_lang_file_not_treated_as_dir(self, tmp_path):
        (tmp_path / "ca").write_text("not a directory")
        result = _resolve_knowledge_path(tmp_path, "ca")
        assert result == tmp_path

    def test_other_lang_code_resolved(self, tmp_path):
        lang_dir = tmp_path / "en"
        lang_dir.mkdir()
        result = _resolve_knowledge_path(tmp_path, "en")
        assert result == lang_dir


# ─── _discover_documents ─────────────────────────────────────────────────────

class TestDiscoverDocuments:
    def test_empty_dir_returns_empty_list(self, tmp_path):
        assert _discover_documents(tmp_path) == []

    def test_finds_txt_files(self, tmp_path):
        (tmp_path / "a.txt").write_text("hello")
        result = _discover_documents(tmp_path)
        assert len(result) == 1
        assert result[0].name == "a.txt"

    def test_finds_md_files(self, tmp_path):
        (tmp_path / "note.md").write_text("# Title")
        result = _discover_documents(tmp_path)
        assert any(p.suffix == ".md" for p in result)

    def test_hidden_files_excluded(self, tmp_path):
        (tmp_path / ".hidden.txt").write_text("secret")
        (tmp_path / "visible.txt").write_text("hi")
        result = _discover_documents(tmp_path)
        assert len(result) == 1
        assert result[0].name == "visible.txt"

    def test_pdf_files_included(self, tmp_path):
        (tmp_path / "doc.pdf").write_bytes(b"%PDF-1.4")
        result = _discover_documents(tmp_path)
        assert any(p.suffix == ".pdf" for p in result)

    def test_unsupported_extension_excluded(self, tmp_path):
        (tmp_path / "image.jpg").write_bytes(b"fake")
        result = _discover_documents(tmp_path)
        assert result == []


# ─── _print_ingestion_header ─────────────────────────────────────────────────

class TestPrintIngestionHeader:
    def test_runs_without_error_empty_list(self):
        _print_ingestion_header([])

    def test_runs_without_error_with_files(self, tmp_path):
        files = [tmp_path / "a.txt", tmp_path / "b.md"]
        _print_ingestion_header(files)


# ─── _initialize_memory ──────────────────────────────────────────────────────

class TestInitializeMemory:
    async def test_returns_initialized_instance(self):
        with patch("memory.memory.api.MemoryAPI") as MockMemory:
            instance = MockMemory.return_value
            instance.initialize = AsyncMock()
            result = await _initialize_memory()
            assert result is instance
            instance.initialize.assert_called_once()

    async def test_propagates_initialize_exception(self):
        with patch("memory.memory.api.MemoryAPI") as MockMemory:
            instance = MockMemory.return_value
            instance.initialize = AsyncMock(side_effect=ConnectionError("no server"))
            with pytest.raises(ConnectionError):
                await _initialize_memory()


# ─── _ensure_collection ──────────────────────────────────────────────────────

class TestEnsureCollection:
    async def test_returns_true_when_collection_exists(self):
        memory = MagicMock()
        memory.collection_exists = AsyncMock(return_value=True)
        log = MagicMock()
        result = await _ensure_collection(memory, "test_col", log)
        assert result is True

    async def test_creates_collection_when_missing(self):
        memory = MagicMock()
        memory.collection_exists = AsyncMock(return_value=False)
        memory.create_collection = AsyncMock()
        log = MagicMock()
        result = await _ensure_collection(memory, "test_col", log)
        assert result is True
        memory.create_collection.assert_called_once()

    async def test_returns_false_on_exception(self):
        memory = MagicMock()
        memory.collection_exists = AsyncMock(side_effect=Exception("Qdrant down"))
        log = MagicMock()
        result = await _ensure_collection(memory, "test_col", log)
        assert result is False


# ─── _try_precomputed_kb ─────────────────────────────────────────────────────

class TestTryPrecomputedKb:
    async def test_returns_false_when_kb_does_not_exist(self):
        memory = MagicMock()
        log = MagicMock()
        with patch("core.ingest.ingest_knowledge.PrecomputedKB") as MockKB:
            MockKB.return_value.exists.return_value = False
            result = await _try_precomputed_kb(memory, Path("/fake/root"), "ca", log)
        assert result is False

    async def test_returns_false_on_constructor_exception(self):
        memory = MagicMock()
        log = MagicMock()
        with patch("core.ingest.ingest_knowledge.PrecomputedKB", side_effect=Exception("boom")):
            result = await _try_precomputed_kb(memory, Path("/fake/root"), "ca", log)
        assert result is False
        log.assert_called()

    async def test_returns_false_when_validation_fails(self):
        memory = MagicMock()
        memory.embedding_model = "test-model"
        log = MagicMock()
        with patch("core.ingest.ingest_knowledge.PrecomputedKB") as MockKB:
            kb = MockKB.return_value
            kb.exists.return_value = True
            outcome = MagicMock()
            outcome.ok = False
            outcome.reason = "model mismatch"
            kb.validate.return_value = outcome
            result = await _try_precomputed_kb(memory, Path("/fake/root"), "ca", log)
        assert result is False


# ─── _process_file_batch ─────────────────────────────────────────────────────

class TestProcessFileBatch:
    async def test_empty_files_returns_zero_and_empty_dict(self):
        memory = MagicMock()
        ingest_cfg = MagicMock()
        ingest_cfg.mega_batch = False
        log = MagicMock()
        total, items, _ = await _process_file_batch(memory, [], "col", ingest_cfg, False, log)
        assert total == 0
        assert items == {}

    async def test_mega_batch_accumulates_items(self, tmp_path):
        doc = tmp_path / "test.txt"
        doc.write_text("hello world content for testing")
        memory = MagicMock()
        ingest_cfg = MagicMock()
        ingest_cfg.mega_batch = True
        ingest_cfg.store_batch_size = 10
        log = MagicMock()
        total, items, _ = await _process_file_batch(memory, [doc], "nexe_documentation", ingest_cfg, True, log)
        assert total > 0
        assert len(items) > 0


# ─── _emit_final_summary ─────────────────────────────────────────────────────

class TestEmitFinalSummary:
    def test_calls_log_at_least_four_times(self, tmp_path):
        files = [tmp_path / "a.txt", tmp_path / "b.txt"]
        log = MagicMock()
        _emit_final_summary(files, 10, "nexe_documentation", log)
        assert log.call_count >= 4

    def test_runs_with_empty_files(self):
        log = MagicMock()
        _emit_final_summary([], 0, "nexe_documentation", log)
        assert log.call_count >= 4
