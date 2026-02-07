"""
────────────────────────────────────
Server Nexe
Version: 0.8
Author: Jordi Goy
Location: plugins/web_ui_module/file_handler.py
Description: Gestió de fitxers pujats (upload) per la UI web

www.jgoy.net
────────────────────────────────────
"""

import logging
from pathlib import Path
from typing import Tuple, Optional

from .i18n import t

logger = logging.getLogger(__name__)

def _t_log(key: str, fallback: str, **kwargs) -> str:
    return t(f"web_ui.logs.{key}", fallback, **kwargs)

# Formats suportats (sync amb core/ingest/ingest_knowledge.py)
SUPPORTED_EXTENSIONS = {".txt", ".md", ".markdown", ".text", ".pdf"}
MAX_FILE_SIZE = 10 * 1024 * 1024  # 10MB
CHUNK_SIZE = 2500  # chars per chunk
CHUNK_OVERLAP = 200  # overlap between chunks for context


class FileHandler:
    """
    Gestió de fitxers pujats per la UI web.

    Característiques:
    - Validació d'extensions
    - Límit de mida
    - Extracció de contingut (txt, md, pdf)
    - Emmagatzematge temporal
    """

    def __init__(self, upload_dir: Path):
        self.upload_dir = Path(upload_dir)
        self.upload_dir.mkdir(parents=True, exist_ok=True)

    def validate_file(self, filename: str, file_size: int) -> Tuple[bool, str]:
        """
        Validar fitxer abans de processar

        Args:
            filename: Nom del fitxer
            file_size: Mida en bytes

        Returns:
            (valid, error_message)
        """
        ext = Path(filename).suffix.lower()

        if ext not in SUPPORTED_EXTENSIONS:
            supported = ", ".join(SUPPORTED_EXTENSIONS)
            return False, t(
                "web_ui.file.unsupported_format",
                "Unsupported format. Valid formats: {supported}",
                supported=supported
            )

        if file_size > MAX_FILE_SIZE:
            max_mb = MAX_FILE_SIZE / (1024 * 1024)
            return False, t(
                "web_ui.file.too_large",
                "File too large. Maximum: {max_mb}MB",
                max_mb=max_mb
            )

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
        logger.info(
            _t_log(
                "file_saved",
                "File saved: {path}",
                path=file_path,
            )
        )

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
                text = ""
                for page in reader.pages:
                    text += page.extract_text() + "\n"
                return text
            except Exception as e:
                logger.error(
                    _t_log(
                        "pdf_extract_error",
                        "Error extracting PDF: {error}",
                        error=str(e),
                    )
                )
                return ""

        return ""

    def chunk_text(self, text: str, chunk_size: int = CHUNK_SIZE, overlap: int = CHUNK_OVERLAP) -> list:
        """
        Dividir text en chunks amb overlap per mantenir context.

        Args:
            text: Text a dividir
            chunk_size: Mida màxima de cada chunk
            overlap: Solapament entre chunks

        Returns:
            Llista de chunks
        """
        if len(text) <= chunk_size:
            return [text]

        chunks = []
        start = 0

        while start < len(text):
            end = start + chunk_size

            # Intentar tallar en un salt de línia o punt
            if end < len(text):
                # Buscar últim salt de línia dins del chunk
                last_newline = text.rfind('\n', start, end)
                if last_newline > start + chunk_size // 2:
                    end = last_newline + 1
                else:
                    # Buscar últim punt
                    last_period = text.rfind('. ', start, end)
                    if last_period > start + chunk_size // 2:
                        end = last_period + 2

            chunk = text[start:end].strip()
            if chunk:
                chunks.append(chunk)

            # Avançar amb overlap
            start = end - overlap if end < len(text) else len(text)

        logger.info(
            _t_log(
                "text_chunked",
                "Text divided into {count} chunks",
                count=len(chunks),
            )
        )
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
                logger.info(
                    _t_log(
                        "file_deleted",
                        "File deleted: {path}",
                        path=file_path,
                    )
                )
                return True
        except Exception as e:
            logger.error(
                _t_log(
                    "file_delete_error",
                    "Error deleting file: {error}",
                    error=str(e),
                )
            )

        return False

    def cleanup_old_files(self, max_age_hours: int = 24) -> int:
        """
        Netejar fitxers temporals antics

        Args:
            max_age_hours: Màxim edat dels fitxers en hores

        Returns:
            Nombre de fitxers eliminats
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
                            logger.info(
                                _t_log(
                                    "cleanup_file",
                                    "Cleaned up old file: {name}",
                                    name=file_path.name,
                                )
                            )
                        except Exception as e:
                            logger.error(
                                _t_log(
                                    "cleanup_delete_error",
                                    "Error deleting {path}: {error}",
                                    path=file_path,
                                    error=str(e),
                                )
                            )
        except Exception as e:
            logger.error(
                _t_log(
                    "cleanup_error",
                    "Error during cleanup: {error}",
                    error=str(e),
                )
            )

        if deleted_count > 0:
            logger.info(
                _t_log(
                    "cleanup_completed",
                    "Cleanup completed: {count} files deleted",
                    count=deleted_count,
                )
            )

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
            logger.error(
                _t_log(
                    "list_files_error",
                    "Error listing files: {error}",
                    error=str(e),
                )
            )
        return files


__all__ = ["FileHandler"]
