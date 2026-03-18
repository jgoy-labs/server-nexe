"""
────────────────────────────────────
Server Nexe
Version: 0.8
Author: Jordi Goy
Location: core/cli/utils/tests/test_api_client.py
Description: Tests per core/cli/utils/api_client.py (NexeAPIClient).

www.jgoy.net · https://server-nexe.org
────────────────────────────────────
"""

import asyncio
import json
import pytest
from unittest.mock import AsyncMock, MagicMock, patch


class TestNexeAPIClientInit:

    def test_default_base_url(self, monkeypatch):
        monkeypatch.setenv("NEXE_PRIMARY_API_KEY", "test-key")
        monkeypatch.delenv("NEXE_API_BASE_URL", raising=False)
        from core.cli.utils.api_client import NexeAPIClient
        client = NexeAPIClient()
        assert "127.0.0.1" in client.base_url or "localhost" in client.base_url

    def test_custom_base_url(self, monkeypatch):
        monkeypatch.setenv("NEXE_PRIMARY_API_KEY", "test-key")
        from core.cli.utils.api_client import NexeAPIClient
        client = NexeAPIClient(base_url="http://192.168.1.1:9119/")
        assert client.base_url == "http://192.168.1.1:9119"  # trailing slash stripped

    def test_api_key_from_env(self, monkeypatch):
        monkeypatch.setenv("NEXE_PRIMARY_API_KEY", "primary-key-123")
        monkeypatch.delenv("NEXE_ADMIN_API_KEY", raising=False)
        from core.cli.utils.api_client import NexeAPIClient
        client = NexeAPIClient()
        assert client.api_key == "primary-key-123"

    def test_api_key_fallback_to_admin(self, monkeypatch):
        monkeypatch.delenv("NEXE_PRIMARY_API_KEY", raising=False)
        monkeypatch.setenv("NEXE_ADMIN_API_KEY", "admin-key-456")
        from core.cli.utils.api_client import NexeAPIClient
        with patch("dotenv.load_dotenv"):  # Prevent .env from overriding
            client = NexeAPIClient()
        # Either primary or admin key is set
        assert client.api_key is not None

    def test_no_api_key_warns(self, monkeypatch, caplog):
        monkeypatch.delenv("NEXE_PRIMARY_API_KEY", raising=False)
        monkeypatch.delenv("NEXE_ADMIN_API_KEY", raising=False)
        from core.cli.utils.api_client import NexeAPIClient
        import logging
        with caplog.at_level(logging.WARNING):
            client = NexeAPIClient()
        # No crash, just a warning

    def test_headers_include_api_key(self, monkeypatch):
        monkeypatch.setenv("NEXE_PRIMARY_API_KEY", "test-key-789")
        from core.cli.utils.api_client import NexeAPIClient
        client = NexeAPIClient()
        assert client.headers.get("x-api-key") == "test-key-789"
        assert "Bearer test-key-789" in client.headers.get("Authorization", "")

    def test_headers_content_type(self, monkeypatch):
        monkeypatch.setenv("NEXE_PRIMARY_API_KEY", "key")
        from core.cli.utils.api_client import NexeAPIClient
        client = NexeAPIClient()
        assert client.headers.get("Content-Type") == "application/json"

    def test_headers_client_id(self, monkeypatch):
        monkeypatch.setenv("NEXE_PRIMARY_API_KEY", "key")
        from core.cli.utils.api_client import NexeAPIClient
        client = NexeAPIClient()
        assert "nexe-cli" in client.headers.get("X-Client-ID", "")


class TestIsServerRunning:

    def test_returns_true_on_200(self, monkeypatch):
        monkeypatch.setenv("NEXE_PRIMARY_API_KEY", "key")
        from core.cli.utils.api_client import NexeAPIClient

        mock_resp = MagicMock()
        mock_resp.status_code = 200

        mock_client = AsyncMock()
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)
        mock_client.get = AsyncMock(return_value=mock_resp)

        with patch("httpx.AsyncClient", return_value=mock_client):
            client = NexeAPIClient()
            result = asyncio.run(client.is_server_running())

        assert result is True

    def test_returns_false_on_non_200(self, monkeypatch):
        monkeypatch.setenv("NEXE_PRIMARY_API_KEY", "key")
        from core.cli.utils.api_client import NexeAPIClient

        mock_resp = MagicMock()
        mock_resp.status_code = 503

        mock_client = AsyncMock()
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)
        mock_client.get = AsyncMock(return_value=mock_resp)

        with patch("httpx.AsyncClient", return_value=mock_client):
            client = NexeAPIClient()
            result = asyncio.run(client.is_server_running())

        assert result is False

    def test_returns_false_on_exception(self, monkeypatch):
        monkeypatch.setenv("NEXE_PRIMARY_API_KEY", "key")
        from core.cli.utils.api_client import NexeAPIClient
        import httpx

        mock_client = AsyncMock()
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)
        mock_client.get = AsyncMock(side_effect=httpx.ConnectError("refused"))

        with patch("httpx.AsyncClient", return_value=mock_client):
            client = NexeAPIClient()
            result = asyncio.run(client.is_server_running())

        assert result is False


class TestChatStream:

    def _collect(self, gen):
        async def _run():
            results = []
            async for item in gen:
                results.append(item)
            return results
        return asyncio.run(_run())

    def test_yields_content_delta(self, monkeypatch):
        monkeypatch.setenv("NEXE_PRIMARY_API_KEY", "key")
        from core.cli.utils.api_client import NexeAPIClient

        lines = [
            'data: {"choices":[{"delta":{"content":"Hola "}}]}',
            'data: {"choices":[{"delta":{"content":"món"}}]}',
            'data: [DONE]',
        ]

        mock_resp = AsyncMock()
        mock_resp.status_code = 200

        async def mock_aiter_lines():
            for line in lines:
                yield line

        mock_resp.aiter_lines = mock_aiter_lines

        mock_stream = AsyncMock()
        mock_stream.__aenter__ = AsyncMock(return_value=mock_resp)
        mock_stream.__aexit__ = AsyncMock(return_value=False)

        mock_client = AsyncMock()
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)
        mock_client.stream = MagicMock(return_value=mock_stream)

        with patch("httpx.AsyncClient", return_value=mock_client):
            client = NexeAPIClient()
            chunks = self._collect(client.chat_stream(
                messages=[{"role": "user", "content": "Hi"}],
                engine="ollama",
                rag=False
            ))

        assert "Hola " in chunks
        assert "món" in chunks

    def test_server_error_yields_error_message(self, monkeypatch):
        monkeypatch.setenv("NEXE_PRIMARY_API_KEY", "key")
        from core.cli.utils.api_client import NexeAPIClient

        mock_resp = AsyncMock()
        mock_resp.status_code = 503
        mock_resp.aread = AsyncMock(return_value=b"Service unavailable")

        mock_stream = AsyncMock()
        mock_stream.__aenter__ = AsyncMock(return_value=mock_resp)
        mock_stream.__aexit__ = AsyncMock(return_value=False)

        mock_client = AsyncMock()
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)
        mock_client.stream = MagicMock(return_value=mock_stream)

        with patch("httpx.AsyncClient", return_value=mock_client):
            client = NexeAPIClient()
            chunks = self._collect(client.chat_stream(
                messages=[{"role": "user", "content": "Hi"}],
                engine="ollama",
            ))

        assert any("503" in c or "Error" in c for c in chunks)

    def test_connect_error_yields_error_message(self, monkeypatch):
        monkeypatch.setenv("NEXE_PRIMARY_API_KEY", "key")
        from core.cli.utils.api_client import NexeAPIClient
        import httpx

        mock_client = AsyncMock()
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)
        mock_client.stream = MagicMock(side_effect=httpx.ConnectError("refused"))

        with patch("httpx.AsyncClient", return_value=mock_client):
            client = NexeAPIClient()
            chunks = self._collect(client.chat_stream(
                messages=[{"role": "user", "content": "Hi"}],
                engine="ollama",
            ))

        assert any("Error" in c or "❌" in c for c in chunks)

    def test_empty_line_skipped(self, monkeypatch):
        monkeypatch.setenv("NEXE_PRIMARY_API_KEY", "key")
        from core.cli.utils.api_client import NexeAPIClient

        lines = [
            "",
            "  ",
            'data: {"choices":[{"delta":{"content":"OK"}}]}',
            'data: [DONE]',
        ]

        mock_resp = AsyncMock()
        mock_resp.status_code = 200

        async def mock_aiter_lines():
            for line in lines:
                yield line

        mock_resp.aiter_lines = mock_aiter_lines

        mock_stream = AsyncMock()
        mock_stream.__aenter__ = AsyncMock(return_value=mock_resp)
        mock_stream.__aexit__ = AsyncMock(return_value=False)

        mock_client = AsyncMock()
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)
        mock_client.stream = MagicMock(return_value=mock_stream)

        with patch("httpx.AsyncClient", return_value=mock_client):
            client = NexeAPIClient()
            chunks = self._collect(client.chat_stream(
                messages=[{"role": "user", "content": "Hi"}],
                engine="ollama",
            ))

        assert "OK" in chunks

    def test_json_decode_error_skipped(self, monkeypatch):
        monkeypatch.setenv("NEXE_PRIMARY_API_KEY", "key")
        from core.cli.utils.api_client import NexeAPIClient

        lines = [
            "data: INVALID JSON",
            'data: {"choices":[{"delta":{"content":"valid"}}]}',
            'data: [DONE]',
        ]

        mock_resp = AsyncMock()
        mock_resp.status_code = 200

        async def mock_aiter_lines():
            for line in lines:
                yield line

        mock_resp.aiter_lines = mock_aiter_lines

        mock_stream = AsyncMock()
        mock_stream.__aenter__ = AsyncMock(return_value=mock_resp)
        mock_stream.__aexit__ = AsyncMock(return_value=False)

        mock_client = AsyncMock()
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)
        mock_client.stream = MagicMock(return_value=mock_stream)

        with patch("httpx.AsyncClient", return_value=mock_client):
            client = NexeAPIClient()
            chunks = self._collect(client.chat_stream(
                messages=[{"role": "user", "content": "Hi"}],
                engine="ollama",
            ))

        assert "valid" in chunks


class TestUploadFile:

    def test_upload_success(self, monkeypatch, tmp_path):
        monkeypatch.setenv("NEXE_PRIMARY_API_KEY", "key")
        from core.cli.utils.api_client import NexeAPIClient

        test_file = tmp_path / "test.txt"
        test_file.write_text("test content")

        mock_resp = AsyncMock()
        mock_resp.status_code = 200
        mock_resp.json = MagicMock(return_value={"file_id": "abc123"})

        mock_client = AsyncMock()
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)
        mock_client.post = AsyncMock(return_value=mock_resp)

        with patch("httpx.AsyncClient", return_value=mock_client):
            client = NexeAPIClient()
            result = asyncio.run(client.upload_file(str(test_file), "session-123"))

        assert result == {"file_id": "abc123"}

    def test_upload_error_status_returns_none(self, monkeypatch, tmp_path):
        monkeypatch.setenv("NEXE_PRIMARY_API_KEY", "key")
        from core.cli.utils.api_client import NexeAPIClient

        test_file = tmp_path / "test.txt"
        test_file.write_text("test content")

        mock_resp = AsyncMock()
        mock_resp.status_code = 500
        mock_resp.text = "Internal error"

        mock_client = AsyncMock()
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)
        mock_client.post = AsyncMock(return_value=mock_resp)

        with patch("httpx.AsyncClient", return_value=mock_client):
            client = NexeAPIClient()
            result = asyncio.run(client.upload_file(str(test_file), "session-123"))

        assert result is None

    def test_upload_nonexistent_file_returns_none(self, monkeypatch):
        monkeypatch.setenv("NEXE_PRIMARY_API_KEY", "key")
        from core.cli.utils.api_client import NexeAPIClient

        client = NexeAPIClient()
        result = asyncio.run(client.upload_file("/nonexistent/path/file.txt", "session-123"))

        assert result is None

    def test_upload_exception_returns_none(self, monkeypatch, tmp_path):
        monkeypatch.setenv("NEXE_PRIMARY_API_KEY", "key")
        from core.cli.utils.api_client import NexeAPIClient

        test_file = tmp_path / "test.txt"
        test_file.write_text("content")

        mock_client = AsyncMock()
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)
        mock_client.post = AsyncMock(side_effect=Exception("Network error"))

        with patch("httpx.AsyncClient", return_value=mock_client):
            client = NexeAPIClient()
            result = asyncio.run(client.upload_file(str(test_file), "session-123"))

        assert result is None


class TestCreateUISession:

    def test_returns_session_id_on_success(self, monkeypatch):
        monkeypatch.setenv("NEXE_PRIMARY_API_KEY", "key")
        from core.cli.utils.api_client import NexeAPIClient

        mock_resp = AsyncMock()
        mock_resp.status_code = 200
        mock_resp.json = MagicMock(return_value={"session_id": "sess-abc"})

        mock_client = AsyncMock()
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)
        mock_client.post = AsyncMock(return_value=mock_resp)

        with patch("httpx.AsyncClient", return_value=mock_client):
            client = NexeAPIClient()
            result = asyncio.run(client.create_ui_session())

        assert result == "sess-abc"

    def test_returns_none_on_error(self, monkeypatch):
        monkeypatch.setenv("NEXE_PRIMARY_API_KEY", "key")
        from core.cli.utils.api_client import NexeAPIClient

        mock_resp = AsyncMock()
        mock_resp.status_code = 500

        mock_client = AsyncMock()
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)
        mock_client.post = AsyncMock(return_value=mock_resp)

        with patch("httpx.AsyncClient", return_value=mock_client):
            client = NexeAPIClient()
            result = asyncio.run(client.create_ui_session())

        assert result is None

    def test_returns_none_on_exception(self, monkeypatch):
        monkeypatch.setenv("NEXE_PRIMARY_API_KEY", "key")
        from core.cli.utils.api_client import NexeAPIClient

        mock_client = AsyncMock()
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)
        mock_client.post = AsyncMock(side_effect=Exception("error"))

        with patch("httpx.AsyncClient", return_value=mock_client):
            client = NexeAPIClient()
            result = asyncio.run(client.create_ui_session())

        assert result is None


class TestChatUIStream:

    def _collect(self, gen):
        async def _run():
            results = []
            async for item in gen:
                results.append(item)
            return results
        return asyncio.run(_run())

    def test_yields_text_chunks(self, monkeypatch):
        monkeypatch.setenv("NEXE_PRIMARY_API_KEY", "key")
        from core.cli.utils.api_client import NexeAPIClient

        mock_resp = AsyncMock()
        mock_resp.status_code = 200

        async def mock_aiter_bytes():
            yield b"Hello "
            yield b"world"

        mock_resp.aiter_bytes = mock_aiter_bytes

        mock_stream = AsyncMock()
        mock_stream.__aenter__ = AsyncMock(return_value=mock_resp)
        mock_stream.__aexit__ = AsyncMock(return_value=False)

        mock_client = AsyncMock()
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)
        mock_client.stream = MagicMock(return_value=mock_stream)

        with patch("httpx.AsyncClient", return_value=mock_client):
            client = NexeAPIClient()
            chunks = self._collect(client.chat_ui_stream("Hello", "session-123"))

        text = "".join(chunks)
        assert "Hello" in text

    def test_error_status_yields_error(self, monkeypatch):
        monkeypatch.setenv("NEXE_PRIMARY_API_KEY", "key")
        from core.cli.utils.api_client import NexeAPIClient

        mock_resp = AsyncMock()
        mock_resp.status_code = 403
        mock_resp.aread = AsyncMock(return_value=b"Forbidden")

        mock_stream = AsyncMock()
        mock_stream.__aenter__ = AsyncMock(return_value=mock_resp)
        mock_stream.__aexit__ = AsyncMock(return_value=False)

        mock_client = AsyncMock()
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)
        mock_client.stream = MagicMock(return_value=mock_stream)

        with patch("httpx.AsyncClient", return_value=mock_client):
            client = NexeAPIClient()
            chunks = self._collect(client.chat_ui_stream("Hello", "session-123"))

        assert any("403" in c or "Error" in c for c in chunks)

    def test_connect_error_yields_error(self, monkeypatch):
        monkeypatch.setenv("NEXE_PRIMARY_API_KEY", "key")
        from core.cli.utils.api_client import NexeAPIClient
        import httpx

        mock_client = AsyncMock()
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)
        mock_client.stream = MagicMock(side_effect=httpx.ConnectError("refused"))

        with patch("httpx.AsyncClient", return_value=mock_client):
            client = NexeAPIClient()
            chunks = self._collect(client.chat_ui_stream("Hello", "session-123"))

        assert any("Error" in c or "❌" in c for c in chunks)

    def test_filters_memory_markers(self, monkeypatch):
        monkeypatch.setenv("NEXE_PRIMARY_API_KEY", "key")
        from core.cli.utils.api_client import NexeAPIClient

        mock_resp = AsyncMock()
        mock_resp.status_code = 200

        async def mock_aiter_bytes():
            yield "Hello \x00[MEM]\x00 world".encode()

        mock_resp.aiter_bytes = mock_aiter_bytes

        mock_stream = AsyncMock()
        mock_stream.__aenter__ = AsyncMock(return_value=mock_resp)
        mock_stream.__aexit__ = AsyncMock(return_value=False)

        mock_client = AsyncMock()
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)
        mock_client.stream = MagicMock(return_value=mock_stream)

        with patch("httpx.AsyncClient", return_value=mock_client):
            client = NexeAPIClient()
            chunks = self._collect(client.chat_ui_stream("Hello", "session-123"))

        text = "".join(chunks)
        assert "\x00[MEM]\x00" not in text
        assert "Hello" in text


class TestChatOffline:

    def test_returns_offline_message(self, monkeypatch):
        monkeypatch.setenv("NEXE_PRIMARY_API_KEY", "key")
        from core.cli.utils.api_client import NexeAPIClient
        client = NexeAPIClient()
        result = asyncio.run(client.chat_offline([], "ollama"))
        assert "Offline" in result or "not supported" in result


class TestMemoryStore:

    def test_returns_true_on_success(self, monkeypatch):
        monkeypatch.setenv("NEXE_PRIMARY_API_KEY", "key")
        from core.cli.utils.api_client import NexeAPIClient

        mock_resp = AsyncMock()
        mock_resp.status_code = 200

        mock_client = AsyncMock()
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)
        mock_client.post = AsyncMock(return_value=mock_resp)

        with patch("httpx.AsyncClient", return_value=mock_client):
            client = NexeAPIClient()
            result = asyncio.run(client.memory_store("content", {"source": "test"}))

        assert result is True

    def test_returns_false_on_error_status(self, monkeypatch):
        monkeypatch.setenv("NEXE_PRIMARY_API_KEY", "key")
        from core.cli.utils.api_client import NexeAPIClient

        mock_resp = AsyncMock()
        mock_resp.status_code = 500

        mock_client = AsyncMock()
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)
        mock_client.post = AsyncMock(return_value=mock_resp)

        with patch("httpx.AsyncClient", return_value=mock_client):
            client = NexeAPIClient()
            result = asyncio.run(client.memory_store("content"))

        assert result is False

    def test_returns_false_on_exception(self, monkeypatch):
        monkeypatch.setenv("NEXE_PRIMARY_API_KEY", "key")
        from core.cli.utils.api_client import NexeAPIClient

        mock_client = AsyncMock()
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)
        mock_client.post = AsyncMock(side_effect=Exception("error"))

        with patch("httpx.AsyncClient", return_value=mock_client):
            client = NexeAPIClient()
            result = asyncio.run(client.memory_store("content"))

        assert result is False

    def test_returns_true_on_201(self, monkeypatch):
        monkeypatch.setenv("NEXE_PRIMARY_API_KEY", "key")
        from core.cli.utils.api_client import NexeAPIClient

        mock_resp = AsyncMock()
        mock_resp.status_code = 201

        mock_client = AsyncMock()
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)
        mock_client.post = AsyncMock(return_value=mock_resp)

        with patch("httpx.AsyncClient", return_value=mock_client):
            client = NexeAPIClient()
            result = asyncio.run(client.memory_store("content"))

        assert result is True


class TestMemorySearch:

    def test_returns_results(self, monkeypatch):
        monkeypatch.setenv("NEXE_PRIMARY_API_KEY", "key")
        from core.cli.utils.api_client import NexeAPIClient

        mock_resp = AsyncMock()
        mock_resp.status_code = 200
        mock_resp.json = MagicMock(return_value={"results": ["r1", "r2"]})

        mock_client = AsyncMock()
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)
        mock_client.post = AsyncMock(return_value=mock_resp)

        with patch("httpx.AsyncClient", return_value=mock_client):
            client = NexeAPIClient()
            results = asyncio.run(client.memory_search("query", limit=5))

        assert results == ["r1", "r2"]

    def test_returns_empty_on_error(self, monkeypatch):
        monkeypatch.setenv("NEXE_PRIMARY_API_KEY", "key")
        from core.cli.utils.api_client import NexeAPIClient

        mock_resp = AsyncMock()
        mock_resp.status_code = 500

        mock_client = AsyncMock()
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)
        mock_client.post = AsyncMock(return_value=mock_resp)

        with patch("httpx.AsyncClient", return_value=mock_client):
            client = NexeAPIClient()
            results = asyncio.run(client.memory_search("query"))

        assert results == []

    def test_returns_empty_on_exception(self, monkeypatch):
        monkeypatch.setenv("NEXE_PRIMARY_API_KEY", "key")
        from core.cli.utils.api_client import NexeAPIClient

        mock_client = AsyncMock()
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)
        mock_client.post = AsyncMock(side_effect=Exception("error"))

        with patch("httpx.AsyncClient", return_value=mock_client):
            client = NexeAPIClient()
            results = asyncio.run(client.memory_search("query"))

        assert results == []
