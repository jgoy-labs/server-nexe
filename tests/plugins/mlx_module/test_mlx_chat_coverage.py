"""Tests for plugins/mlx_module/core/chat.py — coverage gaps (module-level only)."""


class TestMLXChatNode:
    def test_class_exists(self):
        from plugins.mlx_module.core.chat import MLXChatNode
        assert MLXChatNode is not None

    def test_get_pool_stats_class_method(self):
        from plugins.mlx_module.core.chat import MLXChatNode
        stats = MLXChatNode.get_pool_stats()
        assert isinstance(stats, dict)

    def test_reset_model_class_method(self):
        from plugins.mlx_module.core.chat import MLXChatNode
        MLXChatNode.reset_model()
