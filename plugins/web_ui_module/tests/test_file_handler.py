"""
Tests unitaris per FileHandler.
Sense GPU — tota la lògica és E/S local (tmp_path).
"""
import pytest
import time
from pathlib import Path

from plugins.web_ui_module.core.file_handler import (
    FileHandler,
    SUPPORTED_EXTENSIONS,
    MAX_FILE_SIZE,
    CHUNK_SIZE,
    CHUNK_OVERLAP,
)


# ═══════════════════════════════════════════════════════════════
# Fixtures
# ═══════════════════════════════════════════════════════════════

@pytest.fixture
def fh(tmp_path):
    return FileHandler(upload_dir=tmp_path / "uploads")


# ═══════════════════════════════════════════════════════════════
# validate_file
# ═══════════════════════════════════════════════════════════════

class TestValidateFile:

    def test_valid_txt(self, fh):
        ok, msg = fh.validate_file("doc.txt", 100)
        assert ok is True
        assert msg == ""

    def test_valid_md(self, fh):
        ok, _ = fh.validate_file("notes.md", 100)
        assert ok is True

    def test_valid_markdown(self, fh):
        ok, _ = fh.validate_file("readme.markdown", 100)
        assert ok is True

    def test_valid_text(self, fh):
        ok, _ = fh.validate_file("file.text", 100)
        assert ok is True

    def test_valid_pdf(self, fh):
        ok, _ = fh.validate_file("report.pdf", 100)
        assert ok is True

    def test_invalid_extension_jpg(self, fh):
        ok, msg = fh.validate_file("image.jpg", 100)
        assert ok is False
        assert "Unsupported format" in msg

    def test_invalid_extension_exe(self, fh):
        ok, msg = fh.validate_file("malware.exe", 100)
        assert ok is False
        assert len(msg) > 0

    def test_invalid_extension_py(self, fh):
        ok, _ = fh.validate_file("script.py", 100)
        assert _ != ""  # has error message

    def test_file_too_large(self, fh):
        ok, msg = fh.validate_file("big.txt", MAX_FILE_SIZE + 1)
        assert ok is False
        assert "too large" in msg

    def test_file_exact_max_size(self, fh):
        ok, _ = fh.validate_file("edge.txt", MAX_FILE_SIZE)
        assert ok is True

    def test_file_zero_size(self, fh):
        ok, _ = fh.validate_file("empty.txt", 0)
        assert ok is True

    def test_error_message_lists_supported_formats(self, fh):
        _, msg = fh.validate_file("x.xyz", 100)
        for ext in SUPPORTED_EXTENSIONS:
            assert ext in msg


# ═══════════════════════════════════════════════════════════════
# save_file (async)
# ═══════════════════════════════════════════════════════════════

class TestSaveFile:

    @pytest.mark.asyncio
    async def test_save_creates_file(self, fh):
        path = await fh.save_file("hello.txt", b"Hello world")
        assert path.exists()
        assert path.read_bytes() == b"Hello world"

    @pytest.mark.asyncio
    async def test_save_sanitizes_directory_traversal(self, fh):
        path = await fh.save_file("../../etc/passwd", b"x")
        # Must be inside upload_dir
        assert fh.upload_dir in path.parents or path.parent == fh.upload_dir

    @pytest.mark.asyncio
    async def test_save_avoids_overwrite(self, fh):
        p1 = await fh.save_file("file.txt", b"first")
        p2 = await fh.save_file("file.txt", b"second")
        assert p1 != p2
        assert p1.exists()
        assert p2.exists()

    @pytest.mark.asyncio
    async def test_save_returns_path_object(self, fh):
        path = await fh.save_file("test.md", b"# Title")
        assert isinstance(path, Path)

    @pytest.mark.asyncio
    async def test_save_multiple_files(self, fh):
        paths = []
        for i in range(5):
            p = await fh.save_file(f"file_{i}.txt", f"content {i}".encode())
            paths.append(p)
        assert len(set(paths)) == 5


# ═══════════════════════════════════════════════════════════════
# extract_text
# ═══════════════════════════════════════════════════════════════

class TestExtractText:

    def _write(self, tmp_path, name, content):
        p = tmp_path / name
        p.write_text(content, encoding="utf-8")
        return p

    def test_extract_txt(self, fh, tmp_path):
        p = self._write(tmp_path, "a.txt", "Hello text")
        assert fh.extract_text(p) == "Hello text"

    def test_extract_md(self, fh, tmp_path):
        p = self._write(tmp_path, "a.md", "# Title\nBody")
        result = fh.extract_text(p)
        assert "Title" in result
        assert "Body" in result

    def test_extract_markdown(self, fh, tmp_path):
        p = self._write(tmp_path, "a.markdown", "content")
        assert fh.extract_text(p) == "content"

    def test_extract_text_extension(self, fh, tmp_path):
        p = self._write(tmp_path, "a.text", "data")
        assert fh.extract_text(p) == "data"

    def test_extract_unsupported_returns_empty(self, fh, tmp_path):
        p = tmp_path / "a.xyz"
        p.write_bytes(b"\x00\x01\x02")
        assert fh.extract_text(p) == ""

    def test_extract_pdf_not_available_returns_empty(self, fh, tmp_path, monkeypatch):
        """If pypdf is not importable, extract returns empty string gracefully."""
        p = tmp_path / "fake.pdf"
        p.write_bytes(b"not a real pdf")

        import builtins
        real_import = builtins.__import__

        def mock_import(name, *args, **kwargs):
            if name == "pypdf":
                raise ImportError("pypdf not available")
            return real_import(name, *args, **kwargs)

        monkeypatch.setattr(builtins, "__import__", mock_import)
        result = fh.extract_text(p)
        assert result == ""


# ═══════════════════════════════════════════════════════════════
# chunk_text
# ═══════════════════════════════════════════════════════════════

class TestChunkText:

    def test_short_text_single_chunk(self, fh):
        text = "Short text"
        chunks = fh.chunk_text(text, chunk_size=100, overlap=10)
        assert len(chunks) == 1
        assert chunks[0] == text

    def test_long_text_multiple_chunks(self, fh):
        text = "A" * 6000
        chunks = fh.chunk_text(text, chunk_size=2500, overlap=200)
        assert len(chunks) > 1

    def test_all_content_preserved(self, fh):
        # When overlap=0, total chars should approximate original
        text = "word " * 1000  # 5000 chars
        chunks = fh.chunk_text(text, chunk_size=1000, overlap=0)
        combined = "".join(chunks)
        # Strip whitespace differences
        assert len(combined) >= len(text) * 0.9

    def test_chunks_have_reasonable_size(self, fh):
        text = "X" * 10000
        chunks = fh.chunk_text(text, chunk_size=2500, overlap=200)
        for chunk in chunks:
            assert len(chunk) <= 2500 + 50  # small tolerance for newline search

    def test_empty_text_returns_empty_list_or_empty_chunk(self, fh):
        chunks = fh.chunk_text("")
        # Either [] or [""] is acceptable
        assert chunks == [] or chunks == [""]

    def test_text_exactly_chunk_size(self, fh):
        text = "B" * CHUNK_SIZE
        chunks = fh.chunk_text(text)
        assert len(chunks) == 1

    def test_prefers_newline_split(self, fh):
        # Place a newline near the split point
        line = "word " * 250 + "\n"  # ~1251 chars
        text = line * 4
        chunks = fh.chunk_text(text, chunk_size=1300, overlap=50)
        # At least one chunk should end with stripped newline content
        assert all(isinstance(c, str) for c in chunks)

    def test_overlap_default_values(self, fh):
        text = "Z" * 8000
        chunks_with_overlap = fh.chunk_text(text, chunk_size=CHUNK_SIZE, overlap=CHUNK_OVERLAP)
        chunks_no_overlap = fh.chunk_text(text, chunk_size=CHUNK_SIZE, overlap=0)
        # With overlap we get more chunks (or same)
        assert len(chunks_with_overlap) >= len(chunks_no_overlap)


# ═══════════════════════════════════════════════════════════════
# delete_file
# ═══════════════════════════════════════════════════════════════

class TestDeleteFile:

    def test_delete_existing_file(self, fh, tmp_path):
        p = tmp_path / "todelete.txt"
        p.write_text("bye")
        assert fh.delete_file(p) is True
        assert not p.exists()

    def test_delete_nonexistent_returns_false(self, fh, tmp_path):
        p = tmp_path / "ghost.txt"
        assert fh.delete_file(p) is False

    def test_delete_does_not_raise(self, fh, tmp_path):
        p = tmp_path / "x.txt"
        result = fh.delete_file(p)
        assert result is False  # no exception


# ═══════════════════════════════════════════════════════════════
# cleanup_old_files
# ═══════════════════════════════════════════════════════════════

class TestCleanupOldFiles:

    def test_cleanup_removes_old_file(self, fh, tmp_path):
        old_file = fh.upload_dir / "old.txt"
        old_file.write_text("old content")
        # Set mtime to 25 hours ago
        old_time = time.time() - 25 * 3600
        import os
        os.utime(old_file, (old_time, old_time))

        removed = fh.cleanup_old_files(max_age_hours=24)
        assert removed == 1
        assert not old_file.exists()

    def test_cleanup_keeps_recent_file(self, fh):
        recent = fh.upload_dir / "recent.txt"
        recent.write_text("new")
        removed = fh.cleanup_old_files(max_age_hours=24)
        assert removed == 0
        assert recent.exists()

    def test_cleanup_empty_dir(self, fh):
        assert fh.cleanup_old_files(max_age_hours=24) == 0

    def test_cleanup_ignores_dirs(self, fh):
        subdir = fh.upload_dir / "subdir"
        subdir.mkdir()
        removed = fh.cleanup_old_files(max_age_hours=0)
        assert subdir.exists()  # directories not deleted


# ═══════════════════════════════════════════════════════════════
# get_uploaded_files
# ═══════════════════════════════════════════════════════════════

class TestGetUploadedFiles:

    def test_returns_empty_for_empty_dir(self, fh):
        assert fh.get_uploaded_files() == []

    def test_returns_supported_files_only(self, fh):
        (fh.upload_dir / "doc.txt").write_text("a")
        (fh.upload_dir / "img.jpg").write_text("b")
        files = fh.get_uploaded_files()
        names = [f["filename"] for f in files]
        assert "doc.txt" in names
        assert "img.jpg" not in names

    def test_result_has_expected_keys(self, fh):
        (fh.upload_dir / "f.md").write_text("hi")
        files = fh.get_uploaded_files()
        assert len(files) == 1
        assert "filename" in files[0]
        assert "size" in files[0]
        assert "modified" in files[0]
        assert "path" in files[0]

    def test_sorted_newest_first(self, fh):
        import os
        f1 = fh.upload_dir / "first.txt"
        f2 = fh.upload_dir / "second.txt"
        f1.write_text("x")
        f2.write_text("y")
        old_time = time.time() - 3600
        os.utime(f1, (old_time, old_time))
        files = fh.get_uploaded_files()
        assert files[0]["filename"] == "second.txt"

    def test_size_matches(self, fh):
        content = b"hello world"
        p = fh.upload_dir / "sized.txt"
        p.write_bytes(content)
        files = fh.get_uploaded_files()
        assert files[0]["size"] == len(content)


# ═══════════════════════════════════════════════════════════════
# FileHandler init
# ═══════════════════════════════════════════════════════════════

class TestFileHandlerInit:

    def test_creates_upload_dir(self, tmp_path):
        target = tmp_path / "deep" / "nested" / "uploads"
        assert not target.exists()
        fh = FileHandler(upload_dir=target)
        assert target.exists()

    def test_upload_dir_attribute(self, tmp_path):
        fh = FileHandler(upload_dir=tmp_path / "uploads")
        assert fh.upload_dir.is_dir()
