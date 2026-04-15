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

    # ── Detector ampliat: arquitectures VLM noves ─────────────────────────

    def test_vlm_qwen25_vl_returns_true(self, tmp_path):
        path = self._write_config(tmp_path, ["Qwen2_5_VLForConditionalGeneration"])
        from plugins.mlx_module.core.chat import _detect_vlm_capability
        assert _detect_vlm_capability(path) is True

    def test_vlm_qwen35_moe_returns_true(self, tmp_path):
        """Qwen3.5 MoE VLM (cas real detectat 2026-04-15)."""
        path = self._write_config(tmp_path, ["Qwen3_5MoeForConditionalGeneration"])
        from plugins.mlx_module.core.chat import _detect_vlm_capability
        assert _detect_vlm_capability(path) is True

    def test_vlm_minicpmv_returns_true(self, tmp_path):
        path = self._write_config(tmp_path, ["MiniCPMV"])
        from plugins.mlx_module.core.chat import _detect_vlm_capability
        assert _detect_vlm_capability(path) is True

    # ── Detector secundari: vision_config al config.json ──────────────────

    def test_vision_config_present_returns_true(self, tmp_path):
        """Architecture desconeguda però config.json té vision_config → VLM."""
        config = {
            "architectures": ["UnknownFutureVLM"],
            "vision_config": {"hidden_size": 1024},
        }
        (tmp_path / "config.json").write_text(json.dumps(config))
        from plugins.mlx_module.core.chat import _detect_vlm_capability
        assert _detect_vlm_capability(str(tmp_path)) is True

    def test_vision_config_empty_dict_ignored(self, tmp_path):
        """vision_config buit {} NO compta com a VLM."""
        config = {"architectures": ["Qwen2ForCausalLM"], "vision_config": {}}
        (tmp_path / "config.json").write_text(json.dumps(config))
        from plugins.mlx_module.core.chat import _detect_vlm_capability
        assert _detect_vlm_capability(str(tmp_path)) is False

    # ── Detector terciari: safetensors weight map ──────────────────────────

    def _write_index(self, tmp_path, weight_keys):
        (tmp_path / "model.safetensors.index.json").write_text(
            json.dumps({"weight_map": {k: "model-00001-of-00001.safetensors" for k in weight_keys}})
        )

    def test_weight_map_vision_tower_returns_true(self, tmp_path):
        """Architecture desconeguda + vision_tower al safetensors → VLM."""
        self._write_config(tmp_path, ["UnknownArchForCausalLM"])
        self._write_index(tmp_path, [
            "model.layers.0.self_attn.q_proj.weight",
            "vision_tower.blocks.0.attn.qkv.weight",
        ])
        from plugins.mlx_module.core.chat import _detect_vlm_capability
        assert _detect_vlm_capability(str(tmp_path)) is True

    def test_weight_map_mm_projector_returns_true(self, tmp_path):
        self._write_config(tmp_path, ["UnknownArch"])
        self._write_index(tmp_path, ["mm_projector.0.weight", "model.embed_tokens.weight"])
        from plugins.mlx_module.core.chat import _detect_vlm_capability
        assert _detect_vlm_capability(str(tmp_path)) is True

    def test_weight_map_no_vision_keys_returns_false(self, tmp_path):
        """Text-only real: arquitectura desconeguda + cap key vision → False."""
        self._write_config(tmp_path, ["Qwen3NextForCausalLM"])
        self._write_index(tmp_path, [
            "model.layers.0.self_attn.q_proj.weight",
            "model.embed_tokens.weight",
        ])
        from plugins.mlx_module.core.chat import _detect_vlm_capability
        assert _detect_vlm_capability(str(tmp_path)) is False

    def test_malformed_index_falls_through_to_false(self, tmp_path):
        """Index JSON corrupte no ha de fer petar el detector."""
        self._write_config(tmp_path, ["Qwen2ForCausalLM"])
        (tmp_path / "model.safetensors.index.json").write_text("{broken json")
        from plugins.mlx_module.core.chat import _detect_vlm_capability
        assert _detect_vlm_capability(str(tmp_path)) is False

    def test_vlm_gemma4_returns_true(self, tmp_path):
        """Gemma4 (imatge, sense vídeo) — cas real default VLM server-nexe."""
        path = self._write_config(tmp_path, ["Gemma4ForConditionalGeneration"])
        from plugins.mlx_module.core.chat import _detect_vlm_capability
        assert _detect_vlm_capability(path) is True


# ── _generate_vlm compatibilitat mlx-vlm 0.4.x ──────────────────────────────

class TestGenerateVlm04Api:
    """Verifica que el flux VLM és compatible amb mlx-vlm ≥ 0.4:
    - image passat com a path (str), no PIL.Image
    - result.text extret de GenerationResult, no string pelat
    - mètriques reals (prompt_tokens, generation_tps, peak_memory)
    """

    def _reset_singleton(self):
        from plugins.mlx_module.core.chat import MLXChatNode
        MLXChatNode._model = None
        MLXChatNode._tokenizer = None
        MLXChatNode._config = None
        MLXChatNode._is_vlm = False

    def test_generate_vlm_passes_path_not_pil(self, tmp_path):
        """mlx-vlm 0.4 exigeix path (str); no acceptem PIL.Image."""
        self._reset_singleton()
        from plugins.mlx_module.core.config import MLXConfig
        from plugins.mlx_module.core.chat import MLXChatNode

        config = MLXConfig(model_path="/fake/vlm_model")
        node = MLXChatNode(config=config)
        # Simular model ja carregat (bypass _get_model)
        MLXChatNode._is_vlm = True
        MLXChatNode._model = MagicMock()
        MLXChatNode._tokenizer = MagicMock()
        MLXChatNode._tokenizer.config = {}

        # Mock GenerationResult dataclass-like
        gen_result = MagicMock()
        gen_result.text = "Veig un gat a la imatge."
        gen_result.prompt_tokens = 42
        gen_result.generation_tokens = 7
        gen_result.prompt_tps = 120.0
        gen_result.generation_tps = 45.0
        gen_result.peak_memory = 3400.0

        mock_generate = MagicMock(return_value=gen_result)
        mock_template = MagicMock(return_value="formatted prompt")

        mock_mlx_vlm = MagicMock()
        mock_mlx_vlm.generate = mock_generate
        mock_prompt_utils = MagicMock()
        mock_prompt_utils.apply_chat_template = mock_template

        with patch.dict('sys.modules', {
            'mlx_vlm': mock_mlx_vlm,
            'mlx_vlm.prompt_utils': mock_prompt_utils,
        }):
            out = node._generate_vlm(
                system="",
                messages=[{"role": "user", "content": "Què veus?"}],
                images=[b"\xff\xd8\xff" + b"\x00" * 100],  # JPEG magic
            )

        # Verifica que l'argument image és str (path de tempfile), no PIL
        call = mock_generate.call_args
        image_arg = call.kwargs["image"]
        assert isinstance(image_arg, str)
        assert image_arg.endswith(".img")

        # Verifica extracció de .text del GenerationResult
        assert out["text"] == "Veig un gat a la imatge."
        assert out["vlm"] is True

        # Mètriques reals mlx-vlm 0.4 (no zeros com abans)
        assert out["prompt_tokens"] == 42
        assert out["tokens"] == 7
        assert out["prompt_tps"] == 120.0
        assert out["peak_memory_mb"] == 3400.0

    def test_generate_vlm_handles_legacy_string_result(self, tmp_path):
        """Robustesa: si mlx_vlm retornés str (versió antiga), no peta."""
        self._reset_singleton()
        from plugins.mlx_module.core.config import MLXConfig
        from plugins.mlx_module.core.chat import MLXChatNode

        config = MLXConfig(model_path="/fake/vlm_model")
        node = MLXChatNode(config=config)
        MLXChatNode._is_vlm = True
        MLXChatNode._model = MagicMock()
        MLXChatNode._tokenizer = MagicMock()
        MLXChatNode._tokenizer.config = {}

        mock_generate = MagicMock(return_value="response str legacy")
        mock_mlx_vlm = MagicMock()
        mock_mlx_vlm.generate = mock_generate
        mock_prompt_utils = MagicMock()
        mock_prompt_utils.apply_chat_template = MagicMock(return_value="p")

        with patch.dict('sys.modules', {
            'mlx_vlm': mock_mlx_vlm,
            'mlx_vlm.prompt_utils': mock_prompt_utils,
        }):
            out = node._generate_vlm(
                system="", messages=[{"role": "user", "content": "x"}],
                images=[b"\xff\xd8\xff"],
            )
        # Fallback: si no té .text, str(result)
        assert "response str legacy" in out["text"]


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
