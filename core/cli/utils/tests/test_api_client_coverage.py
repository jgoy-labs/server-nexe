"""Tests for core/cli/utils/api_client.py — coverage gaps."""
import pytest
from unittest.mock import patch, MagicMock, AsyncMock


class TestNexeAPIClientInit:
    def test_init_with_base_url(self):
        with patch.dict("os.environ", {"NEXE_PRIMARY_API_KEY": "test-key"}):
            from core.cli.utils.api_client import NexeAPIClient
            client = NexeAPIClient(base_url="http://localhost:8000")
        assert client.base_url == "http://localhost:8000"
        assert client.api_key == "test-key"

    def test_init_sets_base_url(self):
        with patch.dict("os.environ", {"NEXE_PRIMARY_API_KEY": "k"}):
            from core.cli.utils.api_client import NexeAPIClient
            client = NexeAPIClient(base_url="http://localhost:8000/")
        assert client.base_url == "http://localhost:8000"

    def test_headers_include_client_id(self):
        with patch.dict("os.environ", {"NEXE_PRIMARY_API_KEY": "k"}):
            from core.cli.utils.api_client import NexeAPIClient
            client = NexeAPIClient(base_url="http://localhost:8000")
        assert "X-Client-ID" in client.headers


class TestIsServerRunning:
    @pytest.mark.asyncio
    async def test_server_running(self):
        with patch.dict("os.environ", {"NEXE_PRIMARY_API_KEY": "k"}):
            from core.cli.utils.api_client import NexeAPIClient
            client = NexeAPIClient(base_url="http://localhost:9999")
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_httpx_client = AsyncMock()
        mock_httpx_client.__aenter__ = AsyncMock(return_value=mock_httpx_client)
        mock_httpx_client.__aexit__ = AsyncMock(return_value=False)
        mock_httpx_client.get = AsyncMock(return_value=mock_resp)
        with patch("core.cli.utils.api_client.httpx.AsyncClient", return_value=mock_httpx_client):
            result = await client.is_server_running()
        assert result is True

    @pytest.mark.asyncio
    async def test_server_not_running(self):
        with patch.dict("os.environ", {"NEXE_PRIMARY_API_KEY": "k"}):
            from core.cli.utils.api_client import NexeAPIClient
            client = NexeAPIClient(base_url="http://localhost:9999")
        mock_httpx_client = AsyncMock()
        mock_httpx_client.__aenter__ = AsyncMock(return_value=mock_httpx_client)
        mock_httpx_client.__aexit__ = AsyncMock(return_value=False)
        mock_httpx_client.get = AsyncMock(side_effect=Exception("Connection refused"))
        with patch("core.cli.utils.api_client.httpx.AsyncClient", return_value=mock_httpx_client):
            result = await client.is_server_running()
        assert result is False
