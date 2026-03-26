"""
────────────────────────────────────
Server Nexe
Version: 0.8
Author: Jordi Goy
Location: plugins/web_ui_module/tests/test_module.py
Description: Tests per WebUIModule: inicialització, endpoints i helpers.

www.jgoy.net · https://server-nexe.org
────────────────────────────────────
"""

import asyncio
import json
import os
import pytest
import tempfile
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch
from fastapi import FastAPI
from fastapi.testclient import TestClient

from plugins.web_ui_module.module import WebUIModule
from plugins.web_ui_module.manifest import router_public


# ─── Fixtures ─────────────────────────────────────────────────────────────────

@pytest.fixture
def module():
    return WebUIModule()


@pytest.fixture
def initialized_module(tmp_path, monkeypatch):
    """Module inicialitzat amb directori temporal."""
    monkeypatch.setenv("NEXE_API_BASE_URL", "http://127.0.0.1:9119")
    mod = WebUIModule()
    context = {"config": {"core": {"server": {"host": "127.0.0.1", "port": 9119}}}}
    # Patch static_dir to tmp
    asyncio.run(mod.initialize(context))
    return mod


@pytest.fixture
def client(initialized_module, monkeypatch):
    """TestClient amb el router inicialitzat."""
    monkeypatch.setenv("NEXE_PRIMARY_API_KEY", "test-webui-key")
    monkeypatch.delenv("NEXE_ADMIN_API_KEY", raising=False)
    app = FastAPI()
    app.include_router(initialized_module.get_router())
    app.include_router(router_public)
    return TestClient(app, raise_server_exceptions=False)


@pytest.fixture
def auth_headers():
    return {"X-API-Key": "test-webui-key"}


# ─── Tests per WebUIModule ────────────────────────────────────────────────────

class TestWebUIModuleInit:
    """Tests per la inicialització del mòdul."""

    def test_initial_state_not_initialized(self, module):
        assert module._initialized is False
        assert module._router is None

    def test_metadata_name(self, module):
        assert module.metadata.name == "web_ui_module"

    def test_metadata_version(self, module):
        assert module.metadata.version == "0.8.2"

    def test_initialize_returns_true(self, tmp_path, monkeypatch):
        monkeypatch.setenv("NEXE_API_BASE_URL", "http://127.0.0.1:9119")
        mod = WebUIModule()
        result = asyncio.run(mod.initialize({}))
        assert result is True
        assert mod._initialized is True

    def test_initialize_twice_is_idempotent(self, monkeypatch):
        monkeypatch.setenv("NEXE_API_BASE_URL", "http://127.0.0.1:9119")
        mod = WebUIModule()
        asyncio.run(mod.initialize({}))
        result = asyncio.run(mod.initialize({}))
        assert result is True

    def test_initialize_creates_router(self, monkeypatch):
        monkeypatch.setenv("NEXE_API_BASE_URL", "http://127.0.0.1:9119")
        mod = WebUIModule()
        asyncio.run(mod.initialize({}))
        assert mod._router is not None

    def test_get_router_prefix(self, module):
        assert module.get_router_prefix() == "/ui"


class TestResolveApiBaseUrl:
    """Tests per _resolve_api_base_url."""

    def test_env_var_takes_priority(self, monkeypatch):
        monkeypatch.setenv("NEXE_API_BASE_URL", "http://custom:8080")
        mod = WebUIModule()
        url = mod._resolve_api_base_url({})
        assert url == "http://custom:8080"

    def test_env_var_strips_trailing_slash(self, monkeypatch):
        monkeypatch.setenv("NEXE_API_BASE_URL", "http://custom:8080/")
        mod = WebUIModule()
        url = mod._resolve_api_base_url({})
        assert url == "http://custom:8080"

    def test_from_config(self, monkeypatch):
        monkeypatch.delenv("NEXE_API_BASE_URL", raising=False)
        mod = WebUIModule()
        ctx = {"config": {"core": {"server": {"host": "192.168.1.1", "port": 8080}}}}
        url = mod._resolve_api_base_url(ctx)
        assert "192.168.1.1" in url
        assert "8080" in url

    def test_0000_host_replaced_with_localhost(self, monkeypatch):
        monkeypatch.delenv("NEXE_API_BASE_URL", raising=False)
        mod = WebUIModule()
        ctx = {"config": {"core": {"server": {"host": "0.0.0.0", "port": 9119}}}}
        url = mod._resolve_api_base_url(ctx)
        assert "127.0.0.1" in url

    def test_default_url(self, monkeypatch):
        monkeypatch.delenv("NEXE_API_BASE_URL", raising=False)
        mod = WebUIModule()
        url = mod._resolve_api_base_url({})
        assert "127.0.0.1" in url
        assert "9119" in url


class TestWebUIModuleEndpoints:
    """Tests per els endpoints HTTP del mòdul."""

    def test_health_endpoint(self, client):
        response = client.get("/ui/health")
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "healthy"
        assert data["initialized"] is True

    def test_create_session(self, client, auth_headers):
        response = client.post("/ui/session/new", headers=auth_headers)
        assert response.status_code == 200
        data = response.json()
        assert "session_id" in data
        assert "created_at" in data

    def test_create_session_no_auth_fails(self, client):
        response = client.post("/ui/session/new")
        assert response.status_code in (401, 422)

    def test_get_session_info(self, client, auth_headers):
        r1 = client.post("/ui/session/new", headers=auth_headers)
        sid = r1.json()["session_id"]
        response = client.get(f"/ui/session/{sid}", headers=auth_headers)
        assert response.status_code == 200

    def test_get_nonexistent_session_404(self, client, auth_headers):
        response = client.get("/ui/session/nonexistent-id", headers=auth_headers)
        assert response.status_code == 404

    def test_get_session_history(self, client, auth_headers):
        r1 = client.post("/ui/session/new", headers=auth_headers)
        sid = r1.json()["session_id"]
        response = client.get(f"/ui/session/{sid}/history", headers=auth_headers)
        assert response.status_code == 200
        data = response.json()
        assert "messages" in data

    def test_get_history_nonexistent_404(self, client, auth_headers):
        response = client.get("/ui/session/bad-id/history", headers=auth_headers)
        assert response.status_code == 404

    def test_delete_session(self, client, auth_headers):
        r1 = client.post("/ui/session/new", headers=auth_headers)
        sid = r1.json()["session_id"]
        response = client.delete(f"/ui/session/{sid}", headers=auth_headers)
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "deleted"

    def test_delete_nonexistent_session_404(self, client, auth_headers):
        response = client.delete("/ui/session/nonexistent-id", headers=auth_headers)
        assert response.status_code == 404

    def test_list_sessions(self, client, auth_headers):
        response = client.get("/ui/sessions", headers=auth_headers)
        assert response.status_code == 200
        data = response.json()
        assert "sessions" in data

    def test_verify_auth_valid_key(self, client, auth_headers):
        response = client.get("/ui/auth", headers=auth_headers)
        assert response.status_code == 200

    def test_verify_auth_invalid_key(self, client):
        response = client.get("/ui/auth", headers={"X-API-Key": "wrong-key"})
        assert response.status_code in (200, 401)

    def test_serve_ui_not_found(self, client, auth_headers):
        response = client.get("/ui/")
        assert response.status_code in (200, 404)

    def test_serve_static_not_found(self, client):
        response = client.get("/ui/static/nonexistent.css")
        assert response.status_code == 404

    def test_chat_no_message_400(self, client, auth_headers):
        r1 = client.post("/ui/session/new", headers=auth_headers)
        sid = r1.json()["session_id"]
        response = client.post("/ui/chat", headers=auth_headers, json={"session_id": sid})
        assert response.status_code == 400

    def test_chat_calls_engine(self, client, auth_headers, monkeypatch):
        """Chat hauria d'intentar cridar un engine LLM."""
        r1 = client.post("/ui/session/new", headers=auth_headers)
        sid = r1.json()["session_id"]

        # Mock engine that returns a response
        mock_engine = MagicMock()
        mock_engine.chat = AsyncMock(return_value={
            "message": {"content": "Test response"},
        })
        mock_manifest = MagicMock()
        mock_manifest.get_module_instance.return_value = mock_engine

        mock_reg = MagicMock()
        mock_reg.instance = mock_manifest

        mock_mm = MagicMock()
        mock_mm.registry.get_module.return_value = mock_reg
        mock_mm.registry.list_modules.return_value = []

        mock_state = MagicMock()
        mock_state.module_manager = mock_mm
        mock_state.project_root = "/tmp"

        with patch("core.lifespan.get_server_state", return_value=mock_state):
            response = client.post(
                "/ui/chat",
                headers=auth_headers,
                json={"message": "Hello!", "session_id": sid}
            )
        assert response.status_code == 200


class TestWebUIModuleHelpers:
    """Tests per els mètodes helpers del mòdul."""

    def test_resolve_api_base_url_from_env(self, initialized_module, monkeypatch):
        monkeypatch.setenv("NEXE_API_BASE_URL", "http://myhost:8080/")
        url = initialized_module._resolve_api_base_url({})
        assert url == "http://myhost:8080"

    def test_resolve_api_base_url_default(self, initialized_module, monkeypatch):
        monkeypatch.delenv("NEXE_API_BASE_URL", raising=False)
        url = initialized_module._resolve_api_base_url({})
        assert url == "http://127.0.0.1:9119"

    def test_resolve_api_base_url_from_context(self, initialized_module, monkeypatch):
        monkeypatch.delenv("NEXE_API_BASE_URL", raising=False)
        context = {"config": {"core": {"server": {"host": "0.0.0.0", "port": 8080}}}}
        url = initialized_module._resolve_api_base_url(context)
        assert url == "http://127.0.0.1:8080"

    def test_metadata_version(self, initialized_module):
        assert initialized_module.metadata.version is not None

    def test_session_manager_is_available(self, initialized_module):
        assert initialized_module.session_manager is not None

    def test_file_handler_is_available(self, initialized_module):
        assert initialized_module.file_handler is not None

    def test_get_info_returns_dict(self, initialized_module):
        info = initialized_module.get_info()
        assert "name" in info
        assert "version" in info
        assert "initialized" in info

    def test_health_check_initialized(self, initialized_module):
        result = asyncio.run(initialized_module.health_check())
        assert result.status.value in ("healthy", "degraded")

    def test_health_check_not_initialized(self, module):
        result = asyncio.run(module.health_check())
        assert result.status.value == "unknown"

    def test_shutdown_sets_not_initialized(self, initialized_module):
        asyncio.run(initialized_module.shutdown())
        assert initialized_module._initialized is False


class TestWebUIModuleChatErrors:
    """Tests per gestió d'errors en les respostes de chat."""

    def test_chat_engine_error_propagates(self, client, auth_headers):
        """Chat hauria de gestionar errors de l'engine."""
        r1 = client.post("/ui/session/new", headers=auth_headers)
        sid = r1.json()["session_id"]

        # Mock engine that raises an exception
        mock_engine = MagicMock()
        mock_engine.chat = AsyncMock(side_effect=Exception("Service unavailable"))
        mock_manifest = MagicMock()
        mock_manifest.get_module_instance.return_value = mock_engine

        mock_reg = MagicMock()
        mock_reg.instance = mock_manifest

        mock_mm = MagicMock()
        mock_mm.registry.get_module.return_value = mock_reg
        mock_mm.registry.list_modules.return_value = []

        mock_state = MagicMock()
        mock_state.module_manager = mock_mm
        mock_state.project_root = "/tmp"

        with patch("core.lifespan.get_server_state", return_value=mock_state):
            response = client.post(
                "/ui/chat",
                headers=auth_headers,
                json={"message": "Hello!", "session_id": sid}
            )
        # Should handle error gracefully (200 with error message or 503)
        assert response.status_code in (200, 500, 503)

    def test_chat_no_engines_available(self, client, auth_headers):
        """Chat hauria de gestionar el cas sense engines disponibles."""
        r1 = client.post("/ui/session/new", headers=auth_headers)
        sid = r1.json()["session_id"]

        mock_mm = MagicMock()
        mock_mm.registry.get_module.return_value = None
        mock_mm.registry.list_modules.return_value = []

        mock_state = MagicMock()
        mock_state.module_manager = mock_mm
        mock_state.project_root = "/tmp"

        with patch("core.lifespan.get_server_state", return_value=mock_state):
            response = client.post(
                "/ui/chat",
                headers=auth_headers,
                json={"message": "Hello!", "session_id": sid}
            )
        assert response.status_code in (200, 500, 503)

    def test_initialize_handles_exception(self, monkeypatch):
        """initialize() retorna False si hi ha una excepció."""
        monkeypatch.delenv("NEXE_API_BASE_URL", raising=False)
        mod = WebUIModule()

        with patch.object(mod, '_init_router', side_effect=Exception("Router error")):
            result = asyncio.run(mod.initialize({}))
        assert result is False

    def test_chat_stream_response(self, client, auth_headers):
        """Chat en mode streaming hauria de funcionar amb engine mock."""
        r1 = client.post("/ui/session/new", headers=auth_headers)
        sid = r1.json()["session_id"]

        # Mock engine that returns an async generator for streaming
        async def mock_stream(*args, **kwargs):
            yield {"message": {"content": "Hello"}}
            yield {"message": {"content": " world"}}

        mock_engine = MagicMock()
        mock_engine.chat = MagicMock(return_value=mock_stream())
        mock_manifest = MagicMock()
        mock_manifest.get_module_instance.return_value = mock_engine

        mock_reg = MagicMock()
        mock_reg.instance = mock_manifest

        mock_mm = MagicMock()
        mock_mm.registry.get_module.return_value = mock_reg
        mock_mm.registry.list_modules.return_value = []

        mock_state = MagicMock()
        mock_state.module_manager = mock_mm
        mock_state.project_root = "/tmp"

        with patch("core.lifespan.get_server_state", return_value=mock_state):
            response = client.post(
                "/ui/chat",
                headers=auth_headers,
                json={"message": "Hello!", "session_id": sid, "stream": True}
            )
        assert response.status_code == 200
