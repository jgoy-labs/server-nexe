"""
Tests for plugins/ollama_module/core/client.py — reap_process coverage.
C2: subprocess zombie cleanup at shutdown.
"""
import pytest
from unittest.mock import MagicMock, AsyncMock, patch

from plugins.ollama_module.core.client import OllamaClient
from plugins.ollama_module.module import OllamaModule


class TestReapProcess:
    """Tests for OllamaClient.reap_process() — avoids subprocess zombies."""

    def test_reap_calls_poll_on_existing_process(self):
        """If _ollama_process exists → .poll() is called once."""
        client = OllamaClient("http://localhost:11434")
        mock_proc = MagicMock()
        client._ollama_process = mock_proc

        client.reap_process()

        mock_proc.poll.assert_called_once()

    def test_reap_does_nothing_if_no_process(self):
        """If _ollama_process is None → raises no error."""
        client = OllamaClient("http://localhost:11434")
        assert client._ollama_process is None
        client.reap_process()  # must not raise


class TestModuleShutdownReapsProcess:
    """Test that OllamaModule.shutdown() calls reap_process."""

    @pytest.mark.asyncio
    async def test_shutdown_calls_reap_process(self):
        """At shutdown, reap_process() is always called (whether initialized or not)."""
        module = OllamaModule()
        module._initialized = True
        mock_proc = MagicMock()
        module.client._ollama_process = mock_proc

        with patch.object(module.client, "unload_all_models", new_callable=AsyncMock):
            await module.shutdown()

        mock_proc.poll.assert_called_once()
        assert module._initialized is False

    @pytest.mark.asyncio
    async def test_shutdown_reaps_even_when_not_initialized(self):
        """reap_process() is also called when _initialized=False."""
        module = OllamaModule()
        module._initialized = False
        mock_proc = MagicMock()
        module.client._ollama_process = mock_proc

        await module.shutdown()

        mock_proc.poll.assert_called_once()
