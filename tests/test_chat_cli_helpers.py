"""Tests per a les funcions helper extretes de _chat_async."""
import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from core.cli.chat_cli import (
    _check_server_status,
    _create_chat_session,
    _handle_slash_command,
    _handle_user_message,
    _parse_collections,
    _process_metadata_chunk,
    _resolve_chat_engine_and_model,
)


# ─── _resolve_chat_engine_and_model ──────────────────────────────────────────

class TestResolveChatEngineAndModel:
    async def test_detects_engine_when_none(self):
        with patch("core.cli.chat_cli.detect_engine", return_value="ollama"):
            with patch("core.cli.chat_cli.detect_model", return_value="llama3"):
                engine, model = await _resolve_chat_engine_and_model(None, None)
        assert engine == "ollama"
        assert model == "llama3"

    async def test_keeps_provided_engine_and_model(self):
        engine, model = await _resolve_chat_engine_and_model("mlx", "mistral")
        assert engine == "mlx"
        assert model == "mistral"

    async def test_detects_only_model_when_engine_provided(self):
        with patch("core.cli.chat_cli.detect_model", return_value="auto"):
            engine, model = await _resolve_chat_engine_and_model("llama_cpp", None)
        assert engine == "llama_cpp"
        assert model == "auto"


# ─── _check_server_status ────────────────────────────────────────────────────

class TestCheckServerStatus:
    async def test_returns_true_when_running(self):
        client = MagicMock()
        client.is_server_running = AsyncMock(return_value=True)
        assert await _check_server_status(client) is True

    async def test_returns_false_when_not_running(self):
        client = MagicMock()
        client.is_server_running = AsyncMock(return_value=False)
        assert await _check_server_status(client) is False


# ─── _create_chat_session ────────────────────────────────────────────────────

class TestCreateChatSession:
    async def test_returns_session_id(self):
        client = MagicMock()
        client.create_ui_session = AsyncMock(return_value="sess-abc")
        result = await _create_chat_session(client)
        assert result == "sess-abc"

    async def test_returns_none_when_fails(self):
        client = MagicMock()
        client.create_ui_session = AsyncMock(return_value=None)
        result = await _create_chat_session(client)
        assert result is None


# ─── _parse_collections ──────────────────────────────────────────────────────

class TestParseCollections:
    def test_none_returns_none(self):
        assert _parse_collections(None) is None

    def test_empty_string_returns_none(self):
        assert _parse_collections("") is None

    def test_memory_alias_resolved(self):
        result = _parse_collections("memory")
        assert result == ["personal_memory"]

    def test_knowledge_alias_resolved(self):
        result = _parse_collections("knowledge")
        assert result == ["nexe_documentation"]

    def test_unknown_collection_passes_through(self):
        result = _parse_collections("custom_col")
        assert result == ["custom_col"]

    def test_multiple_collections_parsed(self):
        result = _parse_collections("memory,knowledge")
        assert result == ["personal_memory", "nexe_documentation"]


# ─── _process_metadata_chunk ─────────────────────────────────────────────────

class TestProcessMetadataChunk:
    def test_model_name_updated(self):
        state = {"model_name": None, "rag_count": 0, "rag_avg": 0.0, "rag_items": [], "mem_saved": False, "compact_count": 0}
        _process_metadata_chunk({"MODEL": "llama3"}, state)
        assert state["model_name"] == "llama3"

    def test_rag_count_updated(self):
        state = {"model_name": None, "rag_count": 0, "rag_avg": 0.0, "rag_items": [], "mem_saved": False, "compact_count": 0}
        _process_metadata_chunk({"RAG": "3"}, state)
        assert state["rag_count"] == 3

    def test_invalid_rag_does_not_crash(self):
        state = {"model_name": None, "rag_count": 0, "rag_avg": 0.0, "rag_items": [], "mem_saved": False, "compact_count": 0}
        _process_metadata_chunk({"RAG": "not_a_number"}, state)
        assert state["rag_count"] == 0

    def test_rag_item_appended(self):
        state = {"model_name": None, "rag_count": 0, "rag_avg": 0.0, "rag_items": [], "mem_saved": False, "compact_count": 0}
        _process_metadata_chunk({"RAG_ITEM": "nexe_documentation|0.85"}, state)
        assert state["rag_items"] == [("nexe_documentation", 0.85)]

    def test_mem_flag_set(self):
        state = {"model_name": None, "rag_count": 0, "rag_avg": 0.0, "rag_items": [], "mem_saved": False, "compact_count": 0}
        _process_metadata_chunk({"MEM": True}, state)
        assert state["mem_saved"] is True

    def test_empty_chunk_no_change(self):
        state = {"model_name": None, "rag_count": 0, "rag_avg": 0.0, "rag_items": [], "mem_saved": False, "compact_count": 0}
        _process_metadata_chunk({}, state)
        assert state["model_name"] is None
        assert state["rag_count"] == 0


# ─── _handle_slash_command ───────────────────────────────────────────────────

class TestHandleSlashCommand:
    async def test_help_returns_true(self):
        client = MagicMock()
        result = await _handle_slash_command("help", "", client, "sess", {})
        assert result is True

    async def test_unknown_command_returns_true(self):
        client = MagicMock()
        result = await _handle_slash_command("unknown", "", client, "sess", {})
        assert result is True

    async def test_recall_with_results_returns_true(self):
        client = MagicMock()
        client.memory_search = AsyncMock(return_value=[{"content": "result text"}])
        result = await _handle_slash_command("recall", "query", client, "sess", {})
        assert result is True
        client.memory_search.assert_called_once_with("query")

    async def test_recall_no_results_returns_true(self):
        client = MagicMock()
        client.memory_search = AsyncMock(return_value=[])
        result = await _handle_slash_command("recall", "nores", client, "sess", {})
        assert result is True

    async def test_save_success_returns_true(self):
        client = MagicMock()
        client.memory_store = AsyncMock(return_value=True)

        async def _fake_stream(*args, **kwargs):
            yield "confirmat"

        client.chat_ui_stream = _fake_stream
        result = await _handle_slash_command("save", "text to remember", client, "sess", {})
        assert result is True

    async def test_upload_missing_file_returns_true(self):
        client = MagicMock()
        result = await _handle_slash_command("upload", "/no/such/file.txt", client, "sess", {})
        assert result is True


# ─── _handle_user_message ────────────────────────────────────────────────────

class TestHandleUserMessage:
    async def test_streams_text_chunks(self):
        client = MagicMock()

        async def _fake_stream(*args, **kwargs):
            yield "hola "
            yield "món"

        client.chat_ui_stream = _fake_stream

        with patch("core.cli.chat_cli._stream_with_spinner", side_effect=lambda g: g):
            with patch("core.cli.chat_cli.click") as mock_click:
                mock_click.style.return_value = ""
                await _handle_user_message("pregunta", client, "sess", {}, verbose=False)

    async def test_metadata_chunks_processed(self):
        client = MagicMock()

        async def _fake_stream(*args, **kwargs):
            yield {"MODEL": "llama3"}
            yield "resposta"

        client.chat_ui_stream = _fake_stream

        with patch("core.cli.chat_cli._stream_with_spinner", side_effect=lambda g: g):
            with patch("core.cli.chat_cli.click") as mock_click:
                mock_click.style.return_value = ""
                await _handle_user_message("query", client, "sess", {}, verbose=False)
