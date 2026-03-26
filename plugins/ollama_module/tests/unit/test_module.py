"""
────────────────────────────────────
Server Nexe
Version: 0.8
Author: Jordi Goy
Location: plugins/ollama_module/tests/unit/test_module.py
Description: Tests per plugins/ollama_module/module.py.

www.jgoy.net · https://server-nexe.org
────────────────────────────────────
"""

import asyncio
import pytest
from unittest.mock import AsyncMock, MagicMock, patch


class TestOllamaModuleInit:

    def test_default_base_url(self, monkeypatch):
        monkeypatch.delenv("NEXE_OLLAMA_HOST", raising=False)
        monkeypatch.delenv("OLLAMA_HOST", raising=False)
        from plugins.ollama_module.module import OllamaModule
        m = OllamaModule()
        assert "localhost:11434" in m.base_url

    def test_custom_base_url(self, monkeypatch):
        monkeypatch.setenv("NEXE_OLLAMA_HOST", "http://custom:12345")
        from plugins.ollama_module.module import OllamaModule
        m = OllamaModule()
        assert m.base_url == "http://custom:12345"

    def test_strips_trailing_slash(self, monkeypatch):
        monkeypatch.setenv("NEXE_OLLAMA_HOST", "http://localhost:11434/")
        from plugins.ollama_module.module import OllamaModule
        m = OllamaModule()
        assert not m.base_url.endswith("/")

    def test_env_base_url(self, monkeypatch):
        monkeypatch.setenv("NEXE_OLLAMA_HOST", "http://gpu-server:11434")
        from plugins.ollama_module.module import OllamaModule
        m = OllamaModule()
        assert "gpu-server" in m.base_url

    def test_has_name_and_version(self):
        from plugins.ollama_module.module import OllamaModule
        m = OllamaModule()
        assert m.metadata.name == "ollama_module"
        assert m.metadata.version is not None


class TestTranslationHelper:

    def test_returns_fallback_without_i18n(self):
        from plugins.ollama_module.module import OllamaModule
        m = OllamaModule()
        result = m._t("some.key", "Fallback text")
        assert result == "Fallback text"

    def test_formats_kwargs_in_fallback(self):
        from plugins.ollama_module.module import OllamaModule
        m = OllamaModule()
        result = m._t("some.key", "Count: {count}", count=42)
        assert "42" in result

    def test_uses_i18n_when_available(self):
        from plugins.ollama_module.module import OllamaModule
        mock_i18n = MagicMock()
        mock_i18n.t.return_value = "Translated text"
        m = OllamaModule()
        m.i18n = mock_i18n
        result = m._t("some.key", "Fallback")
        assert result == "Translated text"

    def test_falls_back_when_i18n_returns_key(self):
        from plugins.ollama_module.module import OllamaModule
        mock_i18n = MagicMock()
        mock_i18n.t.return_value = "some.key"  # Same as input = not translated
        m = OllamaModule()
        m.i18n = mock_i18n
        result = m._t("some.key", "Fallback")
        assert result == "Fallback"

    def test_falls_back_when_i18n_raises(self):
        from plugins.ollama_module.module import OllamaModule
        mock_i18n = MagicMock()
        mock_i18n.t.side_effect = Exception("i18n error")
        m = OllamaModule()
        m.i18n = mock_i18n
        result = m._t("some.key", "Fallback")
        assert result == "Fallback"


class TestCheckConnection:

    def test_returns_true_when_connected(self):
        from plugins.ollama_module.module import OllamaModule
        m = OllamaModule()

        mock_response = MagicMock()
        mock_response.status_code = 200

        mock_client = AsyncMock()
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)
        mock_client.get = AsyncMock(return_value=mock_response)

        with patch("plugins.ollama_module.module.httpx.AsyncClient", return_value=mock_client):
            result = asyncio.run(m.check_connection())

        assert result is True

    def test_returns_false_when_not_200(self):
        from plugins.ollama_module.module import OllamaModule
        m = OllamaModule()

        mock_response = MagicMock()
        mock_response.status_code = 503

        mock_client = AsyncMock()
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)
        mock_client.get = AsyncMock(return_value=mock_response)

        with patch("plugins.ollama_module.module.httpx.AsyncClient", return_value=mock_client):
            result = asyncio.run(m.check_connection())

        assert result is False

    def test_returns_false_on_circuit_open(self):
        from plugins.ollama_module.module import OllamaModule
        from core.resilience import CircuitOpenError
        m = OllamaModule()

        mock_client = AsyncMock()
        mock_client.__aenter__ = AsyncMock(side_effect=CircuitOpenError("Circuit open"))
        mock_client.__aexit__ = AsyncMock(return_value=False)

        with patch("plugins.ollama_module.module.httpx.AsyncClient", return_value=mock_client):
            result = asyncio.run(m.check_connection())

        assert result is False


class TestHealthCheck:

    def test_healthy_when_connected(self):
        from plugins.ollama_module.module import OllamaModule
        from core.loader.protocol import HealthStatus
        m = OllamaModule()

        with patch.object(m, "check_connection", AsyncMock(return_value=True)):
            result = asyncio.run(m.health_check())

        assert result.status == HealthStatus.HEALTHY

    def test_unhealthy_when_not_connected(self):
        from plugins.ollama_module.module import OllamaModule
        from core.loader.protocol import HealthStatus
        m = OllamaModule()

        with patch.object(m, "check_connection", AsyncMock(return_value=False)):
            result = asyncio.run(m.health_check())

        assert result.status == HealthStatus.UNHEALTHY

    def test_degraded_on_exception(self):
        from plugins.ollama_module.module import OllamaModule
        from core.loader.protocol import HealthStatus
        m = OllamaModule()

        with patch.object(m, "check_connection", AsyncMock(side_effect=Exception("timeout"))):
            result = asyncio.run(m.health_check())

        assert result.status == HealthStatus.DEGRADED

    def test_unknown_when_httpx_none(self):
        from plugins.ollama_module.module import OllamaModule
        from core.loader.protocol import HealthStatus
        import plugins.ollama_module.module as mod

        m = OllamaModule()
        original = mod.httpx
        try:
            mod.httpx = None
            result = asyncio.run(m.health_check())
        finally:
            mod.httpx = original

        assert result.status == HealthStatus.UNKNOWN


class TestListModels:

    def test_returns_models(self):
        from plugins.ollama_module.module import OllamaModule
        m = OllamaModule()

        mock_response = MagicMock()
        mock_response.raise_for_status = MagicMock()
        mock_response.json.return_value = {"models": [{"name": "llama3"}]}

        mock_client = AsyncMock()
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)
        mock_client.get = AsyncMock(return_value=mock_response)

        with patch("plugins.ollama_module.module.httpx.AsyncClient", return_value=mock_client):
            result = asyncio.run(m.list_models())

        assert len(result) == 1
        assert result[0]["name"] == "llama3"

    def test_empty_models(self):
        from plugins.ollama_module.module import OllamaModule
        m = OllamaModule()

        mock_response = MagicMock()
        mock_response.raise_for_status = MagicMock()
        mock_response.json.return_value = {"models": []}

        mock_client = AsyncMock()
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)
        mock_client.get = AsyncMock(return_value=mock_response)

        with patch("plugins.ollama_module.module.httpx.AsyncClient", return_value=mock_client):
            result = asyncio.run(m.list_models())

        assert result == []
