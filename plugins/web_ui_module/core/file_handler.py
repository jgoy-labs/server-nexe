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
from typing import Tuple, Optional

logger = logging.getLogger(__name__)

# Formats suportats (sync amb core/ingest/ingest_knowledge.py)
SUPPORTED_EXTENSIONS = {".txt", ".md", ".markdown", ".text", ".pdf"}
MAX_FILE_SIZE = 10 * 1024 * 1024  # 10MB

# Magic bytes per validacio MIME (SEC-004)
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

    def validate_file(self, filename: str, file_size: int, content_bytes: bytes = None) -> Tuple[bool, str]:
        """
        Validar fitxer abans de processar

        Args:
            filename: Nom del fitxer
            file_size: Mida en bytes
            content_bytes: Contingut en bytes (per validar magic bytes)

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
            valid_magic = any(content_bytes[:len(m)] == m for m in MAGIC_BYTES[ext])
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
        Desar fitxer al directori temporal

        Args:
            filename: Nom del fitxer
            content: Contingut en bytes

        Returns:
            Path del fitxer desat
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
        Extreure text del fitxer segons el format

        Args:
            file_path: Path al fitxer

        Returns:
            Contingut de text
        """
        ext = file_path.suffix.lower()

        if ext in {".txt", ".md", ".markdown", ".text"}:
            return file_path.read_text(encoding="utf-8")

        elif ext == ".pdf":
            try:
                from pypdf import PdfReader
                reader = PdfReader(file_path)
                total_pages = len(reader.pages)
                logger.info(f"PDF '{file_path.name}': {total_pages} pages, extracting...")
                text = ""
                for i, page in enumerate(reader.pages):
                    text += (page.extract_text() or "") + "\n"
                    if (i + 1) % 50 == 0:
                        logger.info(f"  PDF: {i+1}/{total_pages} pages")
                logger.info(f"PDF '{file_path.name}': {total_pages} pages → {len(text)} chars extracted")
                return text
            except Exception as e:
                logger.error(f"Error extracting PDF: {e}")
                return ""

        return ""

    def _extract_pdf_sync(self, file_path: Path) -> str:
        """Extract text from PDF (sync, CPU-bound)."""
        from pypdf import PdfReader
        reader = PdfReader(file_path)
        total_pages = len(reader.pages)
        logger.info(f"PDF '{file_path.name}': {total_pages} pages, extracting...")
        text = ""
        for i, page in enumerate(reader.pages):
            text += (page.extract_text() or "") + "\n"
            if (i + 1) % 50 == 0:
                logger.info(f"  PDF: {i+1}/{total_pages} pages")
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
        Eliminar fitxer temporal

        Args:
            file_path: Path al fitxer

        Returns:
            True si eliminat correctament
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
        Llistar tots els fitxers pujats

        Returns:
            Llista de diccionaris amb info dels fitxers
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
                        "path": str(file_path)
                    })
            # Sort by modified time descending (newest first)
            files.sort(key=lambda x: x["modified"], reverse=True)
        except Exception as e:
            logger.error(f"Error listing files: {e}")
        return files


__all__ = ["FileHandler"]
