"""
────────────────────────────────────
Server Nexe
Version: 0.8
Author: Jordi Goy
Location: plugins/ollama_module/tests/unit/test_manifest.py
Description: Tests per plugins/ollama_module/manifest.py.

www.jgoy.net · https://server-nexe.org
────────────────────────────────────
"""

import asyncio
import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from fastapi import FastAPI
from fastapi.testclient import TestClient


def make_app():
    from plugins.ollama_module.manifest import router_public
    app = FastAPI()
    app.include_router(router_public)
    return app


@pytest.fixture(autouse=True)
def set_api_key(monkeypatch):
    monkeypatch.setenv("NEXE_PRIMARY_API_KEY", "test-ollama-key")
    monkeypatch.delenv("NEXE_ADMIN_API_KEY", raising=False)
    monkeypatch.delenv("NEXE_DEV_MODE", raising=False)


@pytest.fixture
def client():
    return TestClient(make_app(), raise_server_exceptions=False)


@pytest.fixture
def auth():
    return {"X-Api-Key": "test-ollama-key"}


class TestGetModuleInstance:

    def test_get_module_instance_returns_module(self):
        import plugins.ollama_module.manifest as mod
        original = mod._ollama_module
        try:
            mod._ollama_module = None
            with patch("plugins.ollama_module.module.OllamaModule") as mock_cls:
                mock_instance = MagicMock()
                mock_cls.return_value = mock_instance
                result = mod.get_module_instance()
                assert result is mock_instance
        finally:
            mod._ollama_module = original

    def test_get_module_instance_caches(self):
        import plugins.ollama_module.manifest as mod
        original = mod._ollama_module
        try:
            mock_instance = MagicMock()
            mod._ollama_module = mock_instance
            result = mod.get_module_instance()
            assert result is mock_instance
        finally:
            mod._ollama_module = original


class TestServeUI:

    def test_returns_404_when_ui_missing(self, client, auth):
        with patch("plugins.ollama_module.manifest.UI_PATH") as mock_path:
            index = MagicMock()
            index.exists.return_value = False
            mock_path.__truediv__ = MagicMock(return_value=index)
            r = client.get("/ollama/ui")
        assert r.status_code == 404

    def test_serves_html_when_file_exists(self, client, auth, tmp_path):
        index = tmp_path / "index.html"
        index.write_text("<html><body>Ollama UI</body></html>")

        with patch("plugins.ollama_module.manifest.UI_PATH", tmp_path):
            r = client.get("/ollama/ui")

        assert r.status_code == 200
        assert "Ollama UI" in r.text


class TestListModels:

    def test_returns_models(self, client, auth):
        mock_module = MagicMock()
        mock_module.list_models = AsyncMock(return_value=[
            {"name": "llama3", "size": 4_000_000_000}
        ])

        import plugins.ollama_module.manifest as mod
        original = mod._ollama_module
        try:
            mod._ollama_module = mock_module
            r = client.get("/ollama/api/models")
        finally:
            mod._ollama_module = original

        assert r.status_code == 200
        data = r.json()
        assert data["status"] == "ok"
        assert data["total"] == 1

    def test_returns_503_on_error(self, client, auth):
        mock_module = MagicMock()
        mock_module.list_models = AsyncMock(side_effect=Exception("Connection refused"))

        import plugins.ollama_module.manifest as mod
        original = mod._ollama_module
        try:
            mod._ollama_module = mock_module
            r = client.get("/ollama/api/models")
        finally:
            mod._ollama_module = original

        assert r.status_code == 503


class TestGetModelInfo:

    def test_returns_model_info(self, client):
        mock_module = MagicMock()
        mock_module.get_model_info = AsyncMock(return_value={
            "modelfile": "FROM llama3",
            "parameters": "",
            "template": ""
        })

        import plugins.ollama_module.manifest as mod
        original = mod._ollama_module
        try:
            mod._ollama_module = mock_module
            r = client.get("/ollama/api/models/llama3/info")
        finally:
            mod._ollama_module = original

        assert r.status_code == 200
        data = r.json()
        assert data["model"] == "llama3"

    def test_returns_404_on_error(self, client):
        mock_module = MagicMock()
        mock_module.get_model_info = AsyncMock(side_effect=Exception("Model not found"))

        import plugins.ollama_module.manifest as mod
        original = mod._ollama_module
        try:
            mod._ollama_module = mock_module
            r = client.get("/ollama/api/models/nonexistent/info")
        finally:
            mod._ollama_module = original

        assert r.status_code == 404


class TestDeleteModel:

    def test_deletes_model(self, client, auth):
        mock_module = MagicMock()
        mock_module.delete_model = AsyncMock()

        import plugins.ollama_module.manifest as mod
        original = mod._ollama_module
        try:
            mod._ollama_module = mock_module
            r = client.delete("/ollama/api/models/llama3", headers=auth)
        finally:
            mod._ollama_module = original

        assert r.status_code == 200

    def test_requires_api_key(self, client):
        r = client.delete("/ollama/api/models/llama3")
        assert r.status_code == 401

    def test_returns_404_when_not_found(self, client, auth):
        mock_module = MagicMock()
        mock_module.delete_model = AsyncMock(side_effect=Exception("Not found"))

        import plugins.ollama_module.manifest as mod
        original = mod._ollama_module
        try:
            mod._ollama_module = mock_module
            r = client.delete("/ollama/api/models/nonexistent", headers=auth)
        finally:
            mod._ollama_module = original

        assert r.status_code in (404, 500)


class TestHealthEndpoint:

    def test_health_returns_200(self, client):
        mock_health = MagicMock(return_value={
            "status": "healthy",
            "connected": True
        })

        with patch("plugins.ollama_module.manifest.get_health", mock_health, create=True):
            r = client.get("/ollama/health")

        assert r.status_code == 200


class TestPullModel:

    def test_pull_requires_api_key(self, client):
        r = client.post("/ollama/api/pull", json={"name": "llama3"})
        assert r.status_code == 401

    def test_pull_with_auth(self, client, auth):
        async def mock_pull(name):
            yield {"status": "downloading", "completed": 100, "total": 1000}
            yield {"status": "done", "completed": 1000, "total": 1000}

        mock_module = MagicMock()
        mock_module.pull_model = mock_pull

        import plugins.ollama_module.manifest as mod
        original = mod._ollama_module
        try:
            mod._ollama_module = mock_module
            r = client.post("/ollama/api/pull", json={"name": "llama3"}, headers=auth)
        finally:
            mod._ollama_module = original

        assert r.status_code == 200
