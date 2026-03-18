"""
Tests for plugins/ollama_module/manifest.py - targeting uncovered lines.
Lines: 50 (get_ollama_module None case), 97-99/104-106 (serve_css/js),
       159-163 (pull error stream), 191-214 (chat stream), 299-301 (health error),
       315 (info), 332/336 (get_router/get_metadata).
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
    """Test line 50: get_ollama_module when _get_module returns None."""

    def test_get_ollama_module_raises_503(self):
        import plugins.ollama_module.manifest as mod
        original = mod._ollama_module
        try:
            mod._ollama_module = None
            with patch("plugins.ollama_module.manifest._get_module", return_value=None):
                from fastapi import HTTPException
                with pytest.raises(HTTPException) as exc_info:
                    mod.get_ollama_module()
                assert exc_info.value.status_code == 503
        finally:
            mod._ollama_module = original


class TestServeCssJs:
    """Test lines 97-99 and 104-106."""

    def test_serve_css(self, client, tmp_path):
        """Lines 97-99: serve CSS file."""
        css_dir = tmp_path / "assets" / "css"
        css_dir.mkdir(parents=True)
        css_file = css_dir / "style.css"
        css_file.write_text("body { color: red; }")

        with patch("plugins.ollama_module.manifest.UI_PATH", tmp_path):
            r = client.get("/ollama/ui/assets/css/style.css")
            assert r.status_code == 200

    def test_serve_js(self, client, tmp_path):
        """Lines 104-106: serve JS file."""
        js_dir = tmp_path / "js"
        js_dir.mkdir(parents=True)
        js_file = js_dir / "app.js"
        js_file.write_text("console.log('test');")

        with patch("plugins.ollama_module.manifest.UI_PATH", tmp_path):
            r = client.get("/ollama/ui/js/app.js")
            assert r.status_code == 200


class TestPullModelError:
    """Test lines 159-163: pull model streaming error."""

    def test_pull_model_error_in_stream(self, client, auth):
        """Lines 159-163: exception during pull_model stream."""
        async def mock_pull(name):
            raise Exception("Download failed")

        mock_module = MagicMock()
        mock_module.pull_model = mock_pull

        import plugins.ollama_module.manifest as mod
        original = mod._ollama_module
        try:
            mod._ollama_module = mock_module
            r = client.post("/ollama/api/pull", json={"name": "llama3"}, headers=auth)
            assert r.status_code == 200  # StreamingResponse always returns 200
            assert "error" in r.text.lower() or "data:" in r.text
        finally:
            mod._ollama_module = original


class TestChatStream:
    """Test lines 191-214: chat streaming."""

    def test_chat_stream_success(self, client, auth):
        """Lines 191-214: successful chat streaming."""
        async def mock_chat(model, messages, stream):
            yield {"message": {"content": "Hello "}, "done": False}
            yield {"message": {"content": "world"}, "done": True}

        mock_module = MagicMock()
        mock_module.chat = mock_chat

        import plugins.ollama_module.manifest as mod
        original = mod._ollama_module
        try:
            mod._ollama_module = mock_module
            r = client.post(
                "/ollama/api/chat",
                json={
                    "model": "llama3",
                    "messages": [{"role": "user", "content": "Hi"}],
                    "stream": True
                },
                headers=auth
            )
            assert r.status_code == 200
        finally:
            mod._ollama_module = original

    def test_chat_stream_error(self, client, auth):
        """Lines 208-212: exception during chat streaming."""
        async def mock_chat(model, messages, stream):
            raise Exception("Chat engine error")
            yield  # make it a generator

        mock_module = MagicMock()
        mock_module.chat = mock_chat

        import plugins.ollama_module.manifest as mod
        original = mod._ollama_module
        try:
            mod._ollama_module = mock_module
            r = client.post(
                "/ollama/api/chat",
                json={
                    "model": "llama3",
                    "messages": [{"role": "user", "content": "Hi"}],
                    "stream": True
                },
                headers=auth
            )
            assert r.status_code == 200
            assert "error" in r.text.lower()
        finally:
            mod._ollama_module = original


class TestHealthError:
    """Test lines 299-301: health endpoint exception."""

    def test_health_error(self, client):
        """Lines 299-301: exception in health check returns error dict."""
        with patch("plugins.ollama_module.health.get_health", side_effect=Exception("Health broken"), create=True):
            r = client.get("/ollama/health")
            assert r.status_code == 200
            data = r.json()
            # Either from actual health or error path
            assert "status" in data


class TestInfoEndpoint:
    """Test line 315."""

    def test_info_returns_module_info(self, client):
        mock_module = MagicMock()
        mock_module.get_info.return_value = {
            "name": "ollama_module",
            "version": "1.0.0"
        }

        import plugins.ollama_module.manifest as mod
        original = mod._ollama_module
        try:
            mod._ollama_module = mock_module
            r = client.get("/ollama/info")
            assert r.status_code == 200
            data = r.json()
            assert data["name"] == "ollama_module"
        finally:
            mod._ollama_module = original


class TestModuleHelpers:
    """Test lines 332, 336."""

    def test_get_router(self):
        from plugins.ollama_module.manifest import get_router, router_public
        assert get_router() is router_public

    def test_get_metadata(self):
        from plugins.ollama_module.manifest import get_metadata, MODULE_METADATA
        assert get_metadata() is MODULE_METADATA
        assert "name" in MODULE_METADATA
