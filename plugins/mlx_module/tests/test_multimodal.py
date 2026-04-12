"""
Tests suport multimodal (VLM) a mlx_module.
No requereix mlx, mlx_lm ni mlx_vlm instal·lats — tot mockejat.
"""

import json
import os
import pytest
from pathlib import Path
from unittest.mock import MagicMock, patch


# ── _detect_vlm_capability ───────────────────────────────────────────────────

class TestDetectVlmCapability:

    def _write_config(self, tmp_path, architectures):
        config = {"architectures": architectures}
        (tmp_path / "config.json").write_text(json.dumps(config))
        return str(tmp_path)

    def test_text_model_returns_false(self, tmp_path):
        path = self._write_config(tmp_path, ["Qwen2ForCausalLM"])
        from plugins.mlx_module.core.chat import _detect_vlm_capability
        assert _detect_vlm_capability(path) is False

    def test_vlm_qwen2_returns_true(self, tmp_path):
        path = self._write_config(tmp_path, ["Qwen2VLForConditionalGeneration"])
        from plugins.mlx_module.core.chat import _detect_vlm_capability
        assert _detect_vlm_capability(path) is True

    def test_vlm_llava_returns_true(self, tmp_path):
        path = self._write_config(tmp_path, ["LlavaForConditionalGeneration"])
        from plugins.mlx_module.core.chat import _detect_vlm_capability
        assert _detect_vlm_capability(path) is True

    def test_no_config_json_returns_false(self, tmp_path):
        from plugins.mlx_module.core.chat import _detect_vlm_capability
        assert _detect_vlm_capability(str(tmp_path)) is False

    def test_empty_path_returns_false(self):
        from plugins.mlx_module.core.chat import _detect_vlm_capability
        assert _detect_vlm_capability("") is False


# ── _get_model bifurcació ────────────────────────────────────────────────────

class TestGetModelBifurcation:

    def _reset_singleton(self):
        from plugins.mlx_module.core.chat import MLXChatNode
        MLXChatNode._model = None
        MLXChatNode._tokenizer = None
        MLXChatNode._config = None
        MLXChatNode._is_vlm = False

    def test_text_model_uses_mlx_lm(self, tmp_path):
        """Model text-only → mlx_lm.load()."""
        (tmp_path / "config.json").write_text(json.dumps({"architectures": ["Qwen2ForCausalLM"]}))
        self._reset_singleton()

        from plugins.mlx_module.core.config import MLXConfig
        from plugins.mlx_module.core.chat import MLXChatNode

        config = MLXConfig(model_path=str(tmp_path))
        node = MLXChatNode(config=config)

        mock_load = MagicMock(return_value=(MagicMock(), MagicMock()))
        mock_mlx_lm = MagicMock()
        mock_mlx_lm.load = mock_load
        with patch.dict('sys.modules', {'mlx_lm': mock_mlx_lm}):
            node._get_model()

        mock_load.assert_called_once_with(str(tmp_path))
        assert MLXChatNode._is_vlm is False

    def test_vlm_model_uses_mlx_vlm(self, tmp_path):
        """Model VLM → mlx_vlm.load()."""
        (tmp_path / "config.json").write_text(
            json.dumps({"architectures": ["Qwen2VLForConditionalGeneration"]})
        )
        self._reset_singleton()

        from plugins.mlx_module.core.config import MLXConfig
        from plugins.mlx_module.core.chat import MLXChatNode

        config = MLXConfig(model_path=str(tmp_path))
        node = MLXChatNode(config=config)

        mock_load = MagicMock(return_value=(MagicMock(), MagicMock()))
        mock_mlx_vlm = MagicMock()
        mock_mlx_vlm.load = mock_load
        with patch.dict('sys.modules', {'mlx_vlm': mock_mlx_vlm}):
            node._get_model()

        mock_load.assert_called_once_with(str(tmp_path))
        assert MLXChatNode._is_vlm is True


# ── execute() bifurcació ─────────────────────────────────────────────────────

class TestMLXExecuteBifurcation:

    def _reset_singleton(self):
        from plugins.mlx_module.core.chat import MLXChatNode
        MLXChatNode._model = None
        MLXChatNode._tokenizer = None
        MLXChatNode._config = None
        MLXChatNode._is_vlm = False

    @pytest.mark.asyncio
    async def test_text_only_uses_generate_blocking(self):
        """Sense imatges → _generate_blocking (path normal)."""
        self._reset_singleton()

        from plugins.mlx_module.core.config import MLXConfig
        from plugins.mlx_module.core.chat import MLXChatNode

        config = MLXConfig(model_path="/fake/text_model")
        node = MLXChatNode(config=config)
        MLXChatNode._is_vlm = False

        expected = {
            "text": "Hola!", "tokens": 3, "prompt_tokens": 10,
            "tokens_per_second": 30.0,
            "prefix_reused": False, "cached_tokens": 0,
            "actual_prefill_tokens": 10,
            "prompt_tps": 100.0,
            "peak_memory_mb": 0, "identity_hash": "abc",
        }

        with patch("asyncio.to_thread") as mock_thread:
            mock_thread.return_value = expected
            result = await node.execute({
                "system": "",
                "messages": [{"role": "user", "content": "Hola"}],
            })

        # Comprova que s'ha cridat _generate_blocking (no _generate_vlm)
        call_args = mock_thread.call_args
        assert call_args[0][0] == node._generate_blocking

    @pytest.mark.asyncio
    async def test_images_with_vlm_uses_generate_vlm(self):
        """Amb imatges i VLM actiu → _generate_vlm."""
        self._reset_singleton()

        from plugins.mlx_module.core.config import MLXConfig
        from plugins.mlx_module.core.chat import MLXChatNode

        config = MLXConfig(model_path="/fake/vlm_model")
        node = MLXChatNode(config=config)
        MLXChatNode._is_vlm = True  # Simula VLM carregat

        vlm_result = {
            "text": "Veig un gat.", "tokens": 4,
            "tokens_per_second": 20.0,
            "prompt_tokens": 0,
            "prefix_reused": False, "cached_tokens": 0,
            "actual_prefill_tokens": 0,
            "prompt_tps": 0,
            "peak_memory_mb": 0, "identity_hash": "",
            "vlm": True,
        }

        with patch("asyncio.to_thread") as mock_thread:
            mock_thread.return_value = vlm_result
            result = await node.execute({
                "system": "",
                "messages": [{"role": "user", "content": "Descriu la imatge"}],
                "images": [b"\xff\xd8\xff" + b"\x00" * 100],
            })

        # Comprova que s'ha cridat _generate_vlm (no _generate_blocking)
        call_args = mock_thread.call_args
        assert call_args[0][0] == node._generate_vlm
        # La resposta és vàlida
        assert result.get("response") == "Veig un gat."
