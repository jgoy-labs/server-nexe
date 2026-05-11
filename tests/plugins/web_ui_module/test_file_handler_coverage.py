"""Tests for plugins/web_ui_module/core/file_handler.py — coverage gaps."""
import pytest
from pathlib import Path


class TestFileHandler:
    @pytest.fixture
    def handler(self, tmp_path):
        from plugins.web_ui_module.core.file_handler import FileHandler
        return FileHandler(upload_dir=tmp_path)

    def test_init(self, handler):
        assert handler is not None

    def test_chunk_text(self, handler):
        text = "Word " * 200
        chunks = handler.chunk_text(text)
        assert isinstance(chunks, list)
        assert len(chunks) >= 1

    def test_get_uploaded_files_empty(self, handler):
        files = handler.get_uploaded_files()
        assert isinstance(files, list)

    def test_extract_text_txt(self, handler, tmp_path):
        f = tmp_path / "test.txt"
        f.write_text("hello world content")
        text = handler.extract_text(f)
        assert "hello" in text
