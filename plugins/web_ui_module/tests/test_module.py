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
        assert module.metadata.version == "0.8.0"

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

    def test_chat_calls_api(self, client, auth_headers, monkeypatch):
        """Chat hauria d'intentar cridar l'API."""
        r1 = client.post("/ui/session/new", headers=auth_headers)
        sid = r1.json()["session_id"]

        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {
            "choices": [{"message": {"content": "Test response"}}]
        }

        mock_client = MagicMock()
        mock_client.post = AsyncMock(return_value=mock_resp)
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=None)

        with patch("plugins.web_ui_module.module.httpx.AsyncClient", return_value=mock_client):
            response = client.post(
                "/ui/chat",
                headers=auth_headers,
                json={"message": "Hello!", "session_id": sid}
            )
        assert response.status_code == 200
        data = response.json()
        assert "response" in data


class TestWebUIModuleHelpers:
    """Tests per els mètodes helpers del mòdul."""

    def test_get_api_headers_has_content_type(self, initialized_module, monkeypatch):
        monkeypatch.setenv("NEXE_PRIMARY_API_KEY", "test-key")
        headers = initialized_module._get_api_headers()
        assert "Content-Type" in headers
        assert headers["Content-Type"] == "application/json"

    def test_get_api_headers_includes_api_key(self, initialized_module, monkeypatch):
        monkeypatch.setenv("NEXE_PRIMARY_API_KEY", "my-api-key")
        headers = initialized_module._get_api_headers()
        assert "x-api-key" in headers

    def test_build_chat_payload_has_messages(self, initialized_module):
        session = initialized_module.session_manager.create_session()
        session.add_message("user", "Hello")
        payload = initialized_module._build_chat_payload(session, {})
        assert "messages" in payload
        assert len(payload["messages"]) >= 1

    def test_build_chat_payload_stream_default_false(self, initialized_module):
        session = initialized_module.session_manager.create_session()
        payload = initialized_module._build_chat_payload(session, {})
        assert payload["stream"] is False

    def test_build_chat_payload_stream_true(self, initialized_module):
        session = initialized_module.session_manager.create_session()
        payload = initialized_module._build_chat_payload(session, {"stream": True})
        assert payload["stream"] is True

    def test_build_chat_payload_optional_fields(self, initialized_module):
        session = initialized_module.session_manager.create_session()
        payload = initialized_module._build_chat_payload(session, {
            "engine": "mlx",
            "model": "qwen",
            "temperature": 0.7,
            "max_tokens": 500
        })
        assert payload.get("engine") == "mlx"
        assert payload.get("model") == "qwen"
        assert payload.get("temperature") == 0.7
        assert payload.get("max_tokens") == 500

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

    def test_chat_http_error_propagates(self, client, auth_headers):
        """Chat hauria de gestionar errors HTTP de l'API."""
        r1 = client.post("/ui/session/new", headers=auth_headers)
        sid = r1.json()["session_id"]

        mock_resp = MagicMock()
        mock_resp.status_code = 503
        mock_resp.json.return_value = {"detail": "Service unavailable"}

        mock_client = MagicMock()
        mock_client.post = AsyncMock(return_value=mock_resp)
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=None)

        with patch("plugins.web_ui_module.module.httpx.AsyncClient", return_value=mock_client):
            response = client.post(
                "/ui/chat",
                headers=auth_headers,
                json={"message": "Hello!", "session_id": sid}
            )
        assert response.status_code in (200, 503)

    def test_chat_http_error_text_fallback(self, client, auth_headers):
        """Chat hauria de gestionar errors quan json() falla."""
        r1 = client.post("/ui/session/new", headers=auth_headers)
        sid = r1.json()["session_id"]

        mock_resp = MagicMock()
        mock_resp.status_code = 502
        mock_resp.json.side_effect = Exception("not json")
        mock_resp.text = "Bad Gateway"

        mock_client = MagicMock()
        mock_client.post = AsyncMock(return_value=mock_resp)
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=None)

        with patch("plugins.web_ui_module.module.httpx.AsyncClient", return_value=mock_client):
            response = client.post(
                "/ui/chat",
                headers=auth_headers,
                json={"message": "Hello!", "session_id": sid}
            )
        assert response.status_code in (200, 502)

    def test_initialize_handles_exception(self, monkeypatch):
        """initialize() retorna False si hi ha una excepció."""
        monkeypatch.delenv("NEXE_API_BASE_URL", raising=False)
        mod = WebUIModule()

        with patch.object(mod, '_init_router', side_effect=Exception("Router error")):
            result = asyncio.run(mod.initialize({}))
        assert result is False

    def test_chat_stream_response(self, client, auth_headers):
        """Chat en mode streaming hauria de retornar StreamingResponse."""
        r1 = client.post("/ui/session/new", headers=auth_headers)
        sid = r1.json()["session_id"]

        async def mock_aiter_lines():
            yield "data: {\"choices\": [{\"delta\": {\"content\": \"Hello\"}}]}"
            yield "data: [DONE]"

        mock_stream_resp = MagicMock()
        mock_stream_resp.status_code = 200
        mock_stream_resp.aiter_lines = mock_aiter_lines
        mock_stream_resp.__aenter__ = AsyncMock(return_value=mock_stream_resp)
        mock_stream_resp.__aexit__ = AsyncMock(return_value=None)

        mock_client = MagicMock()
        mock_client.stream = MagicMock(return_value=mock_stream_resp)
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=None)

        with patch("plugins.web_ui_module.module.httpx.AsyncClient", return_value=mock_client):
            response = client.post(
                "/ui/chat",
                headers=auth_headers,
                json={"message": "Hello!", "session_id": sid, "stream": True}
            )
        assert response.status_code == 200
