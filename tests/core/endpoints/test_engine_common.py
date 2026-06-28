"""
------------------------------------
Server Nexe
Author: Jordi Goy
Location: tests/core/endpoints/test_engine_common.py
Description: Unit tests for shared engine forwarding helpers (_common.py).

www.jgoy.net · https://server-nexe.org
------------------------------------
"""

import pytest
from unittest.mock import MagicMock, AsyncMock, patch

MODULE = "core.endpoints.chat_engines._common"


class TestExtractLastUserMsg:

    def test_returns_last_user_content(self):
        from core.endpoints.chat_engines._common import extract_last_user_msg

        messages = [
            {"role": "system", "content": "be helpful"},
            {"role": "user", "content": "first question"},
            {"role": "assistant", "content": "answer"},
            {"role": "user", "content": "second question"},
        ]
        assert extract_last_user_msg(messages) == "second question"

    def test_empty_messages_returns_none(self):
        from core.endpoints.chat_engines._common import extract_last_user_msg

        assert extract_last_user_msg([]) is None

    def test_no_user_messages_returns_none(self):
        from core.endpoints.chat_engines._common import extract_last_user_msg

        messages = [{"role": "system", "content": "sys"}, {"role": "assistant", "content": "hi"}]
        assert extract_last_user_msg(messages) is None


class TestSeparateMessages:

    def test_separates_system_from_user(self):
        from core.endpoints.chat_engines._common import separate_messages

        messages = [
            {"role": "system", "content": "be helpful"},
            {"role": "user", "content": "hello"},
            {"role": "assistant", "content": "hi"},
        ]
        system_msg, user_msgs = separate_messages(messages)
        assert system_msg == "be helpful"
        assert len(user_msgs) == 2
        assert user_msgs[0]["role"] == "user"
        assert user_msgs[1]["role"] == "assistant"

    def test_no_system_message(self):
        from core.endpoints.chat_engines._common import separate_messages

        messages = [{"role": "user", "content": "hello"}]
        system_msg, user_msgs = separate_messages(messages)
        assert system_msg == ""
        assert len(user_msgs) == 1


class TestDeriveSessionId:

    def test_uses_session_id_header(self):
        from core.endpoints.chat_engines._common import derive_session_id

        req = MagicMock()
        req.headers = {"x-session-id": "my-session", "x-api-key": "key123"}
        assert derive_session_id(req) == "my-session"

    def test_falls_back_to_api_key_hash(self):
        from core.endpoints.chat_engines._common import derive_session_id

        headers = MagicMock()
        headers.get = lambda k, default="": {
            "x-session-id": None, "x-api-key": "testkey", "authorization": "",
        }.get(k, default)
        req = MagicMock()
        req.headers = headers
        result = derive_session_id(req)
        assert result.startswith("sess_")
        assert len(result) == len("sess_") + 16


class TestBuildOpenaiResponse:

    def test_correct_structure(self):
        from core.endpoints.chat_engines._common import build_openai_response

        result = {"response": "hello world", "prompt_tokens": 10, "tokens": 5, "context_used": 15}
        resp = build_openai_response(result, "test-model", "mlx")

        assert resp["object"] == "chat.completion"
        assert resp["model"] == "test-model"
        assert resp["id"].startswith("mlx-")
        assert resp["choices"][0]["message"]["content"] == "hello world"
        assert resp["choices"][0]["finish_reason"] == "stop"
        assert resp["usage"]["prompt_tokens"] == 10
        assert resp["usage"]["completion_tokens"] == 5
        assert resp["usage"]["total_tokens"] == 15


class TestResolveLoadedModelName:
    """B075-C3: report the model that actually ran, never request.model."""

    def _module_with_path(self, model_path):
        module = MagicMock()
        module._node = MagicMock()
        module._node.config.model_path = model_path
        return module

    def test_returns_basename_of_loaded_model(self):
        from core.endpoints.chat_engines._common import resolve_loaded_model_name

        module = self._module_with_path("/Users/x/storage/models/Qwen3-32B-MLX-4bit")
        assert resolve_loaded_model_name(module, "mlx-local") == "Qwen3-32B-MLX-4bit"

    def test_returns_basename_of_gguf_file(self):
        from core.endpoints.chat_engines._common import resolve_loaded_model_name

        module = self._module_with_path("/Users/x/models/gemma-2-27b-it-Q4_K_M.gguf")
        assert resolve_loaded_model_name(module, "llama-cpp-local") == "gemma-2-27b-it-Q4_K_M.gguf"

    def test_never_leaks_absolute_path(self):
        from core.endpoints.chat_engines._common import resolve_loaded_model_name

        module = self._module_with_path("/Users/secret/home/models/Qwen3-32B-MLX-4bit")
        result = resolve_loaded_model_name(module, "mlx-local")
        assert "/Users/secret" not in result
        assert result == "Qwen3-32B-MLX-4bit"

    def test_node_none_returns_fallback(self):
        from core.endpoints.chat_engines._common import resolve_loaded_model_name

        module = MagicMock()
        module._node = None
        assert resolve_loaded_model_name(module, "mlx-local") == "mlx-local"

    def test_empty_model_path_returns_fallback(self):
        from core.endpoints.chat_engines._common import resolve_loaded_model_name

        module = self._module_with_path("")
        assert resolve_loaded_model_name(module, "llama-cpp-local") == "llama-cpp-local"

    def test_non_string_model_path_returns_fallback(self):
        from core.endpoints.chat_engines._common import resolve_loaded_model_name

        # A bare mock (not a real loaded config) must not crash Path(); fall back.
        module = MagicMock()
        assert resolve_loaded_model_name(module, "mlx-local") == "mlx-local"


class TestFallbackToOllama:

    @pytest.mark.asyncio
    async def test_calls_forward_to_ollama(self):
        from core.endpoints.chat_engines._common import fallback_to_ollama

        mock_forward = AsyncMock(return_value={"ok": True})
        with patch("core.endpoints.chat_engines._common._forward_to_ollama_lazy", mock_forward):
            result = await fallback_to_ollama(
                messages=[{"role": "user", "content": "hi"}],
                request=MagicMock(),
                app_state=MagicMock(),
                user_msg="hi",
                from_engine="mlx",
                reason="module_unavailable",
            )
        assert result == {"ok": True}
        mock_forward.assert_called_once()
