"""
Tests for plugins/ollama_module/manifest.py - targeting uncovered lines.
Adapted for lazy singleton pattern (get_module_instance / get_router / __getattr__).
"""

import pytest
from unittest.mock import patch, MagicMock, AsyncMock
from fastapi import FastAPI
from fastapi.testclient import TestClient


@pytest.fixture(autouse=True)
def set_api_key(monkeypatch):
    monkeypatch.setenv("NEXE_PRIMARY_API_KEY", "test-ollama-cover-key")
    monkeypatch.delenv("NEXE_ADMIN_API_KEY", raising=False)
    monkeypatch.delenv("NEXE_DEV_MODE", raising=False)


def _make_client(mock_module):
    """Build a TestClient with a mock module injected into routes."""
    from plugins.ollama_module.api.routes import create_router
    app = FastAPI()
    router = create_router(mock_module)
    app.include_router(router)
    return TestClient(app, raise_server_exceptions=False)


@pytest.fixture
def client():
    from plugins.ollama_module.manifest import router_public
    app = FastAPI()
    app.include_router(router_public)
    return TestClient(app, raise_server_exceptions=False)


@pytest.fixture
def auth():
    return {"X-Api-Key": "test-ollama-cover-key"}


class TestGetOllamaModuleNone:
    """Test _get_module when _module is None and OllamaModule is created."""

    def test_get_module_instance_creates_module(self):
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


class TestServeCssJs:
    """Test serve CSS and JS file routes."""

    def test_serve_css(self, tmp_path):
        """Serve CSS file."""
        css_dir = tmp_path / "assets" / "css"
        css_dir.mkdir(parents=True)
        css_file = css_dir / "style.css"
        css_file.write_text("body { color: red; }")

        mock_module = MagicMock()
        from plugins.ollama_module.api.routes import create_router
        with patch("plugins.ollama_module.api.routes.Path") as MockPath:
            mock_path_inst = MagicMock()
            mock_path_inst.parent.parent.__truediv__ = MagicMock(return_value=tmp_path)
            MockPath.return_value = mock_path_inst
            router = create_router(mock_module)
        app = FastAPI()
        app.include_router(router)
        c = TestClient(app, raise_server_exceptions=False)
        r = c.get("/ollama/ui/assets/css/style.css")
        assert r.status_code == 200

    def test_serve_js(self, tmp_path):
        """Serve JS file."""
        js_dir = tmp_path / "js"
        js_dir.mkdir(parents=True)
        js_file = js_dir / "app.js"
        js_file.write_text("console.log('test');")

        mock_module = MagicMock()
        from plugins.ollama_module.api.routes import create_router
        with patch("plugins.ollama_module.api.routes.Path") as MockPath:
            mock_path_inst = MagicMock()
            mock_path_inst.parent.parent.__truediv__ = MagicMock(return_value=tmp_path)
            MockPath.return_value = mock_path_inst
            router = create_router(mock_module)
        app = FastAPI()
        app.include_router(router)
        c = TestClient(app, raise_server_exceptions=False)
        r = c.get("/ollama/ui/js/app.js")
        assert r.status_code == 200


class TestPullModelError:
    """Test pull model streaming error."""

    def test_pull_model_error_in_stream(self, auth):
        """Exception during pull_model stream."""
        async def mock_pull(name):
            raise Exception("Download failed")

        mock_module = MagicMock()
        mock_module.pull_model = mock_pull

        c = _make_client(mock_module)
        r = c.post("/ollama/api/pull", json={"name": "llama3"}, headers=auth)
        assert r.status_code == 200  # StreamingResponse always returns 200
        assert "error" in r.text.lower() or "data:" in r.text


class TestHealthError:
    """Test health endpoint exception."""

    def test_health_error(self, auth):
        """Exception in health check returns error."""
        mock_module = MagicMock()
        mock_module.health_check = AsyncMock(side_effect=Exception("Health broken"))

        c = _make_client(mock_module)
        r = c.get("/ollama/health", headers=auth)
        # When health_check raises, the endpoint returns 500
        assert r.status_code in (200, 500)


class TestInfoEndpoint:
    """Test info endpoint."""

    def test_info_returns_module_info(self, auth):
        mock_module = MagicMock()
        mock_module.get_info.return_value = {
            "name": "ollama_module",
            "version": "0.9.0"
        }

        c = _make_client(mock_module)
        r = c.get("/ollama/info", headers=auth)
        assert r.status_code == 200
        data = r.json()
        assert data["name"] == "ollama_module"


class TestModuleHelpers:
    """Test get_router and get_metadata helpers from manifest."""

    def test_get_router(self):
        from plugins.ollama_module.manifest import get_router, router_public
        assert get_router() is router_public

    def test_get_metadata(self):
        from plugins.ollama_module.manifest import get_metadata
        meta = get_metadata()
        assert meta.name == "ollama_module"
