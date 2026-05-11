"""Tests for plugins/llama_cpp_module/core/chat.py — coverage gaps."""
from unittest.mock import MagicMock, patch


class TestLlamaCppChatNodeInit:
    def test_init_creates_pool(self):
        mock_config = MagicMock()
        mock_config.max_sessions = 2
        with patch("plugins.llama_cpp_module.core.chat.ModelPool") as MockPool:
            from plugins.llama_cpp_module.core.chat import LlamaCppChatNode
            LlamaCppChatNode._pool = None
            LlamaCppChatNode._config = None
            node = LlamaCppChatNode(config=mock_config)
            assert node.config is mock_config

    def test_get_pool_stats(self):
        from plugins.llama_cpp_module.core.chat import LlamaCppChatNode
        stats = LlamaCppChatNode.get_pool_stats()
        assert stats is not None
