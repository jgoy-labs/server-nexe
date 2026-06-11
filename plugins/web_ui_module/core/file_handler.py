"""
────────────────────────────────────
Server Nexe
Author: Jordi Goy
Location: plugins/web_ui_module/file_handler.py
Description: Uploaded file handling (upload) for the web UI

www.jgoy.net · https://server-nexe.org
────────────────────────────────────
"""

import logging
from pathlib import Path
from typing import Tuple

logger = logging.getLogger(__name__)

# Supported formats (in sync with core/ingest/ingest_knowledge.py)
SUPPORTED_EXTENSIONS = {".txt", ".md", ".markdown", ".text", ".pdf"}
MAX_FILE_SIZE = 10 * 1024 * 1024  # 10MB

# Magic bytes for MIME validation (SEC-004)
MAGIC_BYTES = {
    ".pdf": [b"%PDF"],
    ".txt": None,    # text — validated via UTF-8 decode
    ".md": None,
    ".markdown": None,
    ".text": None,
}
CHUNK_SIZE = 2500  # chars per chunk
CHUNK_OVERLAP = 200  # overlap between chunks for context


class FileHandler:
    """
    File management for web UI uploads.

    Features:
    - Extension validation
    - Size limits
    - Content extraction (txt, md, pdf)
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

        if ext not in SUPPORTED_EXTENSIONS:
            supported = ", ".join(SUPPORTED_EXTENSIONS)
            return False, f"Unsupported format. Valid formats: {supported}"

        if file_size > MAX_FILE_SIZE:
            max_mb = MAX_FILE_SIZE / (1024 * 1024)
            return False, f"File too large. Maximum: {max_mb}MB"

        # Validate magic bytes (SEC-004)
        if content_bytes and ext in MAGIC_BYTES and MAGIC_BYTES[ext] is not None:
            valid_magic = any(content_bytes[:len(m)] == m for m in MAGIC_BYTES[ext])  # type: ignore[union-attr]  # FP: mypy does not narrow subscript post-is-not-None check (L72 already checks MAGIC_BYTES[ext] is not None)
            if not valid_magic:
                logger.warning(f"Magic bytes mismatch for {filename} (ext={ext})")
                return False, f"File content does not match {ext} format"

        # Text files: verify UTF-8 decodable
        if content_bytes and ext in {".txt", ".md", ".markdown", ".text"}:
            try:
                content_bytes[:4096].decode("utf-8")
            except UnicodeDecodeError:
                logger.warning(f"Non-UTF-8 content in text file {filename}")
                return False, "File content is not valid UTF-8 text"

        return True, ""

    async def save_file(self, filename: str, content: bytes) -> Path:
        """
        Save file to the temporary directory

        Args:
            filename: File name
            content: Content in bytes

        Returns:
            Path of the saved file
        """
        # Sanitize filename
        safe_filename = Path(filename).name
        file_path = self.upload_dir / safe_filename

        # Avoid overwrite by adding counter
        counter = 1
        while file_path.exists():
            stem = Path(safe_filename).stem
            ext = Path(safe_filename).suffix
            file_path = self.upload_dir / f"{stem}_{counter}{ext}"
            counter += 1

        # Write file
        file_path.write_bytes(content)
        logger.info(f"File saved: {file_path}")

        return file_path

    def extract_text(self, file_path: Path) -> str:
        """
        Extract text from the file according to its format

        Args:
            file_path: Path to the file

        Returns:
            Text content
        """
        ext = file_path.suffix.lower()

        if ext in {".txt", ".md", ".markdown", ".text"}:
            return file_path.read_text(encoding="utf-8")

        elif ext == ".pdf":
            try:
                return self._extract_pdf_sync(file_path)
            except Exception as e:
                logger.error(f"Error extracting PDF: {e}")
                return ""

        return ""

    @staticmethod
    def _looks_glued(text: str) -> bool:
        """B026: detect pypdf output that lost inter-word spaces.

        PDFs with non-standard font encodings come out as
        'véroInecesitatuempresahoymismo' — normal prose has ~15% spaces,
        glued text has almost none. Short texts are not judged (tables,
        headers and code pages legitimately have few spaces).
        """
        stripped = text.strip()
        if len(stripped) < 200:
            return False
        space_ratio = stripped.count(" ") / len(stripped)
        return space_ratio < 0.05

    def _extract_pdf_sync(self, file_path: Path) -> str:
        """Extract text from PDF (sync, CPU-bound).

        B026: pypdf's default extraction loses inter-word spaces and breaks
        ligatures on PDFs with non-standard encodings, poisoning the RAG index
        with unreadable text. Per page: if the default output looks glued,
        retry with extraction_mode="layout" (reconstructs spacing from glyph
        positions). The whole text is NFKC-normalized at the end — resolves
        ligature codepoints (ﬁ → fi) and recomposes decomposed accents (ı́ → í).
        """
        import re as _re
        import unicodedata as _ud
        from pypdf import PdfReader
        reader = PdfReader(file_path)
        total_pages = len(reader.pages)
        logger.info(f"PDF '{file_path.name}': {total_pages} pages, extracting...")
        pages = []
        relaid_count = 0
        for i, page in enumerate(reader.pages):
            page_text = page.extract_text() or ""
            if self._looks_glued(page_text):
                try:
                    relaid = page.extract_text(extraction_mode="layout") or ""
                    if relaid and not self._looks_glued(relaid):
                        # Layout mode pads columns with spaces — collapse runs.
                        page_text = _re.sub(r"[ \t]{2,}", " ", relaid)
                        relaid_count += 1
                except Exception as e:
                    logger.debug(f"  PDF layout-mode retry failed on page {i + 1}: {e}")
            pages.append(page_text)
            if (i + 1) % 50 == 0:
                logger.info(f"  PDF: {i+1}/{total_pages} pages")
        if relaid_count:
            logger.info(f"PDF '{file_path.name}': {relaid_count} glued page(s) re-extracted in layout mode")
        text = _ud.normalize("NFKC", "\n".join(pages) + "\n")
        logger.info(f"PDF '{file_path.name}': {total_pages} pages -> {len(text)} chars extracted")
        return text

    async def extract_text_async(self, file_path: Path) -> str:
        """Extract text asynchronously (offloads PDF to thread)."""
        import asyncio
        ext = file_path.suffix.lower()
        if ext == ".pdf":
            return await asyncio.to_thread(self._extract_pdf_sync, file_path)
        return self.extract_text(file_path)

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
            for file_path in self.upload_dir.iterdir():
                if file_path.is_file():
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

        return deleted_count

    def get_uploaded_files(self) -> list:
        """
        List all uploaded files

        Returns:
            List of dictionaries with file info
        """
        files = []
        try:
            for file_path in self.upload_dir.iterdir():
                if file_path.is_file() and file_path.suffix.lower() in SUPPORTED_EXTENSIONS:
                    stat = file_path.stat()
                    files.append({
                        "filename": file_path.name,
                        "size": stat.st_size,
                        "modified": stat.st_mtime,
                        # NB: no absolute "path" — it would leak the OS username/FS layout.
                    })
            # Sort by modified time descending (newest first)
            files.sort(key=lambda x: x["modified"], reverse=True)  # type: ignore[arg-type, return-value]  # lambda x["modified"]: float — dict[str,object] però "modified" sempre float
        except Exception as e:
            logger.error(f"Error listing files: {e}")
        return files


__all__ = ["FileHandler"]
