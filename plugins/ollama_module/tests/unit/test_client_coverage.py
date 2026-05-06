"""
Tests per plugins/ollama_module/core/client.py — cobertura reap_process.
C2: subprocess zombi cleanup al shutdown.
"""
import pytest
from unittest.mock import MagicMock, AsyncMock, patch

from plugins.ollama_module.core.client import OllamaClient
from plugins.ollama_module.module import OllamaModule


class TestReapProcess:
    """Tests per OllamaClient.reap_process() — evita zombis de subprocess."""

    def test_reap_calls_poll_on_existing_process(self):
        """Si _ollama_process existeix → .poll() és cridat una vegada."""
        client = OllamaClient("http://localhost:11434")
        mock_proc = MagicMock()
        client._ollama_process = mock_proc

        client.reap_process()

        mock_proc.poll.assert_called_once()

    def test_reap_does_nothing_if_no_process(self):
        """Si _ollama_process és None → no llança cap error."""
        client = OllamaClient("http://localhost:11434")
        assert client._ollama_process is None
        client.reap_process()  # no ha de llançar


class TestModuleShutdownReapsProcess:
    """Test que OllamaModule.shutdown() crida reap_process."""

    @pytest.mark.asyncio
    async def test_shutdown_calls_reap_process(self):
        """Al shutdown, reap_process() sempre es crida (tant si initialized com si no)."""
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
        """reap_process() també es crida quan _initialized=False."""
        module = OllamaModule()
        module._initialized = False
        mock_proc = MagicMock()
        module.client._ollama_process = mock_proc

        await module.shutdown()

        mock_proc.poll.assert_called_once()
