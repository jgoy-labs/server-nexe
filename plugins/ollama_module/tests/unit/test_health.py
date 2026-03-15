"""
────────────────────────────────────
Server Nexe
Version: 0.8
Author: Jordi Goy
Location: plugins/ollama_module/tests/unit/test_health.py
Description: Tests per plugins/ollama_module/health.py.

www.jgoy.net
────────────────────────────────────
"""

import pytest
from unittest.mock import MagicMock, patch


class TestGetHealth:

    def test_healthy_response(self):
        from plugins.ollama_module.health import get_health
        mock_response = MagicMock()
        mock_response.json.return_value = {"models": [{"name": "llama3"}, {"name": "phi3"}]}
        mock_response.raise_for_status = MagicMock()

        mock_client = MagicMock()
        mock_client.__enter__ = MagicMock(return_value=mock_client)
        mock_client.__exit__ = MagicMock(return_value=False)
        mock_client.get.return_value = mock_response

        with patch("plugins.ollama_module.health.httpx.Client", return_value=mock_client):
            result = get_health()

        assert result["status"] == "HEALTHY"
        assert result["connected"] is True
        assert result["models_count"] == 2
        assert result["name"] == "ollama_module"

    def test_unhealthy_connect_error(self):
        import httpx
        from plugins.ollama_module.health import get_health

        mock_client = MagicMock()
        mock_client.__enter__ = MagicMock(return_value=mock_client)
        mock_client.__exit__ = MagicMock(return_value=False)
        mock_client.get.side_effect = httpx.ConnectError("Connection refused")

        with patch("plugins.ollama_module.health.httpx.Client", return_value=mock_client):
            result = get_health()

        assert result["status"] == "UNHEALTHY"
        assert result["connected"] is False
        assert "Cannot connect" in result["error"]

    def test_error_on_generic_exception(self):
        from plugins.ollama_module.health import get_health

        mock_client = MagicMock()
        mock_client.__enter__ = MagicMock(return_value=mock_client)
        mock_client.__exit__ = MagicMock(return_value=False)
        mock_client.get.side_effect = Exception("Unexpected error")

        with patch("plugins.ollama_module.health.httpx.Client", return_value=mock_client):
            result = get_health()

        assert result["status"] == "ERROR"
        assert result["connected"] is False
        assert "Unexpected error" in result["error"]

    def test_no_httpx_returns_degraded(self):
        import plugins.ollama_module.health as health_mod
        original = health_mod.httpx

        try:
            health_mod.httpx = None
            result = health_mod.get_health()
        finally:
            health_mod.httpx = original

        assert result["status"] == "DEGRADED"
        assert result["connected"] is False
        assert "httpx not installed" in result["error"]

    def test_zero_models(self):
        from plugins.ollama_module.health import get_health
        mock_response = MagicMock()
        mock_response.json.return_value = {"models": []}
        mock_response.raise_for_status = MagicMock()

        mock_client = MagicMock()
        mock_client.__enter__ = MagicMock(return_value=mock_client)
        mock_client.__exit__ = MagicMock(return_value=False)
        mock_client.get.return_value = mock_response

        with patch("plugins.ollama_module.health.httpx.Client", return_value=mock_client):
            result = get_health()

        assert result["models_count"] == 0
        assert result["status"] == "HEALTHY"
