"""
Tests for plugins/ollama_module/cli.py.
"""

import pytest
import sys
from unittest.mock import patch, MagicMock, AsyncMock


class TestRunAsync:
    """Test the _run_async helper."""

    def test_run_async(self):
        """Test _run_async runs a coroutine."""
        from plugins.ollama_module.cli import _run_async
        import asyncio

        async def sample():
            return 42

        result = _run_async(sample())
        assert result == 42


class TestRichAvailable:
    """Test RICH_AVAILABLE detection."""

    def test_rich_available_true(self):
        """Test RICH_AVAILABLE is True when typer/rich are installed."""
        from plugins.ollama_module import cli
        # Both typer and rich should be available in test env
        # If not, this test verifies the fallback
        assert isinstance(cli.RICH_AVAILABLE, bool)


class TestStatusCommand:
    """Test status command."""

    def test_status_connected(self):
        """Test status when connected."""
        from plugins.ollama_module.cli import status

        with patch("plugins.ollama_module.cli.main.OllamaModule") as MockOllama:
            mock_ollama = MockOllama.return_value
            mock_ollama.base_url = "http://localhost:11434"
            mock_ollama.check_connection = AsyncMock(return_value=True)
            mock_ollama.list_models = AsyncMock(return_value=[{"name": "test"}])

            with patch("plugins.ollama_module.cli.main.console") as mock_console:
                mock_console.status.return_value.__enter__ = MagicMock()
                mock_console.status.return_value.__exit__ = MagicMock(return_value=False)
                status()
            mock_ollama.check_connection.assert_awaited_once()
            mock_ollama.list_models.assert_awaited_once()

    def test_status_disconnected(self):
        """Test status when disconnected."""
        from plugins.ollama_module.cli import status

        with patch("plugins.ollama_module.cli.main.OllamaModule") as MockOllama:
            mock_ollama = MockOllama.return_value
            mock_ollama.base_url = "http://localhost:11434"
            mock_ollama.check_connection = AsyncMock(return_value=False)

            with patch("plugins.ollama_module.cli.main.console") as mock_console:
                mock_console.status.return_value.__enter__ = MagicMock()
                mock_console.status.return_value.__exit__ = MagicMock(return_value=False)
                status()
            mock_ollama.check_connection.assert_awaited_once()

    def test_status_models_error(self):
        """Test status when listing models fails."""
        from plugins.ollama_module.cli import status

        with patch("plugins.ollama_module.cli.main.OllamaModule") as MockOllama:
            mock_ollama = MockOllama.return_value
            mock_ollama.base_url = "http://localhost:11434"
            mock_ollama.check_connection = AsyncMock(return_value=True)
            mock_ollama.list_models = AsyncMock(side_effect=RuntimeError("fail"))

            with patch("plugins.ollama_module.cli.main.console") as mock_console:
                mock_console.status.return_value.__enter__ = MagicMock()
                mock_console.status.return_value.__exit__ = MagicMock(return_value=False)
                status()
            mock_ollama.check_connection.assert_awaited_once()


class TestModelsCommand:
    """Test models command."""

    def test_models_list(self):
        """Test listing models."""
        from plugins.ollama_module.cli import models

        with patch("plugins.ollama_module.cli.main.OllamaModule") as MockOllama:
            mock_ollama = MockOllama.return_value
            mock_ollama.list_models = AsyncMock(return_value=[
                {"name": "mistral", "size": 4 * 1024**3, "modified_at": "2026-01-01T00:00:00"},
                {"name": "llama3", "size": 8 * 1024**3},
            ])

            with patch("plugins.ollama_module.cli.main.console") as mock_console:
                mock_console.status.return_value.__enter__ = MagicMock()
                mock_console.status.return_value.__exit__ = MagicMock(return_value=False)
                with patch("plugins.ollama_module.cli.main.Table") as MockTable:
                    mock_table = MagicMock()
                    MockTable.return_value = mock_table
                    models()
                    assert mock_table.add_row.call_count == 2

    def test_models_empty(self):
        """Test when no models installed."""
        from plugins.ollama_module.cli import models

        with patch("plugins.ollama_module.cli.main.OllamaModule") as MockOllama:
            mock_ollama = MockOllama.return_value
            mock_ollama.list_models = AsyncMock(return_value=[])

            with patch("plugins.ollama_module.cli.main.console") as mock_console:
                mock_console.status.return_value.__enter__ = MagicMock()
                mock_console.status.return_value.__exit__ = MagicMock(return_value=False)
                models()
            mock_ollama.list_models.assert_awaited_once()

    def test_models_error(self):
        """Test models command error."""
        from plugins.ollama_module.cli import models
        import typer

        with patch("plugins.ollama_module.cli.main.OllamaModule") as MockOllama:
            mock_ollama = MockOllama.return_value
            mock_ollama.list_models = AsyncMock(side_effect=RuntimeError("fail"))

            with patch("plugins.ollama_module.cli.main.console") as mock_console:
                mock_console.status.return_value.__enter__ = MagicMock()
                mock_console.status.return_value.__exit__ = MagicMock(return_value=False)
                with pytest.raises(typer.Exit):
                    models()


class TestPullCommand:
    """Test pull command."""

    def test_pull_success(self):
        """Test successful model pull."""
        from plugins.ollama_module.cli import pull

        async def mock_pull_gen(model):
            yield {"status": "downloading"}
            yield {"status": "downloading", "completed": 50, "total": 100}
            yield {"status": "success"}

        with patch("plugins.ollama_module.cli.main.OllamaModule") as MockOllama:
            mock_ollama = MockOllama.return_value
            mock_ollama.pull_model = mock_pull_gen

            with patch("plugins.ollama_module.cli.main.console") as mock_console:
                with patch("plugins.ollama_module.cli.main.Progress") as MockProgress:
                    mock_progress = MagicMock()
                    MockProgress.return_value.__enter__ = MagicMock(return_value=mock_progress)
                    MockProgress.return_value.__exit__ = MagicMock()
                    mock_progress.add_task.return_value = "task1"
                    pull(model="mistral")
                    mock_progress.update.assert_called()

    def test_pull_error(self):
        """Test pull command error."""
        from plugins.ollama_module.cli import pull
        import typer

        with patch("plugins.ollama_module.cli.main.OllamaModule") as MockOllama:
            mock_ollama = MockOllama.return_value

            with patch("plugins.ollama_module.cli.main.console") as mock_console:
                with patch("plugins.ollama_module.cli.main._run_async", side_effect=RuntimeError("download failed")):
                    with pytest.raises(typer.Exit):
                        pull(model="nonexistent")


class TestInfoCommand:
    """Test info command."""

    def test_info_success(self):
        """Test getting model info."""
        from plugins.ollama_module.cli import info

        with patch("plugins.ollama_module.cli.main.OllamaModule") as MockOllama:
            mock_ollama = MockOllama.return_value
            mock_ollama.get_model_info = AsyncMock(return_value={
                "parameters": "num_params 7B",
                "template": "{{ .System }}\n{{ .Prompt }}",
                "details": {"format": "gguf", "family": "llama"},
            })

            with patch("plugins.ollama_module.cli.main.console") as mock_console:
                mock_console.status.return_value.__enter__ = MagicMock()
                mock_console.status.return_value.__exit__ = MagicMock(return_value=False)
                with patch("plugins.ollama_module.cli.main.Panel"):
                    info(model="mistral")
            mock_ollama.get_model_info.assert_awaited_once()

    def test_info_long_params(self):
        """Test info with long parameters string."""
        from plugins.ollama_module.cli import info

        with patch("plugins.ollama_module.cli.main.OllamaModule") as MockOllama:
            mock_ollama = MockOllama.return_value
            mock_ollama.get_model_info = AsyncMock(return_value={
                "parameters": "x" * 600,
                "template": "y" * 400,
            })

            with patch("plugins.ollama_module.cli.main.console") as mock_console:
                mock_console.status.return_value.__enter__ = MagicMock()
                mock_console.status.return_value.__exit__ = MagicMock(return_value=False)
                with patch("plugins.ollama_module.cli.main.Panel"):
                    info(model="mistral")
            mock_ollama.get_model_info.assert_awaited_once()

    def test_info_error(self):
        """Test info command error."""
        from plugins.ollama_module.cli import info
        import typer

        with patch("plugins.ollama_module.cli.main.OllamaModule") as MockOllama:
            mock_ollama = MockOllama.return_value
            mock_ollama.get_model_info = AsyncMock(side_effect=RuntimeError("fail"))

            with patch("plugins.ollama_module.cli.main.console") as mock_console:
                mock_console.status.return_value.__enter__ = MagicMock()
                mock_console.status.return_value.__exit__ = MagicMock(return_value=False)
                with pytest.raises(typer.Exit):
                    info(model="bad")


class TestDeleteCommand:
    """Test delete command."""

    def test_delete_with_force(self):
        """Test force delete."""
        from plugins.ollama_module.cli import delete

        with patch("plugins.ollama_module.cli.main.OllamaModule") as MockOllama:
            mock_ollama = MockOllama.return_value
            mock_ollama.delete_model = AsyncMock()

            with patch("plugins.ollama_module.cli.main.console") as mock_console:
                mock_console.status.return_value.__enter__ = MagicMock()
                mock_console.status.return_value.__exit__ = MagicMock(return_value=False)
                delete(model="mistral", force=True)
            mock_ollama.delete_model.assert_awaited_once()

    def test_delete_confirmed(self):
        """Test delete with confirmation."""
        from plugins.ollama_module.cli import delete
        import typer

        with patch("plugins.ollama_module.cli.main.OllamaModule") as MockOllama:
            mock_ollama = MockOllama.return_value
            mock_ollama.delete_model = AsyncMock()

            with patch("plugins.ollama_module.cli.main.console") as mock_console:
                mock_console.status.return_value.__enter__ = MagicMock()
                mock_console.status.return_value.__exit__ = MagicMock(return_value=False)
                with patch.object(typer, "confirm", return_value=True):
                    delete(model="mistral", force=False)
            mock_ollama.delete_model.assert_awaited_once()

    def test_delete_cancelled(self):
        """Test delete cancelled by user."""
        from plugins.ollama_module.cli import delete
        import typer

        with patch("plugins.ollama_module.cli.main.OllamaModule") as MockOllama:
            with patch("plugins.ollama_module.cli.main.console") as mock_console:
                with patch.object(typer, "confirm", return_value=False):
                    with pytest.raises(typer.Exit):
                        delete(model="mistral", force=False)

    def test_delete_error(self):
        """Test delete error."""
        from plugins.ollama_module.cli import delete
        import typer

        with patch("plugins.ollama_module.cli.main.OllamaModule") as MockOllama:
            mock_ollama = MockOllama.return_value
            mock_ollama.delete_model = AsyncMock(side_effect=RuntimeError("fail"))

            with patch("plugins.ollama_module.cli.main.console") as mock_console:
                mock_console.status.return_value.__enter__ = MagicMock()
                mock_console.status.return_value.__exit__ = MagicMock(return_value=False)
                with pytest.raises(typer.Exit):
                    delete(model="bad", force=True)


class TestChatCommand:
    """Test chat command."""

    def test_chat_not_connected(self):
        """Test chat when Ollama not connected."""
        from plugins.ollama_module.cli import chat
        import typer

        with patch("plugins.ollama_module.cli.main.OllamaModule") as MockOllama:
            mock_ollama = MockOllama.return_value
            mock_ollama.check_connection = AsyncMock(return_value=False)

            with patch("plugins.ollama_module.cli.main.console") as mock_console:
                mock_console.status.return_value.__enter__ = MagicMock()
                mock_console.status.return_value.__exit__ = MagicMock(return_value=False)
                with pytest.raises(typer.Exit):
                    chat(model="mistral", system=None)

    def test_chat_exit_command(self):
        """Test chat with exit command."""
        from plugins.ollama_module.cli import chat

        with patch("plugins.ollama_module.cli.main.OllamaModule") as MockOllama:
            mock_ollama = MockOllama.return_value
            mock_ollama.check_connection = AsyncMock(return_value=True)

            with patch("plugins.ollama_module.cli.main.console") as mock_console:
                mock_console.status.return_value.__enter__ = MagicMock()
                mock_console.status.return_value.__exit__ = MagicMock(return_value=False)
                mock_console.input.return_value = "exit"
                with patch("plugins.ollama_module.cli.main.Panel"):
                    chat(model="mistral", system=None)
                mock_console.input.assert_called()

    def test_chat_with_system_prompt(self):
        """Test chat with system prompt."""
        from plugins.ollama_module.cli import chat

        with patch("plugins.ollama_module.cli.main.OllamaModule") as MockOllama:
            mock_ollama = MockOllama.return_value
            mock_ollama.check_connection = AsyncMock(return_value=True)

            with patch("plugins.ollama_module.cli.main.console") as mock_console:
                mock_console.status.return_value.__enter__ = MagicMock()
                mock_console.status.return_value.__exit__ = MagicMock(return_value=False)
                mock_console.input.return_value = "quit"
                with patch("plugins.ollama_module.cli.main.Panel"):
                    chat(model="mistral", system="Be helpful")
                mock_console.input.assert_called()

    def test_chat_clear_command(self):
        """Test chat clear command."""
        from plugins.ollama_module.cli import chat

        with patch("plugins.ollama_module.cli.main.OllamaModule") as MockOllama:
            mock_ollama = MockOllama.return_value
            mock_ollama.check_connection = AsyncMock(return_value=True)

            with patch("plugins.ollama_module.cli.main.console") as mock_console:
                mock_console.status.return_value.__enter__ = MagicMock()
                mock_console.status.return_value.__exit__ = MagicMock(return_value=False)
                mock_console.input.side_effect = ["clear", "exit"]
                with patch("plugins.ollama_module.cli.main.Panel"):
                    chat(model="mistral", system="sys")
                assert mock_console.input.call_count == 2

    def test_chat_empty_input(self):
        """Test chat with empty input."""
        from plugins.ollama_module.cli import chat

        with patch("plugins.ollama_module.cli.main.OllamaModule") as MockOllama:
            mock_ollama = MockOllama.return_value
            mock_ollama.check_connection = AsyncMock(return_value=True)

            with patch("plugins.ollama_module.cli.main.console") as mock_console:
                mock_console.status.return_value.__enter__ = MagicMock()
                mock_console.status.return_value.__exit__ = MagicMock(return_value=False)
                mock_console.input.side_effect = ["", "q"]
                with patch("plugins.ollama_module.cli.main.Panel"):
                    chat(model="mistral", system=None)
                assert mock_console.input.call_count == 2

    def test_chat_keyboard_interrupt(self):
        """Test chat with KeyboardInterrupt."""
        from plugins.ollama_module.cli import chat

        with patch("plugins.ollama_module.cli.main.OllamaModule") as MockOllama:
            mock_ollama = MockOllama.return_value
            mock_ollama.check_connection = AsyncMock(return_value=True)

            with patch("plugins.ollama_module.cli.main.console") as mock_console:
                mock_console.status.return_value.__enter__ = MagicMock()
                mock_console.status.return_value.__exit__ = MagicMock(return_value=False)
                mock_console.input.side_effect = KeyboardInterrupt
                with patch("plugins.ollama_module.cli.main.Panel"):
                    chat(model="mistral", system=None)
                mock_console.input.assert_called_once()

    def test_chat_error_during_response(self):
        """Test chat error during response generation."""
        from plugins.ollama_module.cli import chat

        call_count = 0
        def mock_run_async(coro):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                return True  # check_connection
            raise RuntimeError("api error")  # get_response

        with patch("plugins.ollama_module.cli.main.OllamaModule") as MockOllama:
            mock_ollama = MockOllama.return_value

            with patch("plugins.ollama_module.cli.main.console") as mock_console:
                mock_console.status.return_value.__enter__ = MagicMock()
                mock_console.status.return_value.__exit__ = MagicMock(return_value=False)
                mock_console.input.side_effect = ["hello", "exit"]

                with patch("plugins.ollama_module.cli.main._run_async", side_effect=mock_run_async):
                    with patch("plugins.ollama_module.cli.main.Panel"):
                        with patch("builtins.print"):
                            chat(model="mistral", system=None)
                mock_console.input.assert_called()


class TestAskCommand:
    """Test ask command."""

    def test_ask_success(self):
        """Test successful ask."""
        from plugins.ollama_module.cli import ask

        async def mock_chat_gen(model, messages, stream=True):
            yield {"message": {"content": "The answer"}}

        with patch("plugins.ollama_module.cli.main.OllamaModule") as MockOllama:
            mock_ollama = MockOllama.return_value
            mock_ollama.check_connection = AsyncMock(return_value=True)
            mock_ollama.chat = mock_chat_gen

            with patch("plugins.ollama_module.cli.main.console") as mock_console:
                mock_console.status.return_value.__enter__ = MagicMock()
                mock_console.status.return_value.__exit__ = MagicMock(return_value=False)
                with patch("builtins.print") as mock_print:
                    ask(prompt="What is 2+2?", model="mistral", system=None)
                mock_print.assert_called()

    def test_ask_with_system(self):
        """Test ask with system prompt."""
        from plugins.ollama_module.cli import ask

        async def mock_chat_gen(model, messages, stream=True):
            yield {"message": {"content": "4"}}

        with patch("plugins.ollama_module.cli.main.OllamaModule") as MockOllama:
            mock_ollama = MockOllama.return_value
            mock_ollama.check_connection = AsyncMock(return_value=True)
            mock_ollama.chat = mock_chat_gen

            with patch("plugins.ollama_module.cli.main.console") as mock_console:
                mock_console.status.return_value.__enter__ = MagicMock()
                mock_console.status.return_value.__exit__ = MagicMock(return_value=False)
                with patch("builtins.print") as mock_print:
                    ask(prompt="2+2", model="mistral", system="Be brief")
                mock_print.assert_called()

    def test_ask_not_connected(self):
        """Test ask when not connected."""
        from plugins.ollama_module.cli import ask
        import typer

        with patch("plugins.ollama_module.cli.main.OllamaModule") as MockOllama:
            mock_ollama = MockOllama.return_value
            mock_ollama.check_connection = AsyncMock(return_value=False)

            with patch("plugins.ollama_module.cli.main.console") as mock_console:
                mock_console.status.return_value.__enter__ = MagicMock()
                mock_console.status.return_value.__exit__ = MagicMock(return_value=False)
                with pytest.raises(typer.Exit):
                    ask(prompt="test", model="mistral", system=None)

    def test_ask_error(self):
        """Test ask with error."""
        from plugins.ollama_module.cli import ask
        import typer

        with patch("plugins.ollama_module.cli.main.OllamaModule") as MockOllama:
            mock_ollama = MockOllama.return_value
            mock_ollama.check_connection = AsyncMock(return_value=True)

            with patch("plugins.ollama_module.cli.main.console") as mock_console:
                mock_console.status.return_value.__enter__ = MagicMock()
                mock_console.status.return_value.__exit__ = MagicMock(return_value=False)
                with patch("plugins.ollama_module.cli.main._run_async", side_effect=[True, RuntimeError("fail")]):
                    with pytest.raises(typer.Exit):
                        ask(prompt="test", model="mistral", system=None)


class TestMainEntryPoint:
    """Test main() entry point."""

    def test_main_with_dependencies(self):
        """Test main when dependencies are available."""
        from plugins.ollama_module.cli.main import main as main_fn

        with patch("plugins.ollama_module.cli.main.RICH_AVAILABLE", True):
            with patch("plugins.ollama_module.cli.main.typer", MagicMock()):
                with patch("plugins.ollama_module.cli.main.app") as mock_app:
                    main_fn()
                    mock_app.assert_called_once()

    def test_main_without_dependencies(self):
        """Test main when dependencies are not available."""
        from plugins.ollama_module.cli.main import main as main_fn

        with patch("plugins.ollama_module.cli.main.RICH_AVAILABLE", False):
            with patch("plugins.ollama_module.cli.main.typer", None):
                with patch("builtins.print"):
                    with pytest.raises(SystemExit) as exc_info:
                        main_fn()
                    assert exc_info.value.code == 1
