"""
Tests for plugins/mlx_module/chat.py
Covers uncovered lines: 69-75, 84-100, 116-222, 237-287, 295-323, 329-337
"""
import sys
import gc
import pytest
from unittest.mock import MagicMock, patch

from plugins.mlx_module.core.chat import MLXChatNode


@pytest.fixture(autouse=True)
def reset_singleton():
    """Reset MLXChatNode singleton state."""
    MLXChatNode._model = None
    MLXChatNode._tokenizer = None
    MLXChatNode._config = None
    yield
    MLXChatNode._model = None
    MLXChatNode._tokenizer = None
    MLXChatNode._config = None


def _make_config(model_path="/fake/model"):
    config = MagicMock()
    config.model_path = model_path
    config.max_kv_size = 4096
    config.temperature = 0.7
    config.top_p = 0.9
    config.max_tokens = 2048
    return config


class TestInit:
    """Tests for __init__ (lines 69-75)"""

    def test_init_sets_config(self):
        """Lines 69-75: config set and singleton updated"""
        config = _make_config()
        node = MLXChatNode(config=config)
        assert node.config is config
        assert MLXChatNode._config is config

    def test_init_force_reload_on_path_change(self):
        """Lines 72-75: different model_path forces reload"""
        config1 = _make_config("/model/a")
        config2 = _make_config("/model/b")

        MLXChatNode(config=config1)
        MLXChatNode._model = MagicMock()  # Simulate loaded model

        MLXChatNode(config=config2)
        assert MLXChatNode._model is None  # Reset to force reload


class TestGetModel:
    """Tests for _get_model (lines 84-100)"""

    def test_lazy_loads_model(self):
        """Lines 84-100: loads model on first call"""
        config = _make_config()
        node = MLXChatNode.__new__(MLXChatNode)
        node.config = config
        MLXChatNode._config = config

        mock_model = MagicMock()
        mock_tokenizer = MagicMock()

        mock_mlx_lm = MagicMock()
        mock_mlx_lm.load.return_value = (mock_model, mock_tokenizer)

        with patch.dict(sys.modules, {"mlx_lm": mock_mlx_lm}):
            model, tokenizer = node._get_model()

        assert model is mock_model
        assert tokenizer is mock_tokenizer

    def test_reuses_cached_model(self):
        """Lines 84: model already loaded, skip load"""
        config = _make_config()
        node = MLXChatNode.__new__(MLXChatNode)
        node.config = config
        MLXChatNode._config = config

        cached_model = MagicMock()
        cached_tokenizer = MagicMock()
        MLXChatNode._model = cached_model
        MLXChatNode._tokenizer = cached_tokenizer

        model, tokenizer = node._get_model()
        assert model is cached_model
        assert tokenizer is cached_tokenizer


class TestExecute:
    """Tests for execute (lines 116-222)"""

    @pytest.mark.asyncio
    async def test_execute_success(self):
        """Lines 116-213: successful execution"""
        config = _make_config()
        node = MLXChatNode.__new__(MLXChatNode)
        node.config = config
        MLXChatNode._config = config

        generate_result = {
            "text": "Generated text",
            "tokens": 20,
            "prompt_tokens": 10,
            "tokens_per_second": 50.0,
            "prompt_tps": 100.0,
            "prefix_reused": False,
            "cached_tokens": 0,
            "actual_prefill_tokens": 10,
            "peak_memory_mb": 500.0,
            "cache_active": True,
            "identity_hash": "abc123",
        }

        async def fake_to_thread(fn, *args, **kwargs):
            return generate_result

        with patch("plugins.mlx_module.core.chat.asyncio.to_thread", side_effect=fake_to_thread), \
             patch("plugins.mlx_module.core.chat.asyncio.get_running_loop", return_value=MagicMock()):
            result = await node.execute({
                "system": "You are a helper",
                "messages": [{"role": "user", "content": "hello"}],
                "session_id": "sess1",
            })

        assert result["response"] == "Generated text"
        assert result["tokens"] == 20
        assert result["prefix_reuse"] is False
        assert "timing" in result

    @pytest.mark.asyncio
    async def test_execute_with_prefix_reuse(self):
        """Lines 164-167: cached_tokens > 0"""
        config = _make_config()
        node = MLXChatNode.__new__(MLXChatNode)
        node.config = config
        MLXChatNode._config = config

        generate_result = {
            "text": "Response",
            "tokens": 10,
            "prompt_tokens": 15,
            "tokens_per_second": 40.0,
            "prompt_tps": 80.0,
            "prefix_reused": True,
            "cached_tokens": 10,
            "actual_prefill_tokens": 5,
            "peak_memory_mb": 300.0,
            "cache_active": True,
            "identity_hash": "def456",
        }

        async def fake_to_thread(fn, *args, **kwargs):
            return generate_result

        with patch("plugins.mlx_module.core.chat.asyncio.to_thread", side_effect=fake_to_thread), \
             patch("plugins.mlx_module.core.chat.asyncio.get_running_loop", return_value=MagicMock()):
            result = await node.execute({
                "system": "sys",
                "messages": [],
            })

        assert result["prefix_reuse"] is True
        assert result["cached_tokens"] == 10
        assert result["reuse_ratio"] > 1.0

    @pytest.mark.asyncio
    async def test_execute_with_stream_callback(self):
        """Lines 148: stream_callback provided"""
        config = _make_config()
        node = MLXChatNode.__new__(MLXChatNode)
        node.config = config
        MLXChatNode._config = config

        generate_result = {
            "text": "Streamed",
            "tokens": 5,
            "prompt_tokens": 3,
            "tokens_per_second": 30.0,
            "prompt_tps": 60.0,
            "prefix_reused": False,
            "cached_tokens": 0,
            "actual_prefill_tokens": 3,
            "peak_memory_mb": 200.0,
        }

        async def fake_to_thread(fn, *args, **kwargs):
            return generate_result

        with patch("plugins.mlx_module.core.chat.asyncio.to_thread", side_effect=fake_to_thread), \
             patch("plugins.mlx_module.core.chat.asyncio.get_running_loop", return_value=MagicMock()):
            result = await node.execute({
                "system": "s",
                "messages": [],
                "stream_callback": MagicMock(),
            })

        assert result["response"] == "Streamed"

    @pytest.mark.asyncio
    async def test_execute_error(self):
        """Lines 215-222: exception during execute"""
        config = _make_config()
        node = MLXChatNode.__new__(MLXChatNode)
        node.config = config
        MLXChatNode._config = config

        async def fake_to_thread(fn, *args, **kwargs):
            raise RuntimeError("mlx error")

        with patch("plugins.mlx_module.core.chat.asyncio.to_thread", side_effect=fake_to_thread), \
             patch("plugins.mlx_module.core.chat.asyncio.get_running_loop", return_value=MagicMock()):
            with pytest.raises(RuntimeError, match="mlx error"):
                await node.execute({"system": "", "messages": []})


class TestGenerateBlocking:
    """Tests for _generate_blocking (lines 237-287)"""

    def test_generate_blocking(self):
        """Lines 237-290: full blocking generation pipeline"""
        config = _make_config()
        node = MLXChatNode.__new__(MLXChatNode)
        node.config = config
        MLXChatNode._config = config

        mock_model = MagicMock()
        mock_tokenizer = MagicMock()
        MLXChatNode._model = mock_model
        MLXChatNode._tokenizer = mock_tokenizer

        mock_sampler = MagicMock()
        mock_cache_mgr = MagicMock()

        mock_mlx_lm = MagicMock()
        mock_mlx_lm.sample_utils.make_sampler.return_value = mock_sampler

        with patch("plugins.mlx_module.core.chat.compute_system_hash", return_value="hash1"), \
             patch("plugins.mlx_module.core.chat.prepare_tokens", return_value=([1, 2, 3], [1, 2], [], [])), \
             patch("plugins.mlx_module.core.chat.lookup_prefix_cache", return_value=(MagicMock(), 1, True)), \
             patch("plugins.mlx_module.core.chat.determine_tokens_to_process", return_value=([3], 1)), \
             patch("plugins.mlx_module.core.chat.run_streaming_generation", return_value=("output", MagicMock(), None)), \
             patch("plugins.mlx_module.core.chat.save_cache_post_generation"), \
             patch("plugins.mlx_module.core.chat.extract_metrics", return_value={"text": "output", "tokens": 5}), \
             patch.dict(sys.modules, {"mlx_lm": mock_mlx_lm, "mlx_lm.sample_utils": mock_mlx_lm.sample_utils}), \
             patch("plugins.mlx_module.core.prompt_cache_manager.get_prompt_cache_manager", return_value=mock_cache_mgr, create=True):
            result = node._generate_blocking("sys", [{"role": "user", "content": "hi"}], [], None, "sess")

        assert result["text"] == "output"


class TestResetModel:
    """Tests for reset_model (lines 295-323)"""

    def test_reset_model_clears_everything(self):
        """Lines 295-323: resets model, tokenizer, config, cache"""
        MLXChatNode._model = MagicMock()
        MLXChatNode._tokenizer = MagicMock()
        MLXChatNode._config = _make_config()

        mock_cache_mgr = MagicMock()
        mock_mx = MagicMock()

        # The import inside the method is `from .prompt_cache_manager import get_prompt_cache_manager`
        # We need to make the module available for that relative import
        mock_pcm_mod = MagicMock()
        mock_pcm_mod.get_prompt_cache_manager.return_value = mock_cache_mgr

        with patch.dict(sys.modules, {
            "plugins.mlx_module.core.prompt_cache_manager": mock_pcm_mod,
            "mlx": MagicMock(), "mlx.core": mock_mx
        }):
            MLXChatNode.reset_model()

        assert MLXChatNode._model is None
        assert MLXChatNode._tokenizer is None
        assert MLXChatNode._config is None
        mock_cache_mgr.clear.assert_called_once()

    def test_reset_model_handles_cache_error(self):
        """Lines 301-302: cache manager error handled"""
        MLXChatNode._model = MagicMock()
        MLXChatNode._tokenizer = MagicMock()
        MLXChatNode._config = _make_config()

        mock_mx = MagicMock()
        # Make get_prompt_cache_manager raise
        mock_pcm = MagicMock()
        mock_pcm.get_prompt_cache_manager.side_effect = Exception("cache err")

        with patch.dict(sys.modules, {
            "plugins.mlx_module.core.prompt_cache_manager": mock_pcm,
            "mlx": MagicMock(), "mlx.core": mock_mx
        }):
            MLXChatNode.reset_model()

        assert MLXChatNode._model is None

    def test_reset_model_handles_mlx_clear_error(self):
        """Lines 319-320: mlx clear_cache error handled"""
        MLXChatNode._model = MagicMock()
        MLXChatNode._config = _make_config()

        mock_pcm = MagicMock()
        mock_pcm.get_prompt_cache_manager.return_value = MagicMock()

        mock_mx = MagicMock()
        mock_mx.clear_cache.side_effect = Exception("mlx err")

        with patch.dict(sys.modules, {
            "plugins.mlx_module.core.prompt_cache_manager": mock_pcm,
            "mlx": MagicMock(), "mlx.core": mock_mx
        }):
            MLXChatNode.reset_model()

        assert MLXChatNode._model is None


class TestGetPoolStats:
    """Tests for get_pool_stats (lines 329-337)"""

    def test_stats_no_model(self):
        """Lines 329-337: model not loaded"""
        MLXChatNode._model = None
        MLXChatNode._config = None

        mock_pcm = MagicMock()
        mock_pcm.get_prompt_cache_manager.return_value = MagicMock(get_stats=MagicMock(return_value={}))

        with patch.dict(sys.modules, {"plugins.mlx_module.core.prompt_cache_manager": mock_pcm}):
            stats = MLXChatNode.get_pool_stats()

        assert stats["model_loaded"] is False
        assert stats["model_path"] is None

    def test_stats_with_model(self):
        """Lines 329-337: model loaded"""
        MLXChatNode._model = MagicMock()
        MLXChatNode._config = _make_config("/my/model")

        mock_cache_mgr = MagicMock()
        mock_cache_mgr.get_stats.return_value = {"entries": 3}
        mock_pcm = MagicMock()
        mock_pcm.get_prompt_cache_manager.return_value = mock_cache_mgr

        with patch.dict(sys.modules, {"plugins.mlx_module.core.prompt_cache_manager": mock_pcm}):
            stats = MLXChatNode.get_pool_stats()

        assert stats["model_loaded"] is True
        assert stats["model_path"] == "/my/model"
        assert stats["cache_manager"]["entries"] == 3

    def test_stats_cache_manager_error(self):
        """Lines 334-335: cache manager stats fail"""
        MLXChatNode._model = None
        MLXChatNode._config = None

        mock_pcm = MagicMock()
        mock_pcm.get_prompt_cache_manager.side_effect = Exception("stats err")

        with patch.dict(sys.modules, {"plugins.mlx_module.core.prompt_cache_manager": mock_pcm}):
            stats = MLXChatNode.get_pool_stats()

        assert stats["model_loaded"] is False
        assert stats["cache_manager"] == {}
