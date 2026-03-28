"""
────────────────────────────────────
Server Nexe
Author: Jordi Goy
Location: memory/rag/tests/test_endpoints.py
Description: Tests unitaris dels endpoints RAG (upload, search, add_document).

www.jgoy.net · https://server-nexe.org
────────────────────────────────────
"""

import io
import json
import pytest
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

from fastapi import HTTPException
from fastapi.responses import JSONResponse


# ═══════════════════════════════════════════════════════════════════════════
# Helpers
# ═══════════════════════════════════════════════════════════════════════════

def _make_upload_file(filename: str, content: bytes = b"hello world", content_type: str = "text/plain"):
    """Crea un mock d'UploadFile per als tests."""
    mock_file = MagicMock()
    mock_file.filename = filename
    mock_file.content_type = content_type
    mock_file.size = len(content)
    mock_file.read = AsyncMock(return_value=content)
    mock_file.file = io.BytesIO(content)
    return mock_file


# ═══════════════════════════════════════════════════════════════════════════
# Upload endpoint
# ═══════════════════════════════════════════════════════════════════════════

class TestUploadFileEndpoint:
    """Tests de l'endpoint d'upload de fitxers al RAG."""

    @pytest.mark.asyncio
    async def test_upload_invalid_extension_raises_400(self):
        """Verifica que .exe és rebutjat amb 400."""
        from memory.rag.routers.endpoints import upload_file_endpoint

        mock_file = _make_upload_file("malware.exe")

        with pytest.raises(HTTPException) as exc_info:
            await upload_file_endpoint(file=mock_file, metadata="{}")

        assert exc_info.value.status_code == 400
        assert "not allowed" in exc_info.value.detail.lower() or "ext" in exc_info.value.detail.lower()

    @pytest.mark.asyncio
    async def test_upload_no_extension_raises_400(self):
        """Verifica que fitxer sense extensió és rebutjat."""
        from memory.rag.routers.endpoints import upload_file_endpoint

        mock_file = _make_upload_file("noextension")

        with pytest.raises(HTTPException) as exc_info:
            await upload_file_endpoint(file=mock_file, metadata="{}")

        assert exc_info.value.status_code == 400

    @pytest.mark.asyncio
    async def test_upload_path_traversal_filename_sanitized(self):
        """Verifica que path traversal és detectat o sanititzat."""
        from memory.rag.routers.endpoints import upload_file_endpoint

        # ../../etc/passwd té nom base 'passwd' sense extensió → 400
        mock_file = _make_upload_file("../../etc/passwd")

        with pytest.raises(HTTPException) as exc_info:
            await upload_file_endpoint(file=mock_file, metadata="{}")

        assert exc_info.value.status_code == 400

    @pytest.mark.asyncio
    async def test_upload_valid_txt_calls_file_rag(self):
        """Verifica que .txt vàlid arriba a file_rag.add_file."""
        from memory.rag.routers.endpoints import upload_file_endpoint

        mock_file = _make_upload_file("document.txt", b"contingut del document")
        mock_file_rag = AsyncMock()
        mock_file_rag.add_file = AsyncMock(return_value="doc-123")
        mock_file_rag.get_metrics = MagicMock(return_value={
            "total_chunks": 1, "total_documents": 1, "total_vectors": 1
        })

        with patch("memory.rag.routers.endpoints._get_file_rag", return_value=mock_file_rag):
            response = await upload_file_endpoint(file=mock_file, metadata="{}")

        assert response.status_code == 200
        body = json.loads(response.body)
        assert body["success"] is True
        assert body["doc_id"] == "doc-123"

    @pytest.mark.asyncio
    async def test_upload_invalid_metadata_json_ignored(self):
        """Verifica que metadata JSON invàlid no fa petar l'endpoint."""
        from memory.rag.routers.endpoints import upload_file_endpoint

        mock_file = _make_upload_file("doc.txt", b"text")
        mock_file_rag = AsyncMock()
        mock_file_rag.add_file = AsyncMock(return_value="doc-456")
        mock_file_rag.get_metrics = MagicMock(return_value={
            "total_chunks": 1, "total_documents": 1, "total_vectors": 1
        })

        with patch("memory.rag.routers.endpoints._get_file_rag", return_value=mock_file_rag):
            # metadata invàlid → es fa servir {} com a fallback
            response = await upload_file_endpoint(file=mock_file, metadata="{invalid json}")

        assert response.status_code == 200

    @pytest.mark.asyncio
    async def test_upload_file_too_large_raises_413(self):
        """Verifica que fitxer massa gran retorna 413."""
        from memory.rag.routers.endpoints import upload_file_endpoint

        large_content = b"x" * 100
        mock_file = _make_upload_file("big.txt", large_content)
        mock_file.size = 60 * 1024 * 1024  # 60 MB > 50 MB màxim

        with pytest.raises(HTTPException) as exc_info:
            await upload_file_endpoint(file=mock_file, metadata="{}")

        assert exc_info.value.status_code == 413


# ═══════════════════════════════════════════════════════════════════════════
# Search endpoint
# ═══════════════════════════════════════════════════════════════════════════

class TestSearchEndpoint:
    """Tests de l'endpoint de cerca al RAG."""

    @pytest.mark.asyncio
    async def test_search_returns_results(self):
        """Verifica que la cerca retorna resultats."""
        from memory.rag.routers.endpoints import search_endpoint

        mock_result = MagicMock()
        mock_result.doc_id = "doc-1"
        mock_result.chunk_id = "chunk-1"
        mock_result.score = 0.95
        mock_result.text = "contingut rellevant"
        mock_result.metadata = {}

        mock_module = AsyncMock()
        mock_module._initialized = True
        mock_module.search = AsyncMock(return_value=[mock_result])

        with patch("memory.rag.module.RAGModule") as mock_rag_class:
            mock_rag_class.get_instance.return_value = mock_module
            response = await search_endpoint({"query": "cerca test", "top_k": 5})

        assert response.status_code == 200
        body = json.loads(response.body)
        assert body["success"] is True
        assert body["count"] == 1
        assert body["results"][0]["doc_id"] == "doc-1"

    @pytest.mark.asyncio
    async def test_search_empty_results(self):
        """Verifica que cerca sense resultats retorna count 0."""
        from memory.rag.routers.endpoints import search_endpoint

        mock_module = AsyncMock()
        mock_module._initialized = True
        mock_module.search = AsyncMock(return_value=[])

        with patch("memory.rag.module.RAGModule") as mock_rag_class:
            mock_rag_class.get_instance.return_value = mock_module
            response = await search_endpoint({"query": "res aquí"})

        body = json.loads(response.body)
        assert body["count"] == 0
        assert body["results"] == []

    @pytest.mark.asyncio
    async def test_search_error_returns_500(self):
        """Verifica que error intern retorna 500 genèric."""
        from memory.rag.routers.endpoints import search_endpoint

        mock_module = AsyncMock()
        mock_module._initialized = True
        mock_module.search = AsyncMock(side_effect=RuntimeError("DB error intern"))

        with patch("memory.rag.module.RAGModule") as mock_rag_class:
            mock_rag_class.get_instance.return_value = mock_module
            with pytest.raises(HTTPException) as exc_info:
                await search_endpoint({"query": "test"})

        assert exc_info.value.status_code == 500
        # SECURITY: no ha d'exposar detalls interns
        assert "DB error intern" not in exc_info.value.detail


# ═══════════════════════════════════════════════════════════════════════════
# Add document endpoint
# ═══════════════════════════════════════════════════════════════════════════

class TestAddDocumentEndpoint:
    """Tests de l'endpoint d'afegir documents al RAG."""

    @pytest.mark.asyncio
    async def test_add_document_success(self):
        """Verifica que un document vàlid s'afegeix correctament."""
        from memory.rag.routers.endpoints import add_document_endpoint

        mock_module = AsyncMock()
        mock_module._initialized = True
        mock_module.add_document = AsyncMock(return_value="new-doc-id")

        with patch("memory.rag.module.RAGModule") as mock_rag_class:
            mock_rag_class.get_instance.return_value = mock_module
            response = await add_document_endpoint({
                "text": "contingut del document",
                "metadata": {"font": "test"},
                "source": "personality"
            })

        assert response.status_code == 200
        body = json.loads(response.body)
        assert body["success"] is True
        assert body["doc_id"] == "new-doc-id"
        assert body["source"] == "personality"

    @pytest.mark.asyncio
    async def test_add_document_default_source(self):
        """Verifica que el source per defecte és 'personality'."""
        from memory.rag.routers.endpoints import add_document_endpoint

        mock_module = AsyncMock()
        mock_module._initialized = True
        mock_module.add_document = AsyncMock(return_value="doc-default")

        with patch("memory.rag.module.RAGModule") as mock_rag_class:
            mock_rag_class.get_instance.return_value = mock_module
            response = await add_document_endpoint({"text": "text"})

        body = json.loads(response.body)
        assert body["source"] == "personality"

    @pytest.mark.asyncio
    async def test_add_document_error_returns_500_generic(self):
        """Verifica que error intern retorna 500 genèric (no detalls)."""
        from memory.rag.routers.endpoints import add_document_endpoint

        mock_module = AsyncMock()
        mock_module._initialized = True
        mock_module.add_document = AsyncMock(side_effect=Exception("internal crash"))

        with patch("memory.rag.module.RAGModule") as mock_rag_class:
            mock_rag_class.get_instance.return_value = mock_module
            with pytest.raises(HTTPException) as exc_info:
                await add_document_endpoint({"text": "text"})

        assert exc_info.value.status_code == 500
        assert "internal crash" not in exc_info.value.detail


# ═══════════════════════════════════════════════════════════════════════════
# Allowed extensions whitelist
# ═══════════════════════════════════════════════════════════════════════════

class TestAllowedExtensions:
    """Tests de la whitelist d'extensions."""

    def test_whitelist_contains_expected_types(self):
        """Verifica que la whitelist conté els tipus esperats."""
        from memory.rag.routers.endpoints import ALLOWED_UPLOAD_EXTENSIONS
        assert ".txt" in ALLOWED_UPLOAD_EXTENSIONS
        assert ".md" in ALLOWED_UPLOAD_EXTENSIONS
        assert ".pdf" in ALLOWED_UPLOAD_EXTENSIONS
        assert ".csv" in ALLOWED_UPLOAD_EXTENSIONS

    def test_whitelist_excludes_dangerous_types(self):
        """Verifica que tipus perillosos no són a la whitelist."""
        from memory.rag.routers.endpoints import ALLOWED_UPLOAD_EXTENSIONS
        dangerous = {".exe", ".sh", ".bat", ".py", ".js", ".php", ".rb"}
        assert dangerous.isdisjoint(ALLOWED_UPLOAD_EXTENSIONS)
