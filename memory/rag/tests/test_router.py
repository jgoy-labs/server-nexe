"""
Tests per memory/rag/router.py
"""
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from unittest.mock import AsyncMock, MagicMock, patch


def make_app():
    app = FastAPI()
    from plugins.security.core.auth import require_api_key
    app.dependency_overrides[require_api_key] = lambda: "test-key"
    from memory.rag.router import router_public
    app.include_router(router_public)
    return app


class TestRAGRouterFunctions:
    def test_get_router(self):
        from memory.rag.router import get_router, router_public
        result = get_router()
        assert result is router_public

    def test_get_metadata(self):
        from memory.rag.router import get_metadata, MODULE_METADATA
        result = get_metadata()
        assert result is MODULE_METADATA
        assert "name" in result
        assert result["name"] == "rag"

    def test_module_metadata_structure(self):
        from memory.rag.router import MODULE_METADATA
        assert "version" in MODULE_METADATA
        assert "description" in MODULE_METADATA
        assert "router" in MODULE_METADATA
        assert MODULE_METADATA["ui_available"] is True


class TestRAGRouterEndpoints:
    def test_health_endpoint(self):
        app = make_app()
        client = TestClient(app, raise_server_exceptions=False)
        # Patchem la funció delegada al router (not endpoints, sino el handler)
        from memory.rag import router as rag_router_module
        with patch.object(rag_router_module, "health_endpoint",
                          new=AsyncMock(return_value={"status": "healthy"})):
            resp = client.get("/rag/health")
        assert resp.status_code in (200, 503)  # 503 si el RAG no és disponible

    def test_info_endpoint(self):
        app = make_app()
        client = TestClient(app, raise_server_exceptions=False)
        resp = client.get("/rag/info")
        assert resp.status_code in (200, 503)
