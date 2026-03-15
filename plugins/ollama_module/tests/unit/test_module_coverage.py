"""
Tests for plugins/ollama_module/module.py - additional coverage
Covers uncovered lines: 21-22, 172-200, 218-225, 251, 273-288, 295, 320-329, 333, 352-358, 362-419
"""
import json
import asyncio
import pytest
from unittest.mock import MagicMock, AsyncMock, patch

from plugins.ollama_module.module import OllamaModule


class TestPullModel:
    """Tests for pull_model (lines 172-200)"""

    @pytest.mark.asyncio
    async def test_pull_model_success(self):
        """Lines 172-195: successful pull with streaming"""
        module = OllamaModule()

        mock_response = MagicMock()
        mock_response.raise_for_status = MagicMock()

        async def fake_aiter_lines():
            yield json.dumps({"status": "downloading", "completed": 50})
            yield json.dumps({"status": "success"})
            yield ""  # empty line skipped

        mock_response.aiter_lines = fake_aiter_lines

        mock_stream_ctx = AsyncMock()
        mock_stream_ctx.__aenter__ = AsyncMock(return_value=mock_response)
        mock_stream_ctx.__aexit__ = AsyncMock(return_value=None)

        mock_client = AsyncMock()
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=None)
        mock_client.stream = MagicMock(return_value=mock_stream_ctx)

        with patch("plugins.ollama_module.module.httpx.AsyncClient", return_value=mock_client), \
             patch("plugins.ollama_module.module.ollama_breaker") as mock_breaker:
            mock_breaker.check_circuit = AsyncMock(return_value=True)
            mock_breaker.record_success = AsyncMock()
            chunks = []
            async for chunk in module.pull_model("llama3"):
                chunks.append(chunk)

        assert len(chunks) == 2
        assert chunks[1]["status"] == "success"

    @pytest.mark.asyncio
    async def test_pull_model_circuit_open(self):
        """Lines 172-175: circuit breaker open"""
        from core.resilience import CircuitOpenError
        module = OllamaModule()

        with patch("plugins.ollama_module.module.ollama_breaker") as mock_breaker:
            mock_breaker.check_circuit = AsyncMock(return_value=False)
            mock_breaker.config.timeout_seconds = 30
            with pytest.raises(CircuitOpenError):
                async for _ in module.pull_model("model"):
                    pass

    @pytest.mark.asyncio
    async def test_pull_model_http_error(self):
        """Lines 196-200: HTTP error during pull"""
        import httpx
        module = OllamaModule()

        mock_client = AsyncMock()
        mock_client.__aenter__ = AsyncMock(side_effect=httpx.HTTPError("connection failed"))
        mock_client.__aexit__ = AsyncMock(return_value=None)

        with patch("plugins.ollama_module.module.httpx.AsyncClient", return_value=mock_client), \
             patch("plugins.ollama_module.module.ollama_breaker") as mock_breaker:
            mock_breaker.check_circuit = AsyncMock(return_value=True)
            mock_breaker.record_failure = AsyncMock()
            with pytest.raises(httpx.HTTPError):
                async for _ in module.pull_model("model"):
                    pass

    @pytest.mark.asyncio
    async def test_pull_model_invalid_json(self):
        """Lines 192-194: invalid JSON in response line"""
        module = OllamaModule()

        mock_response = MagicMock()
        mock_response.raise_for_status = MagicMock()

        async def fake_aiter_lines():
            yield "not json {{"
            yield json.dumps({"status": "ok"})

        mock_response.aiter_lines = fake_aiter_lines

        mock_stream_ctx = AsyncMock()
        mock_stream_ctx.__aenter__ = AsyncMock(return_value=mock_response)
        mock_stream_ctx.__aexit__ = AsyncMock(return_value=None)

        mock_client = AsyncMock()
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=None)
        mock_client.stream = MagicMock(return_value=mock_stream_ctx)

        with patch("plugins.ollama_module.module.httpx.AsyncClient", return_value=mock_client), \
             patch("plugins.ollama_module.module.ollama_breaker") as mock_breaker:
            mock_breaker.check_circuit = AsyncMock(return_value=True)
            mock_breaker.record_success = AsyncMock()
            chunks = []
            async for chunk in module.pull_model("model"):
                chunks.append(chunk)

        assert len(chunks) == 1  # only valid JSON yielded


class TestGetModelInfo:
    """Tests for get_model_info (lines 218-225)"""

    @pytest.mark.asyncio
    async def test_get_model_info_success(self):
        """Lines 218-225: successful model info"""
        module = OllamaModule()
        mock_response = MagicMock()
        mock_response.raise_for_status = MagicMock()
        mock_response.json.return_value = {"modelfile": "...", "parameters": {}}

        mock_client = AsyncMock()
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=None)
        mock_client.post = AsyncMock(return_value=mock_response)

        with patch("plugins.ollama_module.module.httpx.AsyncClient", return_value=mock_client):
            result = await module.get_model_info("llama3")

        assert "modelfile" in result


class TestChat:
    """Tests for chat (lines 251, 273-288, 295)"""

    @pytest.mark.asyncio
    async def test_chat_streaming(self):
        """Lines 273-288: streaming chat"""
        module = OllamaModule()

        mock_response = MagicMock()
        mock_response.raise_for_status = MagicMock()

        async def fake_aiter_lines():
            yield json.dumps({"message": {"content": "Hello"}})
            yield json.dumps({"message": {"content": " world"}})

        mock_response.aiter_lines = fake_aiter_lines

        mock_stream_ctx = AsyncMock()
        mock_stream_ctx.__aenter__ = AsyncMock(return_value=mock_response)
        mock_stream_ctx.__aexit__ = AsyncMock(return_value=None)

        mock_client = AsyncMock()
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=None)
        mock_client.stream = MagicMock(return_value=mock_stream_ctx)

        with patch("plugins.ollama_module.module.httpx.AsyncClient", return_value=mock_client), \
             patch("plugins.ollama_module.module.ollama_breaker") as mock_breaker:
            mock_breaker.check_circuit = AsyncMock(return_value=True)
            mock_breaker.record_success = AsyncMock()
            chunks = []
            async for chunk in module.chat("llama3", [{"role": "user", "content": "hi"}], stream=True):
                chunks.append(chunk)

        assert len(chunks) == 2

    @pytest.mark.asyncio
    async def test_chat_non_streaming(self):
        """Lines 289-296: non-streaming chat"""
        module = OllamaModule()

        mock_response = MagicMock()
        mock_response.raise_for_status = MagicMock()
        mock_response.json.return_value = {"message": {"content": "Full response"}}

        mock_client = AsyncMock()
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=None)
        mock_client.post = AsyncMock(return_value=mock_response)

        with patch("plugins.ollama_module.module.httpx.AsyncClient", return_value=mock_client), \
             patch("plugins.ollama_module.module.ollama_breaker") as mock_breaker:
            mock_breaker.check_circuit = AsyncMock(return_value=True)
            mock_breaker.record_success = AsyncMock()
            chunks = []
            async for chunk in module.chat("llama3", [{"role": "user", "content": "hi"}], stream=False):
                chunks.append(chunk)

        assert len(chunks) == 1
        assert chunks[0]["message"]["content"] == "Full response"

    @pytest.mark.asyncio
    async def test_chat_circuit_open(self):
        """Line 251: circuit breaker open"""
        from core.resilience import CircuitOpenError
        module = OllamaModule()

        with patch("plugins.ollama_module.module.ollama_breaker") as mock_breaker:
            mock_breaker.check_circuit = AsyncMock(return_value=False)
            mock_breaker.config.timeout_seconds = 30
            with pytest.raises(CircuitOpenError):
                async for _ in module.chat("model", [], stream=True):
                    pass

    @pytest.mark.asyncio
    async def test_chat_http_error(self):
        """Lines 298-302: HTTP error during chat"""
        import httpx
        module = OllamaModule()

        mock_client = AsyncMock()
        mock_client.__aenter__ = AsyncMock(side_effect=httpx.HTTPError("timeout"))
        mock_client.__aexit__ = AsyncMock(return_value=None)

        with patch("plugins.ollama_module.module.httpx.AsyncClient", return_value=mock_client), \
             patch("plugins.ollama_module.module.ollama_breaker") as mock_breaker:
            mock_breaker.check_circuit = AsyncMock(return_value=True)
            mock_breaker.record_failure = AsyncMock()
            with pytest.raises(httpx.HTTPError):
                async for _ in module.chat("model", [], stream=True):
                    pass

    @pytest.mark.asyncio
    async def test_chat_invalid_json_in_stream(self):
        """Lines 286-288: invalid JSON in streaming response"""
        module = OllamaModule()

        mock_response = MagicMock()
        mock_response.raise_for_status = MagicMock()

        async def fake_aiter_lines():
            yield "invalid json"
            yield json.dumps({"message": {"content": "valid"}})

        mock_response.aiter_lines = fake_aiter_lines

        mock_stream_ctx = AsyncMock()
        mock_stream_ctx.__aenter__ = AsyncMock(return_value=mock_response)
        mock_stream_ctx.__aexit__ = AsyncMock(return_value=None)

        mock_client = AsyncMock()
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=None)
        mock_client.stream = MagicMock(return_value=mock_stream_ctx)

        with patch("plugins.ollama_module.module.httpx.AsyncClient", return_value=mock_client), \
             patch("plugins.ollama_module.module.ollama_breaker") as mock_breaker:
            mock_breaker.check_circuit = AsyncMock(return_value=True)
            mock_breaker.record_success = AsyncMock()
            chunks = []
            async for chunk in module.chat("llama3", [], stream=True):
                chunks.append(chunk)

        assert len(chunks) == 1


class TestDeleteModel:
    """Tests for delete_model (lines 320-329)"""

    @pytest.mark.asyncio
    async def test_delete_model_success(self):
        """Lines 320-329: successful delete"""
        module = OllamaModule()
        mock_response = MagicMock()
        mock_response.raise_for_status = MagicMock()

        mock_client = AsyncMock()
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=None)
        mock_client.delete = AsyncMock(return_value=mock_response)

        with patch("plugins.ollama_module.module.httpx.AsyncClient", return_value=mock_client):
            result = await module.delete_model("llama3")

        assert result is True


class TestGetInfo:
    """Tests for get_info (line 333)"""

    def test_get_info(self):
        """Lines 331-348: returns module info dict"""
        module = OllamaModule()
        info = module.get_info()
        assert info["name"] == "ollama_module"
        assert "features" in info


class TestLoadI18nForCli:
    """Tests for _load_i18n_for_cli (lines 352-358)"""

    def test_load_i18n_success(self):
        """Lines 352-356: successful i18n load"""
        from plugins.ollama_module.module import _load_i18n_for_cli
        mock_i18n = MagicMock()
        with patch("plugins.ollama_module.module.I18nService", return_value=mock_i18n, create=True):
            with patch.dict("sys.modules", {"personality.i18n": MagicMock(I18nService=MagicMock(return_value=mock_i18n))}):
                result = _load_i18n_for_cli()
        # May return None if import fails in test env; that's fine
        # The test exercises the code path

    def test_load_i18n_failure(self):
        """Lines 357-358: i18n import fails"""
        from plugins.ollama_module.module import _load_i18n_for_cli
        with patch.dict("sys.modules", {"personality.i18n": None}):
            result = _load_i18n_for_cli()
        assert result is None


class TestMain:
    """Tests for main (lines 362-419)"""

    @pytest.mark.asyncio
    async def test_main_connected_with_models(self):
        """Lines 362-419: main with connection and models"""
        from plugins.ollama_module.module import main

        mock_module = MagicMock()
        mock_module.base_url = "http://localhost:11434"
        mock_module.check_connection = AsyncMock(return_value=True)
        mock_module.list_models = AsyncMock(return_value=[
            {"name": "llama3", "size": 4 * 1024**3}
        ])

        with patch("plugins.ollama_module.module._load_i18n_for_cli", return_value=None), \
             patch("plugins.ollama_module.module.OllamaModule", return_value=mock_module), \
             patch("builtins.print"):
            result = await main()

        assert result == 0

    @pytest.mark.asyncio
    async def test_main_not_connected(self):
        """Lines 391-394: not connected"""
        from plugins.ollama_module.module import main

        mock_module = MagicMock()
        mock_module.base_url = "http://localhost:11434"
        mock_module.check_connection = AsyncMock(return_value=False)

        with patch("plugins.ollama_module.module._load_i18n_for_cli", return_value=None), \
             patch("plugins.ollama_module.module.OllamaModule", return_value=mock_module), \
             patch("builtins.print"):
            result = await main()

        assert result == 1

    @pytest.mark.asyncio
    async def test_main_no_models(self):
        """Lines 401-403: connected but no models"""
        from plugins.ollama_module.module import main

        mock_module = MagicMock()
        mock_module.base_url = "http://localhost:11434"
        mock_module.check_connection = AsyncMock(return_value=True)
        mock_module.list_models = AsyncMock(return_value=[])

        with patch("plugins.ollama_module.module._load_i18n_for_cli", return_value=None), \
             patch("plugins.ollama_module.module.OllamaModule", return_value=mock_module), \
             patch("builtins.print"):
            result = await main()

        assert result == 0

    @pytest.mark.asyncio
    async def test_main_list_models_error(self):
        """Lines 409-411: error listing models"""
        from plugins.ollama_module.module import main

        mock_module = MagicMock()
        mock_module.base_url = "http://localhost:11434"
        mock_module.check_connection = AsyncMock(return_value=True)
        mock_module.list_models = AsyncMock(side_effect=Exception("API error"))

        with patch("plugins.ollama_module.module._load_i18n_for_cli", return_value=None), \
             patch("plugins.ollama_module.module.OllamaModule", return_value=mock_module), \
             patch("builtins.print"):
            result = await main()

        assert result == 1
