"""
Tests for plugins/mlx_module/ — config resolution, prompt cache, manifest.

Covers:
- config.py: tilde expansion, relative path resolution, from_env fallback
- prompt_cache_manager.py: insert/fetch/delete lifecycle
- chat.py: reset_model with no loaded model
- manifest.py: get_module_instance
"""

import os
from unittest.mock import patch

from plugins.mlx_module.core.config import MLXConfig
from plugins.mlx_module.core.prompt_cache_manager import MLXPromptCacheManager
from plugins.mlx_module.manifest import get_module_instance


class TestMLXConfig:

    def test_tilde_expansion(self):
        config = MLXConfig(model_path="~/models/test")
        assert "~" not in config.model_path
        assert config.model_path.startswith("/")

    def test_relative_path_resolved_to_absolute(self):
        config = MLXConfig(model_path="models/test")
        assert os.path.isabs(config.model_path)

    def test_from_env_returns_valid_config(self, monkeypatch):
        monkeypatch.delenv("NEXE_MLX_MODEL", raising=False)
        config = MLXConfig.from_env()
        assert isinstance(config, MLXConfig)


class TestPromptCacheManager:

    def test_insert_fetch_delete_lifecycle(self):
        manager = MLXPromptCacheManager(max_size=10)
        tokens = [1, 2, 3]
        manager.insert_cache("model", tokens, ["cache_data"])

        cache, remaining = manager.fetch_nearest_cache("model", tokens)
        assert cache is not None
        assert remaining == []

        manager._delete("model", tokens)
        cache2, remaining2 = manager.fetch_nearest_cache("model", tokens)
        assert cache2 is None
        assert remaining2 == tokens

    def test_double_insert_updates_cache(self):
        manager = MLXPromptCacheManager(max_size=10)
        tokens = [1, 2, 3]
        manager.insert_cache("model", tokens, ["v1"])
        manager.insert_cache("model", tokens, ["v2"])

        cache, remaining = manager.fetch_nearest_cache("model", tokens)
        assert cache is not None
        assert remaining == []


class TestMLXChatReset:

    def test_reset_model_with_nothing_loaded(self):
        from plugins.mlx_module.core.chat import MLXChatNode
        MLXChatNode._model = None
        MLXChatNode._tokenizer = None
        MLXChatNode._config = None
        with patch("plugins.mlx_module.core.chat.gc.collect"):
            MLXChatNode.reset_model()


class TestMLXManifest:

    def test_get_module_instance_has_metadata(self):
        instance = get_module_instance()
        assert instance is not None
        assert hasattr(instance, 'metadata')
