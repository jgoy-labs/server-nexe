"""
Tests for plugins/llama_cpp_module/chat.py
Covers uncovered lines: 58-61, 65-147, 156-179, 199-257, 272-274, 279-287
"""
import asyncio
import time
import pytest
from unittest.mock import MagicMock, AsyncMock, patch

from plugins.llama_cpp_module.core.chat import LlamaCppChatNode


@pytest.fixture(autouse=True)
def reset_pool():
    """Reset singleton pool before each test."""
    LlamaCppChatNode._pool = None
    LlamaCppChatNode._config = None
    yield
    LlamaCppChatNode._pool = None
    LlamaCppChatNode._config = None


def _make_config():
    config = MagicMock()
    config.model_path = "/fake/model.gguf"
    config.max_sessions = 1
    return config


class TestGetModel:
    """Tests for _get_model (lines 58-61)"""

    def test_get_model_default_session_id(self):
        """Lines 58-59: empty session_id defaults to 'default'"""
        config = _make_config()
        mock_pool = MagicMock()
        mock_pool.get_or_create.return_value = (MagicMock(), True)

        with patch.object(LlamaCppChatNode, '_pool', mock_pool), \
             patch.object(LlamaCppChatNode, '_config', config):
            node = LlamaCppChatNode.__new__(LlamaCppChatNode)
            node.config = config
            model, hit = node._get_model("", "hash123")

        mock_pool.get_or_create.assert_called_once_with("default", "hash123")

    def test_get_model_with_session_id(self):
        """Line 61: normal session_id"""
        config = _make_config()
        mock_pool = MagicMock()
        mock_pool.get_or_create.return_value = (MagicMock(), False)

        with patch.object(LlamaCppChatNode, '_pool', mock_pool), \
             patch.object(LlamaCppChatNode, '_config', config):
            node = LlamaCppChatNode.__new__(LlamaCppChatNode)
            node.config = config
            model, hit = node._get_model("sess1", "hash123")

        mock_pool.get_or_create.assert_called_once_with("sess1", "hash123")


class TestExecute:
    """Tests for execute (lines 65-147)"""

    @pytest.mark.asyncio
    async def test_execute_without_streaming(self):
        """Lines 65-142: non-streaming execution"""
        config = _make_config()
        node = LlamaCppChatNode.__new__(LlamaCppChatNode)
        node.config = config

        mock_model = MagicMock()
        mock_pool = MagicMock()
        mock_pool.get_or_create.return_value = (mock_model, False)

        generate_result = {
            "text": "Hello world",
            "tokens": 10,
            "prompt_tokens": 5,
            "timing": {"prefill_ms": 10, "generation_ms": 50},
        }

        async def fake_to_thread(fn, *args, **kwargs):
            return generate_result

        with patch.object(LlamaCppChatNode, '_pool', mock_pool), \
             patch.object(LlamaCppChatNode, '_config', config), \
             patch("plugins.llama_cpp_module.chat.compute_system_hash", return_value="hash123"), \
             patch("plugins.llama_cpp_module.chat.asyncio.to_thread", side_effect=fake_to_thread), \
             patch("plugins.llama_cpp_module.chat.asyncio.get_running_loop", return_value=MagicMock()):
            result = await node.execute({
                "system": "You are helpful",
                "messages": [{"role": "user", "content": "hi"}],
                "session_id": "test_sess",
            })

        assert result["response"] == "Hello world"
        assert result["tokens"] == 10
        assert result["session_id"] == "test_sess"
        assert result["cache_hit"] is False

    @pytest.mark.asyncio
    async def test_execute_with_streaming(self):
        """Lines 95-99: streaming execution"""
        config = _make_config()
        node = LlamaCppChatNode.__new__(LlamaCppChatNode)
        node.config = config

        mock_pool = MagicMock()
        mock_pool.get_or_create.return_value = (MagicMock(), True)

        generate_result = {
            "text": "Streamed",
            "tokens": 5,
            "prompt_tokens": 3,
            "timing": {"prefill_ms": 5, "generation_ms": 20},
        }

        async def fake_to_thread(fn, *args, **kwargs):
            return generate_result

        with patch.object(LlamaCppChatNode, '_pool', mock_pool), \
             patch.object(LlamaCppChatNode, '_config', config), \
             patch("plugins.llama_cpp_module.chat.compute_system_hash", return_value="h"), \
             patch("plugins.llama_cpp_module.chat.asyncio.to_thread", side_effect=fake_to_thread), \
             patch("plugins.llama_cpp_module.chat.asyncio.get_running_loop", return_value=MagicMock()):
            result = await node.execute({
                "system": "sys",
                "messages": [],
                "stream_callback": MagicMock(),
            })

        assert result["response"] == "Streamed"
        assert result["cache_hit"] is True

    @pytest.mark.asyncio
    async def test_execute_error(self):
        """Lines 144-147: exception during execute"""
        config = _make_config()
        node = LlamaCppChatNode.__new__(LlamaCppChatNode)
        node.config = config

        mock_pool = MagicMock()
        mock_pool.get_or_create.return_value = (MagicMock(), False)

        async def fake_to_thread(fn, *args, **kwargs):
            raise RuntimeError("gen error")

        with patch.object(LlamaCppChatNode, '_pool', mock_pool), \
             patch.object(LlamaCppChatNode, '_config', config), \
             patch("plugins.llama_cpp_module.chat.compute_system_hash", return_value="h"), \
             patch("plugins.llama_cpp_module.chat.asyncio.to_thread", side_effect=fake_to_thread), \
             patch("plugins.llama_cpp_module.chat.asyncio.get_running_loop", return_value=MagicMock()):
            with pytest.raises(RuntimeError, match="gen error"):
                await node.execute({"system": "", "messages": []})


class TestGenerate:
    """Tests for _generate (lines 156-179)"""

    def test_generate_returns_result(self):
        """Lines 156-179: non-streaming generation"""
        config = _make_config()
        node = LlamaCppChatNode.__new__(LlamaCppChatNode)
        node.config = config

        mock_model = MagicMock()
        mock_model.create_chat_completion.return_value = {
            "choices": [{"message": {"content": "Response text"}}],
            "usage": {"completion_tokens": 10, "prompt_tokens": 5},
        }

        result = node._generate(mock_model, "system prompt", [{"role": "user", "content": "hi"}])
        assert result["text"] == "Response text"
        assert result["tokens"] == 10
        assert result["prompt_tokens"] == 5
        assert result["timing"]["prefill_available"] is False


class TestGenerateStreaming:
    """Tests for _generate_streaming (lines 199-257)"""

    def test_streaming_with_content(self):
        """Lines 199-267: streaming generation"""
        config = _make_config()
        node = LlamaCppChatNode.__new__(LlamaCppChatNode)
        node.config = config

        chunks = [
            {"choices": [{"delta": {"content": "Hello"}}], "usage": {}},
            {"choices": [{"delta": {"content": " world"}}], "usage": {}},
            {"choices": [{"delta": {}}], "usage": {"prompt_tokens": 5, "completion_tokens": 2}},
        ]
        mock_model = MagicMock()
        mock_model.create_chat_completion.return_value = iter(chunks)

        callback = MagicMock()
        result = node._generate_streaming(
            mock_model, "sys", [{"role": "user", "content": "hi"}], callback
        )
        assert result["text"] == "Hello world"
        assert callback.call_count == 2

    def test_streaming_no_content_estimates_tokens(self):
        """Lines 246-247: completion_tokens == 0, estimate from text length"""
        config = _make_config()
        node = LlamaCppChatNode.__new__(LlamaCppChatNode)
        node.config = config

        chunks = [
            {"choices": [{"delta": {"content": "Response text here"}}], "usage": {}},
        ]
        mock_model = MagicMock()
        mock_model.create_chat_completion.return_value = iter(chunks)

        result = node._generate_streaming(
            mock_model, "sys", [], MagicMock()
        )
        assert result["tokens"] == len("Response text here") // 4

    def test_streaming_no_first_token(self):
        """Lines 253-255: no content tokens received"""
        config = _make_config()
        node = LlamaCppChatNode.__new__(LlamaCppChatNode)
        node.config = config

        chunks = [
            {"choices": [{"delta": {}}], "usage": {}},
        ]
        mock_model = MagicMock()
        mock_model.create_chat_completion.return_value = iter(chunks)

        result = node._generate_streaming(
            mock_model, "sys", [], MagicMock()
        )
        assert result["text"] == ""
        assert result["timing"]["prefill_ms"] == 0


class TestResetModelAndStats:
    """Tests for reset_model and get_pool_stats (lines 272-274, 279-287)"""

    def test_reset_model_with_pool(self):
        """Lines 272-274: reset with active pool"""
        mock_pool = MagicMock()
        LlamaCppChatNode._pool = mock_pool
        LlamaCppChatNode.reset_model()
        mock_pool.destroy_all.assert_called_once()

    def test_reset_model_no_pool(self):
        """Line 272: no pool, no-op"""
        LlamaCppChatNode._pool = None
        LlamaCppChatNode.reset_model()  # Should not raise

    def test_get_pool_stats_no_pool(self):
        """Lines 279-284: pool is None"""
        LlamaCppChatNode._pool = None
        stats = LlamaCppChatNode.get_pool_stats()
        assert stats["pool_initialized"] is False
        assert stats["active_sessions"] == 0

    def test_get_pool_stats_with_pool(self):
        """Lines 285-287: pool exists"""
        mock_pool = MagicMock()
        mock_pool.get_stats.return_value = {"sessions": 2}
        LlamaCppChatNode._pool = mock_pool
        stats = LlamaCppChatNode.get_pool_stats()
        assert stats["pool_initialized"] is True
        assert stats["sessions"] == 2
