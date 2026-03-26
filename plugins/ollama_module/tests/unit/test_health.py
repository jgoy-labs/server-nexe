"""
────────────────────────────────────
Server Nexe
Version: 0.8
Author: Jordi Goy
Location: plugins/ollama_module/tests/unit/test_health.py
Description: Tests per plugins/ollama_module/health.py.
             Adapted for async health (get_health_async + sync wrapper).

www.jgoy.net · https://server-nexe.org
────────────────────────────────────
"""

import pytest
from unittest.mock import MagicMock, AsyncMock, patch


class TestGetHealthAsync:
    """Test get_health_async (the async implementation)."""

    @pytest.mark.asyncio
    async def test_healthy_response(self):
        from plugins.ollama_module.health import get_health_async
        mock_response = MagicMock()
        mock_response.json.return_value = {"models": [{"name": "llama3"}, {"name": "phi3"}]}
        mock_response.raise_for_status = MagicMock()

        mock_client = AsyncMock()
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)
        mock_client.get = AsyncMock(return_value=mock_response)

        with patch("plugins.ollama_module.health.httpx.AsyncClient", return_value=mock_client):
            result = await get_health_async()

        assert result["status"] == "HEALTHY"
        assert result["connected"] is True
        assert result["models_count"] == 2
        assert result["name"] == "ollama_module"

    @pytest.mark.asyncio
    async def test_unhealthy_connect_error(self):
        import httpx
        from plugins.ollama_module.health import get_health_async

        mock_client = AsyncMock()
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)
        mock_client.get = AsyncMock(side_effect=httpx.ConnectError("Connection refused"))

        with patch("plugins.ollama_module.health.httpx.AsyncClient", return_value=mock_client):
            result = await get_health_async()

        assert result["status"] == "UNHEALTHY"
        assert result["connected"] is False
        assert "Cannot connect" in result["error"]

    @pytest.mark.asyncio
    async def test_error_on_generic_exception(self):
        from plugins.ollama_module.health import get_health_async

        mock_client = AsyncMock()
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)
        mock_client.get = AsyncMock(side_effect=Exception("Unexpected error"))

        with patch("plugins.ollama_module.health.httpx.AsyncClient", return_value=mock_client):
            result = await get_health_async()

        assert result["status"] == "ERROR"
        assert result["connected"] is False
        assert "Unexpected error" in result["error"]

    @pytest.mark.asyncio
    async def test_no_httpx_returns_degraded(self):
        import plugins.ollama_module.health as health_mod
        original = health_mod.httpx

        try:
            health_mod.httpx = None
            result = await health_mod.get_health_async()
        finally:
            health_mod.httpx = original

        assert result["status"] == "DEGRADED"
        assert result["connected"] is False
        assert "httpx not installed" in result["error"]

    @pytest.mark.asyncio
    async def test_zero_models(self):
        from plugins.ollama_module.health import get_health_async
        mock_response = MagicMock()
        mock_response.json.return_value = {"models": []}
        mock_response.raise_for_status = MagicMock()

        mock_client = AsyncMock()
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)
        mock_client.get = AsyncMock(return_value=mock_response)

        with patch("plugins.ollama_module.health.httpx.AsyncClient", return_value=mock_client):
            result = await get_health_async()

        assert result["models_count"] == 0
        assert result["status"] == "HEALTHY"


class TestGetHealthSync:
    """Test the sync wrapper get_health()."""

    def test_returns_basic_dict_in_event_loop(self):
        """When called from inside a running event loop, returns basic dict."""
        import asyncio
        from plugins.ollama_module.health import get_health

        async def _run():
            return get_health()

        result = asyncio.run(_run())
        assert result["name"] == "ollama_module"
        assert result["status"] == "unknown"
