"""
────────────────────────────────────
Server Nexe
Author: Jordi Goy
Location: core/files/handler.py
Description: Uploaded file handling (upload), shared by every door

www.jgoy.net · https://server-nexe.org
────────────────────────────────────
"""

import logging
from datetime import datetime
from pathlib import Path
from typing import Tuple

from core.files import loaders
from core.files.loaders import MAX_FILE_SIZE  # the doors cap their reads with _fh.MAX_FILE_SIZE (MC-078)
from core.files.loaders.pdf import extract_pdf, looks_glued

logger = logging.getLogger(__name__)

# Supported formats — derived from the loader registry (ADR-008 E3, #1070), the
# one list uploads, the knowledge ingest, the CLI and the web picker agree on.
SUPPORTED_EXTENSIONS = loaders.supported_extensions()
CHUNK_SIZE = 2500  # chars per chunk
CHUNK_OVERLAP = 200  # overlap between chunks for context


class FileHandler:
    """
    File management for web UI uploads.

    Features:
    - Extension validation
    - Size limits
    - Content extraction through the loader registry (core/files/loaders)
    - Temporary storage
    """

    def __init__(self, upload_dir: Path):
        self.upload_dir = Path(upload_dir)
        self.upload_dir.mkdir(parents=True, exist_ok=True)

    def validate_file(self, filename: str, file_size: int, content_bytes: bytes = None) -> Tuple[bool, str]:  # type: ignore[assignment]  # no_implicit_optional
        """
        Validate file before processing

        Args:
            filename: File name
            file_size: Size in bytes
            content_bytes: Content in bytes (for validating magic bytes)

        Returns:
            (valid, error_message)
        """
        ext = Path(filename).suffix.lower()
        loader = loaders.get_loader(filename)

        if loader is None:
            supported = ", ".join(sorted(SUPPORTED_EXTENSIONS))
            return False, f"Unsupported format. Valid formats: {supported}"

        if file_size > MAX_FILE_SIZE:
            max_mb = MAX_FILE_SIZE / (1024 * 1024)
            return False, f"File too large. Maximum: {max_mb}MB"

        # Validate magic bytes (SEC-004): %PDF, the zip header of the Office
        # formats — whatever the registered loader declares.
        if content_bytes and loader.magic is not None:
            if not any(content_bytes.startswith(m) for m in loader.magic):
                logger.warning(f"Magic bytes mismatch for {filename} (ext={ext})")
                return False, f"File content does not match {ext} format"

        # Text formats: the WHOLE content must be UTF-8. Decoding only the
        # first 4096 bytes refused valid text whose multi-byte character
        # straddled byte 4096, and let invalid bytes after it through to an
        # extraction that then raised (measured, ADR-008 E3).
        if content_bytes and loader.is_text:
            try:
                content_bytes.decode("utf-8")
            except UnicodeDecodeError:
                logger.warning(f"Non-UTF-8 content in text file {filename}")
                return False, "File content is not valid UTF-8 text"

        return True, ""

    def _dir_for_today(self) -> Path:
        """The dated folder this upload belongs in: `<root>/<year>/<yyyymmdd>/`.

        Two levels, not three: a year folder so the root does not grow without
        bound, and one folder per DAY named with the whole date, so a folder
        name means something on its own when you are looking at it without its
        parent. The same shape the project's own journal uses.
        """
        today = datetime.now()
        day_dir = self.upload_dir / today.strftime("%Y") / today.strftime("%Y%m%d")
        day_dir.mkdir(parents=True, exist_ok=True)
        return day_dir

    def _iter_files(self):
        """Every uploaded file under the root, dated folders included.

        `iterdir` only saw the flat layout; uploads have lived in
        `<year>/<date>/` since they moved to the storage tree. Walking instead
        of listing keeps the listing and the cleanup honest for both, which
        matters because an install that predates the move still has files
        sitting directly in the root.
        """
        if not self.upload_dir.is_dir():
            return
        for file_path in self.upload_dir.rglob("*"):
            if file_path.is_file():
                yield file_path

    async def save_file(self, filename: str, content: bytes) -> Path:
        """
        Save file to the dated upload folder

        Args:
            filename: File name
            content: Content in bytes

        Returns:
            Path of the saved file
        """
        # Sanitize filename
        safe_filename = Path(filename).name
        target_dir = self._dir_for_today()
        file_path = target_dir / safe_filename

        # Avoid overwrite by adding counter
        counter = 1
        while file_path.exists():
            stem = Path(safe_filename).stem
            ext = Path(safe_filename).suffix
            file_path = target_dir / f"{stem}_{counter}{ext}"
            counter += 1

        # Write file
        file_path.write_bytes(content)
        logger.info(f"File saved: {file_path}")

        return file_path

    def extract_text(self, file_path: Path) -> str:
        """
        Extract text from the file with the loader its extension names

        Args:
            file_path: Path to the file

        Returns:
            Text content; "" for an unsupported extension or a file the
            loader cannot read (the caller turns that into FILE_EXTRACT_FAILED)
        """
        try:
            return loaders.extract_text(file_path)
        except loaders.UnsupportedFormatError:
            return ""
        except Exception as e:
            logger.error(f"Error extracting {file_path.suffix.lower()} text from {file_path.name}: {e}")
            return ""

    # B026 lives in core/files/loaders/pdf.py since ADR-008 E3 (#1070), so the
    # knowledge ingest reads PDFs with it too. Kept here as the names the
    # handler has always answered to.
    _looks_glued = staticmethod(looks_glued)

    def _extract_pdf_sync(self, file_path: Path) -> str:
        """Extract text from PDF (sync, CPU-bound) — see loaders/pdf.py."""
        return extract_pdf(file_path)

    async def extract_text_async(self, file_path: Path) -> str:
        """Extract text in a worker thread — every parser here is CPU-bound."""
        import asyncio
        return await asyncio.to_thread(self.extract_text, file_path)

    def chunk_text(self, text: str, chunk_size: int = CHUNK_SIZE, overlap: int = CHUNK_OVERLAP) -> list:
        """
        Split text into chunks with overlap to maintain context.

        Args:
            text: Text to split
            chunk_size: Maximum size of each chunk
            overlap: Overlap between chunks

        Returns:
            List of chunks
        """
        if len(text) <= chunk_size:
            return [text]

        chunks = []
        start = 0

        while start < len(text):
            end = start + chunk_size

            # Try to cut at a newline or period
            if end < len(text):
                # Find last newline within the chunk
                last_newline = text.rfind('\n', start, end)
                if last_newline > start + chunk_size // 2:
                    end = last_newline + 1
                else:
                    # Find last period
                    last_period = text.rfind('. ', start, end)
                    if last_period > start + chunk_size // 2:
                        end = last_period + 2

            chunk = text[start:end].strip()
            if chunk:
                chunks.append(chunk)

            # Advance with overlap
            start = end - overlap if end < len(text) else len(text)

        avg = sum(len(c) for c in chunks) // len(chunks) if chunks else 0
        logger.info(f"Chunking: {len(chunks)} chunks (avg {avg} chars, overlap={overlap})")
        return chunks

    def delete_file(self, file_path: Path) -> bool:
        """
        Delete temporary file

        Args:
            file_path: Path to the file

        Returns:
            True if deleted successfully
        """
        try:
            if file_path.exists():
                file_path.unlink()
                logger.info(f"File deleted: {file_path}")
                return True
        except Exception as e:
            logger.error(f"Error deleting file: {e}")

        return False

    def cleanup_old_files(self, max_age_hours: int = 24) -> int:
        """
        Clean up old temporary files

        Args:
            max_age_hours: Maximum age of files in hours

        Returns:
            Number of deleted files
        """
        import time

        deleted_count = 0
        current_time = time.time()
        max_age_seconds = max_age_hours * 3600

        try:
            for file_path in self._iter_files():
                file_age = current_time - file_path.stat().st_mtime
                if file_age > max_age_seconds:
                    try:
                        file_path.unlink()
                        deleted_count += 1
                        logger.info(f"Cleaned up old file: {file_path.name}")
                    except Exception as e:
                        logger.error(f"Error deleting {file_path}: {e}")
        except Exception as e:
            logger.error(f"Error during cleanup: {e}")

        if deleted_count > 0:
            logger.info(f"Cleanup completed: {deleted_count} files deleted")
            self._prune_empty_dated_dirs()

        return deleted_count

    def _prune_empty_dated_dirs(self) -> None:
        """Remove the dated folders the cleanup just emptied (#1065).

        Without this the tree keeps one empty directory per day for ever — a
        folder a year later has 365 empty children and the layout stops being
        the tidy thing it was introduced to be. Deepest first, so a year folder
        goes once its last day does. Never the root, and never a folder that
        still holds anything.
        """
        try:
            dirs = sorted(
                (p for p in self.upload_dir.rglob("*") if p.is_dir()),
                key=lambda p: len(p.parts), reverse=True,
            )
            for d in dirs:
                try:
                    if not any(d.iterdir()):
                        d.rmdir()
                except OSError as e:  # raced, or not empty after all — leave it
                    logger.debug("Could not prune %s: %s", d, e)
        except Exception as e:
            logger.debug("Pruning empty upload folders failed: %s", e)

    def get_uploaded_files(self) -> list:
        """
        List all uploaded files

        Returns:
            List of dictionaries with file info
        """
        files = []
        try:
            for file_path in self._iter_files():
                if file_path.suffix.lower() in SUPPORTED_EXTENSIONS:
                    stat = file_path.stat()
                    files.append({
                        "filename": file_path.name,
                        "size": stat.st_size,
                        "modified": stat.st_mtime,
                        # Which dated folder it is in (#1065). The flat layout used
                        # to make `filename` unique by itself — `save_file` adds a
                        # `_1` suffix on a clash — but that uniqueness is per FOLDER,
                        # and folders are per day now. Two uploads of `informe.pdf`
                        # on different days are two different files with one name,
                        # and without this a caller cannot tell the rows apart.
                        # A relative folder name, never the absolute path: that
                        # would leak the OS username and the filesystem layout.
                        "day": file_path.parent.name if file_path.parent != self.upload_dir else "",
                    })
            # Sort by modified time descending (newest first)
            files.sort(key=lambda x: x["modified"], reverse=True)  # type: ignore[arg-type, return-value]  # lambda x["modified"]: float — dict[str,object] però "modified" sempre float
        except Exception as e:
            logger.error(f"Error listing files: {e}")
        return files


__all__ = ["FileHandler"]
