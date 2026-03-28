"""
────────────────────────────────────
Server Nexe
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


def make_app_with_mock(mock_module):
    """Build app with a mock module instance injected into routes."""
    from plugins.ollama_module.api.routes import create_router
    app = FastAPI()
    router = create_router(mock_module)
    app.include_router(router)
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
        original = mod._module
        try:
            mod._module = None
            with patch("plugins.ollama_module.module.OllamaModule") as mock_cls:
                mock_instance = MagicMock()
                mock_instance._init_router = MagicMock()
                mock_cls.return_value = mock_instance
                result = mod.get_module_instance()
                assert result is mock_instance
        finally:
            mod._module = original

    def test_get_module_instance_caches(self):
        import plugins.ollama_module.manifest as mod
        original = mod._module
        try:
            mock_instance = MagicMock()
            mod._module = mock_instance
            result = mod.get_module_instance()
            assert result is mock_instance
        finally:
            mod._module = original


class TestServeUI:

    def test_returns_404_when_ui_missing(self, auth, tmp_path):
        """UI endpoint returns 404 when index.html does not exist."""
        from plugins.ollama_module.api.routes import create_router
        mock_module = MagicMock()
        # tmp_path exists but has no index.html
        with patch("plugins.ollama_module.api.routes.Path") as MockPath:
            mock_path_inst = MagicMock()
            mock_path_inst.parent.parent.__truediv__ = MagicMock(return_value=tmp_path)
            MockPath.return_value = mock_path_inst
            router = create_router(mock_module)
        app = FastAPI()
        app.include_router(router)
        c = TestClient(app, raise_server_exceptions=False)
        r = c.get("/ollama/ui")
        assert r.status_code == 404

    def test_serves_html_when_file_exists(self, auth, tmp_path):
        index = tmp_path / "index.html"
        index.write_text("<html><body>Ollama UI</body></html>")

        mock_module = MagicMock()
        with patch("plugins.ollama_module.api.routes.Path") as mock_path_cls:
            # Make Path(__file__).parent.parent / "ui" return tmp_path
            mock_file_path = MagicMock()
            mock_file_path.parent = MagicMock()
            mock_file_path.parent.parent = MagicMock()
            mock_file_path.parent.parent.__truediv__ = MagicMock(return_value=tmp_path)
            mock_path_cls.return_value = mock_file_path
            # Re-import won't work; instead patch at create_router level
        # Simpler: patch the open call and exists
        from plugins.ollama_module.api.routes import create_router
        app = FastAPI()
        with patch("plugins.ollama_module.api.routes.Path") as MockPath:
            mock_path_inst = MagicMock()
            mock_path_inst.parent.parent.__truediv__ = MagicMock(return_value=tmp_path)
            MockPath.return_value = mock_path_inst
            router = create_router(mock_module)
        app.include_router(router)
        c = TestClient(app, raise_server_exceptions=False)
        r = c.get("/ollama/ui")

        assert r.status_code == 200
        assert "Ollama UI" in r.text


class TestListModels:

    def test_returns_models(self, auth):
        mock_module = MagicMock()
        mock_module.list_models = AsyncMock(return_value=[
            {"name": "llama3", "size": 4_000_000_000}
        ])

        c = TestClient(make_app_with_mock(mock_module), raise_server_exceptions=False)
        r = c.get("/ollama/api/models")

        assert r.status_code == 200
        data = r.json()
        assert data["status"] == "ok"
        assert data["total"] == 1

    def test_returns_503_on_error(self, auth):
        mock_module = MagicMock()
        mock_module.list_models = AsyncMock(side_effect=Exception("Connection refused"))

        c = TestClient(make_app_with_mock(mock_module), raise_server_exceptions=False)
        r = c.get("/ollama/api/models")

        assert r.status_code == 503


class TestGetModelInfo:

    def test_returns_model_info(self):
        mock_module = MagicMock()
        mock_module.get_model_info = AsyncMock(return_value={
            "modelfile": "FROM llama3",
            "parameters": "",
            "template": ""
        })

        c = TestClient(make_app_with_mock(mock_module), raise_server_exceptions=False)
        r = c.get("/ollama/api/models/llama3/info")

        assert r.status_code == 200
        data = r.json()
        assert data["model"] == "llama3"

    def test_returns_404_on_error(self):
        mock_module = MagicMock()
        mock_module.get_model_info = AsyncMock(side_effect=Exception("Model not found"))

        c = TestClient(make_app_with_mock(mock_module), raise_server_exceptions=False)
        r = c.get("/ollama/api/models/nonexistent/info")

        assert r.status_code == 404


class TestDeleteModel:

    def test_deletes_model(self, auth):
        mock_module = MagicMock()
        mock_module.delete_model = AsyncMock()

        c = TestClient(make_app_with_mock(mock_module), raise_server_exceptions=False)
        r = c.delete("/ollama/api/models/llama3", headers=auth)

        assert r.status_code == 200

    def test_requires_api_key(self):
        mock_module = MagicMock()
        c = TestClient(make_app_with_mock(mock_module), raise_server_exceptions=False)
        r = c.delete("/ollama/api/models/llama3")
        assert r.status_code == 401

    def test_returns_500_when_not_found(self, auth):
        mock_module = MagicMock()
        mock_module.delete_model = AsyncMock(side_effect=Exception("Not found"))

        c = TestClient(make_app_with_mock(mock_module), raise_server_exceptions=False)
        r = c.delete("/ollama/api/models/nonexistent", headers=auth)

        assert r.status_code == 500


class TestHealthEndpoint:

    def test_health_returns_200(self):
        mock_module = MagicMock()
        mock_result = MagicMock()
        mock_result.to_dict.return_value = {"status": "healthy", "connected": True}
        mock_module.health_check = AsyncMock(return_value=mock_result)

        c = TestClient(make_app_with_mock(mock_module), raise_server_exceptions=False)
        r = c.get("/ollama/health")

        assert r.status_code == 200


class TestPullModel:

    def test_pull_requires_api_key(self):
        mock_module = MagicMock()
        c = TestClient(make_app_with_mock(mock_module), raise_server_exceptions=False)
        r = c.post("/ollama/api/pull", json={"name": "llama3"})
        assert r.status_code == 401

    def test_pull_with_auth(self, auth):
        async def mock_pull(name):
            yield {"status": "downloading", "completed": 100, "total": 1000}
            yield {"status": "done", "completed": 1000, "total": 1000}

        mock_module = MagicMock()
        mock_module.pull_model = mock_pull

        c = TestClient(make_app_with_mock(mock_module), raise_server_exceptions=False)
        r = c.post("/ollama/api/pull", json={"name": "llama3"}, headers=auth)

        assert r.status_code == 200
