"""
────────────────────────────────────
Server Nexe
Author: Jordi Goy
Location: memory/rag/tests/test_routers.py
Description: Tests per memory/rag/routers/endpoints.py i ui.py.

www.jgoy.net · https://server-nexe.org
────────────────────────────────────
"""

import asyncio
import json
import pytest
from unittest.mock import AsyncMock, MagicMock, patch


# ─── TestRagEndpoints ─────────────────────────────────────────────────────────

class TestAddDocumentEndpoint:

    def test_adds_document_successfully(self):
        from memory.rag.routers.endpoints import add_document_endpoint

        mock_module = MagicMock()
        mock_module._initialized = True
        mock_module.add_document = AsyncMock(return_value="doc-id-abc")

        mock_request_cls = MagicMock(return_value=MagicMock())

        # Patch at source location since it's a local import
        with patch("memory.rag.module.RAGModule") as mock_cls, \
             patch("memory.rag_sources.base.AddDocumentRequest", mock_request_cls):
            mock_cls.get_instance.return_value = mock_module
            result = asyncio.run(add_document_endpoint({
                "text": "Hello world",
                "metadata": {"source": "test"},
                "source": "personality"
            }))

        assert result.status_code == 200
        data = json.loads(result.body)
        assert data["success"] is True
        assert data["doc_id"] == "doc-id-abc"

    def test_initializes_if_not_initialized(self):
        from memory.rag.routers.endpoints import add_document_endpoint

        mock_module = MagicMock()
        mock_module._initialized = False
        mock_module.initialize = AsyncMock()
        mock_module.add_document = AsyncMock(return_value="doc-id-xyz")

        with patch("memory.rag.module.RAGModule") as mock_cls, \
             patch("memory.rag_sources.base.AddDocumentRequest"):
            mock_cls.get_instance.return_value = mock_module
            asyncio.run(add_document_endpoint({"text": "test"}))

        mock_module.initialize.assert_called_once()

    def test_raises_500_on_error(self):
        from memory.rag.routers.endpoints import add_document_endpoint
        from fastapi import HTTPException

        mock_module = MagicMock()
        mock_module._initialized = True
        mock_module.add_document = AsyncMock(side_effect=Exception("DB error"))

        with patch("memory.rag.module.RAGModule") as mock_cls, \
             patch("memory.rag_sources.base.AddDocumentRequest"):
            mock_cls.get_instance.return_value = mock_module
            with pytest.raises(HTTPException) as exc:
                asyncio.run(add_document_endpoint({"text": "test"}))

        assert exc.value.status_code == 500


class TestSearchEndpoint:

    def test_searches_successfully(self):
        from memory.rag.routers.endpoints import search_endpoint

        mock_result = MagicMock()
        mock_result.doc_id = "doc1"
        mock_result.chunk_id = "chunk1"
        mock_result.score = 0.85
        mock_result.text = "Result text"
        mock_result.metadata = {"source": "test.md"}

        mock_module = MagicMock()
        mock_module._initialized = True
        mock_module.search = AsyncMock(return_value=[mock_result])

        with patch("memory.rag.module.RAGModule") as mock_cls, \
             patch("memory.rag_sources.base.SearchRequest"):
            mock_cls.get_instance.return_value = mock_module
            result = asyncio.run(search_endpoint({
                "query": "test query",
                "top_k": 3
            }))

        data = json.loads(result.body)
        assert "results" in data or "count" in data

    def test_raises_500_on_error(self):
        from memory.rag.routers.endpoints import search_endpoint
        from fastapi import HTTPException

        mock_module = MagicMock()
        mock_module._initialized = True
        mock_module.search = AsyncMock(side_effect=Exception("Search failed"))

        with patch("memory.rag.module.RAGModule") as mock_cls, \
             patch("memory.rag_sources.base.SearchRequest"):
            mock_cls.get_instance.return_value = mock_module
            with pytest.raises(HTTPException) as exc:
                asyncio.run(search_endpoint({"query": "test"}))

        assert exc.value.status_code == 500


class TestHealthEndpoint:

    def test_healthy(self):
        from memory.rag.routers.endpoints import health_endpoint

        mock_module = MagicMock()
        mock_module._initialized = True
        mock_module.get_health = AsyncMock(return_value={"status": "HEALTHY"})

        with patch("memory.rag.module.RAGModule") as mock_cls:
            mock_cls.get_instance.return_value = mock_module
            result = asyncio.run(health_endpoint())

        data = json.loads(result.body)
        assert "status" in data

    def test_returns_unhealthy_on_error(self):
        from memory.rag.routers.endpoints import health_endpoint

        with patch("memory.rag.module.RAGModule") as mock_cls:
            mock_cls.get_instance.side_effect = Exception("Module not found")
            result = asyncio.run(health_endpoint())

        data = json.loads(result.body)
        assert data.get("status") in ("UNHEALTHY", "ERROR") or "error" in data


class TestInfoEndpoint:

    def test_info_returns_data(self):
        from memory.rag.routers.endpoints import info_endpoint

        mock_module = MagicMock()
        mock_module._initialized = True
        mock_module.get_info = MagicMock(return_value={"name": "rag"})

        with patch("memory.rag.module.RAGModule") as mock_cls:
            mock_cls.get_instance.return_value = mock_module
            result = asyncio.run(info_endpoint())

        data = json.loads(result.body)
        assert isinstance(data, dict)


class TestFilesStatsEndpoint:

    def test_files_stats_returns_data(self):
        from memory.rag.routers.endpoints import files_stats_endpoint

        mock_file_rag = MagicMock()
        mock_file_rag.get_metrics.return_value = {
            "total_documents": 2,
            "total_chunks": 10,
            "total_vectors": 10,
        }
        mock_file_rag._documents = {}

        with patch("memory.rag.routers.endpoints._get_file_rag", return_value=mock_file_rag):
            result = asyncio.run(files_stats_endpoint())

        data = json.loads(result.body)
        assert data["total_documents"] == 2


# ─── TestRagUI ────────────────────────────────────────────────────────────────

class TestServeUI:

    def test_returns_placeholder_when_no_file(self):
        from memory.rag.routers.ui import serve_ui

        with patch("memory.rag.routers.ui.UI_PATH") as mock_path:
            index = MagicMock()
            index.exists.return_value = False
            mock_path.__truediv__ = MagicMock(return_value=index)

            result = asyncio.run(serve_ui())

        assert result.status_code == 200

    def test_serves_html_when_file_exists(self, tmp_path):
        from memory.rag.routers.ui import serve_ui

        index = tmp_path / "index.html"
        index.write_text("<html><body>RAG UI</body></html>")

        with patch("memory.rag.routers.ui.UI_PATH", tmp_path):
            result = asyncio.run(serve_ui())

        assert result.status_code == 200
