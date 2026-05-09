"""Tests for the helper functions extracted from chat_completions."""
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import BackgroundTasks
from fastapi.responses import StreamingResponse

from core.endpoints.chat import (
    _build_rag_and_system_prompt,
    _dispatch_to_engine,
    _inject_response_headers,
    _record_engine_metrics,
    _schedule_episodic_memory,
    _validate_chat_request,
)
from core.endpoints.chat_schemas import ChatCompletionRequest, Message


def _make_body(**kwargs):
    defaults = {
        "messages": [Message(role="user", content="hola")],
        "model": None,
        "engine": None,
        "use_rag": False,
    }
    defaults.update(kwargs)
    return ChatCompletionRequest(**defaults)


# ─── _validate_chat_request ──────────────────────────────────────────────────

class TestValidateChatRequest:
    def test_strips_model_field(self):
        body = _make_body(model="gpt-4")
        _validate_chat_request(body)
        assert body.model == "gpt-4"

    def test_strips_memory_tags_from_user_content(self):
        body = _make_body(messages=[Message(role="user", content="<NEXE_MEMORY>secret</NEXE_MEMORY>hola")])
        _validate_chat_request(body)
        assert "<NEXE_MEMORY>" not in body.messages[0].content

    def test_no_error_when_model_is_none(self):
        body = _make_body(model=None)
        _validate_chat_request(body)

    def test_no_error_with_assistant_message(self):
        body = _make_body(messages=[Message(role="assistant", content="hola")])
        _validate_chat_request(body)
        assert body.messages[0].content == "hola"


# ─── _build_rag_and_system_prompt ────────────────────────────────────────────

class TestBuildRagAndSystemPrompt:
    async def test_no_rag_injects_system_prompt(self):
        body = _make_body(use_rag=False)
        app_state = MagicMock()
        app_state.config = {}
        messages, context = await _build_rag_and_system_prompt(body, app_state, "en")
        assert context == ""
        assert messages[0]["role"] == "system"

    async def test_existing_system_message_not_duplicated(self):
        body = _make_body(
            use_rag=False,
            messages=[
                Message(role="system", content="custom"),
                Message(role="user", content="hola"),
            ],
        )
        app_state = MagicMock()
        messages, context = await _build_rag_and_system_prompt(body, app_state, "en")
        system_msgs = [m for m in messages if m["role"] == "system"]
        assert len(system_msgs) == 1
        assert system_msgs[0]["content"] == "custom"

    async def test_rag_disabled_returns_empty_context(self):
        body = _make_body(use_rag=False)
        app_state = MagicMock()
        app_state.config = {}
        _, context = await _build_rag_and_system_prompt(body, app_state, "ca")
        assert context == ""

    async def test_rag_enabled_calls_build_rag_context(self):
        body = _make_body(use_rag=True, messages=[Message(role="user", content="query")])
        app_state = MagicMock()
        app_state.config = {}
        with patch("core.endpoints.chat.build_rag_context", new=AsyncMock(return_value="rag_text")) as mock_rag:
            messages, context = await _build_rag_and_system_prompt(body, app_state, "en")
        mock_rag.assert_called_once()
        assert context == "rag_text"


# ─── _dispatch_to_engine ─────────────────────────────────────────────────────

class TestDispatchToEngine:
    async def test_ollama_path(self):
        body = _make_body()
        request = MagicMock()
        app_state = MagicMock()
        with patch("core.endpoints.chat._forward_to_ollama", new=AsyncMock(return_value={"ok": True})) as mock_ollama:
            result = await _dispatch_to_engine("ollama", [], body, request, app_state, "q")
        mock_ollama.assert_called_once()
        assert result == {"ok": True}

    async def test_unknown_engine_falls_back_to_ollama(self):
        body = _make_body()
        request = MagicMock()
        app_state = MagicMock()
        with patch("core.endpoints.chat._forward_to_ollama", new=AsyncMock(return_value={"fallback": True})) as mock_ollama:
            result = await _dispatch_to_engine("unknown_engine", [], body, request, app_state, "q")
        mock_ollama.assert_called_once()
        assert result == {"fallback": True}

    async def test_mlx_path(self):
        body = _make_body()
        request = MagicMock()
        app_state = MagicMock()
        with patch("core.endpoints.chat._forward_to_mlx", new=AsyncMock(return_value={"mlx": True})) as mock_mlx:
            result = await _dispatch_to_engine("mlx", [], body, request, app_state, None)
        mock_mlx.assert_called_once()
        assert result == {"mlx": True}


# ─── _record_engine_metrics ──────────────────────────────────────────────────

class TestRecordEngineMetrics:
    def test_does_not_raise_when_metrics_unavailable(self):
        with patch("builtins.__import__", side_effect=ImportError("no metrics")):
            _record_engine_metrics("ollama", "success", 0.0)

    def test_records_metrics_when_available(self):
        mock_requests = MagicMock()
        mock_duration = MagicMock()
        with patch.dict("sys.modules", {
            "core.metrics.registry": MagicMock(
                CHAT_ENGINE_REQUESTS=mock_requests,
                CHAT_ENGINE_DURATION=mock_duration,
            )
        }):
            _record_engine_metrics("ollama", "success", 0.0)
        mock_requests.labels.assert_called_once_with(engine="ollama", status="success")


# ─── _schedule_episodic_memory ───────────────────────────────────────────────

class TestScheduleEpisodicMemory:
    def test_streaming_response_skipped(self):
        response = MagicMock(spec=StreamingResponse)
        bt = MagicMock(spec=BackgroundTasks)
        _schedule_episodic_memory(response, bt, MagicMock(), "query")
        bt.add_task.assert_not_called()

    def test_dict_response_with_content_schedules_task(self):
        response = {"choices": [{"message": {"content": "resposta"}}]}
        bt = MagicMock(spec=BackgroundTasks)
        _schedule_episodic_memory(response, bt, MagicMock(), "query")
        bt.add_task.assert_called_once()

    def test_dict_response_without_content_no_task(self):
        response = {"choices": [{"message": {"content": ""}}]}
        bt = MagicMock(spec=BackgroundTasks)
        _schedule_episodic_memory(response, bt, MagicMock(), "query")
        bt.add_task.assert_not_called()

    def test_no_last_user_msg_no_task(self):
        response = {"choices": [{"message": {"content": "resposta"}}]}
        bt = MagicMock(spec=BackgroundTasks)
        _schedule_episodic_memory(response, bt, MagicMock(), None)
        bt.add_task.assert_not_called()


# ─── _inject_response_headers ────────────────────────────────────────────────

class TestInjectResponseHeaders:
    def test_dict_response_gets_nexe_engine(self):
        response = {}
        result = _inject_response_headers(response, "ollama", "", None)
        assert result["nexe_engine"] == "ollama"

    def test_dict_rag_active_when_context(self):
        response = {}
        result = _inject_response_headers(response, "ollama", "some context", None)
        assert result["nexe_rag_status"] == "active"

    def test_dict_rag_inactive_when_no_context(self):
        response = {}
        result = _inject_response_headers(response, "ollama", "", None)
        assert result["nexe_rag_status"] == "inactive"

    def test_dict_fallback_set_when_preferred(self):
        response = {}
        result = _inject_response_headers(response, "ollama", "", "mlx")
        assert "nexe_fallback" in result
        assert result["nexe_fallback"]["from"] == "mlx"

    def test_streaming_gets_engine_header(self):
        headers = {}
        response = MagicMock(spec=StreamingResponse)
        response.headers = headers
        _inject_response_headers(response, "ollama", "", None)
        assert headers.get("X-Nexe-Engine") == "ollama"
