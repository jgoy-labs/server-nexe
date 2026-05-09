"""
Tests for multimodal (VLM) support in mlx_module.
Does not require mlx, mlx_lm or mlx_vlm installed — everything is mocked.
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

    # ── Extended detector: new VLM architectures ──────────────────────────

    def test_vlm_qwen25_vl_returns_true(self, tmp_path):
        path = self._write_config(tmp_path, ["Qwen2_5_VLForConditionalGeneration"])
        from plugins.mlx_module.core.chat import _detect_vlm_capability
        assert _detect_vlm_capability(path) is True

    def test_vlm_qwen35_moe_returns_true(self, tmp_path):
        """Qwen3.5 MoE VLM (real case detected 2026-04-15)."""
        path = self._write_config(tmp_path, ["Qwen3_5MoeForConditionalGeneration"])
        from plugins.mlx_module.core.chat import _detect_vlm_capability
        assert _detect_vlm_capability(path) is True

    def test_vlm_qwen3_vl_returns_true(self, tmp_path):
        """Qwen3VLForConditionalGeneration — direct Qwen3 VLM architecture."""
        path = self._write_config(tmp_path, ["Qwen3VLForConditionalGeneration"])
        from plugins.mlx_module.core.chat import _detect_vlm_capability
        assert _detect_vlm_capability(path) is True

    def test_vlm_minicpmv_returns_true(self, tmp_path):
        path = self._write_config(tmp_path, ["MiniCPMV"])
        from plugins.mlx_module.core.chat import _detect_vlm_capability
        assert _detect_vlm_capability(path) is True

    # ── Secondary detector: vision_config in config.json ─────────────────

    def test_vision_config_present_returns_true(self, tmp_path):
        """Unknown architecture but config.json has vision_config → VLM."""
        config = {
            "architectures": ["UnknownFutureVLM"],
            "vision_config": {"hidden_size": 1024},
        }
        (tmp_path / "config.json").write_text(json.dumps(config))
        from plugins.mlx_module.core.chat import _detect_vlm_capability
        assert _detect_vlm_capability(str(tmp_path)) is True

    def test_vision_config_empty_dict_ignored(self, tmp_path):
        """Empty vision_config {} does NOT count as VLM."""
        config = {"architectures": ["Qwen2ForCausalLM"], "vision_config": {}}
        (tmp_path / "config.json").write_text(json.dumps(config))
        from plugins.mlx_module.core.chat import _detect_vlm_capability
        assert _detect_vlm_capability(str(tmp_path)) is False

    # ── Tertiary detector: safetensors weight map ──────────────────────────

    def _write_index(self, tmp_path, weight_keys):
        (tmp_path / "model.safetensors.index.json").write_text(
            json.dumps({"weight_map": {k: "model-00001-of-00001.safetensors" for k in weight_keys}})
        )

    def test_weight_map_vision_tower_returns_true(self, tmp_path):
        """Unknown architecture + vision_tower in safetensors → VLM."""
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
        """Real text-only: unknown architecture + no vision keys → False."""
        self._write_config(tmp_path, ["Qwen3NextForCausalLM"])
        self._write_index(tmp_path, [
            "model.layers.0.self_attn.q_proj.weight",
            "model.embed_tokens.weight",
        ])
        from plugins.mlx_module.core.chat import _detect_vlm_capability
        assert _detect_vlm_capability(str(tmp_path)) is False

    def test_malformed_index_falls_through_to_false(self, tmp_path):
        """Corrupted index JSON must not crash the detector."""
        self._write_config(tmp_path, ["Qwen2ForCausalLM"])
        (tmp_path / "model.safetensors.index.json").write_text("{broken json")
        from plugins.mlx_module.core.chat import _detect_vlm_capability
        assert _detect_vlm_capability(str(tmp_path)) is False

    def test_vlm_gemma4_returns_true(self, tmp_path):
        """Gemma4 (image, no video) — real default VLM case for server-nexe."""
        path = self._write_config(tmp_path, ["Gemma4ForConditionalGeneration"])
        from plugins.mlx_module.core.chat import _detect_vlm_capability
        assert _detect_vlm_capability(path) is True


# ── _generate_vlm compatibility with mlx-vlm 0.4.x ──────────────────────────

class TestGenerateVlm04Api:
    """Verifies that the VLM flow is compatible with mlx-vlm >= 0.4:
    - image passed as path (str), not PIL.Image
    - result.text extracted from GenerationResult, not a bare string
    - real metrics (prompt_tokens, generation_tps, peak_memory)
    """

    def _reset_singleton(self):
        from plugins.mlx_module.core.chat import MLXChatNode
        MLXChatNode._model = None
        MLXChatNode._tokenizer = None
        MLXChatNode._config = None
        MLXChatNode._is_vlm = False

    def test_generate_vlm_passes_path_not_pil(self, tmp_path):
        """mlx-vlm 0.4 requires path (str); we do not accept PIL.Image."""
        self._reset_singleton()
        from plugins.mlx_module.core.config import MLXConfig
        from plugins.mlx_module.core.chat import MLXChatNode

        config = MLXConfig(model_path="/fake/vlm_model")
        node = MLXChatNode(config=config)
        # Simulate model already loaded (bypass _get_model)
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

        # Verify that the image argument is str (tempfile path), not PIL
        call = mock_generate.call_args
        image_arg = call.kwargs["image"]
        assert isinstance(image_arg, str)
        assert image_arg.endswith(".img")

        # Verify extraction of .text from GenerationResult
        assert out["text"] == "Veig un gat a la imatge."
        assert out["vlm"] is True

        # Real metrics from mlx-vlm 0.4 (no zeros as before)
        assert out["prompt_tokens"] == 42
        assert out["tokens"] == 7
        assert out["prompt_tps"] == 120.0
        assert out["peak_memory_mb"] == 3400.0

    def test_generate_vlm_handles_legacy_string_result(self, tmp_path):
        """Robustness: if mlx_vlm returned str (old version), it should not crash."""
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
        # Fallback: if it has no .text, str(result)
        assert "response str legacy" in out["text"]


# ── _get_model branching ─────────────────────────────────────────────────────

class TestGetModelBifurcation:

    def _reset_singleton(self):
        from plugins.mlx_module.core.chat import MLXChatNode
        MLXChatNode._model = None
        MLXChatNode._tokenizer = None
        MLXChatNode._config = None
        MLXChatNode._is_vlm = False

    def test_text_model_uses_mlx_lm(self, tmp_path):
        """Text-only model → mlx_lm.load()."""
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
        """VLM model → mlx_vlm.load()."""
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
        mock_torch = MagicMock()
        with patch.dict('sys.modules', {'mlx_vlm': mock_mlx_vlm, 'torch': mock_torch}):
            node._get_model()

        mock_load.assert_called_once_with(str(tmp_path))
        assert MLXChatNode._is_vlm is True


# ── execute() branching ──────────────────────────────────────────────────────

class TestMLXExecuteBifurcation:

    def _reset_singleton(self):
        from plugins.mlx_module.core.chat import MLXChatNode
        MLXChatNode._model = None
        MLXChatNode._tokenizer = None
        MLXChatNode._config = None
        MLXChatNode._is_vlm = False

    @pytest.mark.asyncio
    async def test_text_only_uses_generate_blocking(self):
        """Without images → _generate_blocking (normal path)."""
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

        # Verify that _generate_blocking was called (not _generate_vlm)
        call_args = mock_thread.call_args
        assert call_args[0][0] == node._generate_blocking

    @pytest.mark.asyncio
    async def test_images_with_vlm_uses_generate_vlm(self):
        """With images and VLM active → _generate_vlm.

        execute() uses _detect_vlm_capability(config.model_path) as the
        source of truth (not the _is_vlm singleton — can go stale when
        switching VLM→text models). Mock the detector to True.
        """
        self._reset_singleton()

        from plugins.mlx_module.core.config import MLXConfig
        from plugins.mlx_module.core.chat import MLXChatNode

        config = MLXConfig(model_path="/fake/vlm_model")
        node = MLXChatNode(config=config)
        MLXChatNode._is_vlm = True  # Singleton state (secondary; not used by execute)

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

        with patch("plugins.mlx_module.core.chat._detect_vlm_capability", return_value=True), \
             patch("asyncio.to_thread") as mock_thread:
            mock_thread.return_value = vlm_result
            result = await node.execute({
                "system": "",
                "messages": [{"role": "user", "content": "Descriu la imatge"}],
                "images": [b"\xff\xd8\xff" + b"\x00" * 100],
            })

        # Verify that _generate_vlm was called (not _generate_blocking)
        call_args = mock_thread.call_args
        assert call_args[0][0] == node._generate_vlm
        # The response is valid
        assert result.get("response") == "Veig un gat."


# ── _normalize_image_input ───────────────────────────────────────────────────

class TestNormalizeImageInput:

    def _make_node(self):
        from plugins.mlx_module.core.config import MLXConfig
        from plugins.mlx_module.core.chat import MLXChatNode
        MLXChatNode._model = None
        MLXChatNode._tokenizer = None
        return MLXChatNode(config=MLXConfig(model_path="/fake/model"))

    def test_bytes_passthrough(self):
        node = self._make_node()
        data = b"\xff\xd8\xff\xe0" + b"\x00" * 10
        assert node._normalize_image_input(data) is data

    def test_bytearray_passthrough(self):
        node = self._make_node()
        data = bytearray(b"\xff\xd8\xff\xe0")
        result = node._normalize_image_input(data)
        assert isinstance(result, (bytes, bytearray))

    def test_bare_base64_str_decoded(self):
        import base64
        node = self._make_node()
        raw = b"\xff\xd8\xff\xe0" + b"\x00" * 10
        encoded = base64.b64encode(raw).decode()
        result = node._normalize_image_input(encoded)
        assert result == raw

    def test_data_uri_prefix_stripped_and_decoded(self):
        import base64
        node = self._make_node()
        raw = b"\x89PNG\r\n" + b"\x00" * 20
        encoded = base64.b64encode(raw).decode()
        data_uri = f"data:image/png;base64,{encoded}"
        result = node._normalize_image_input(data_uri)
        assert result == raw

    def test_invalid_base64_str_raises_value_error(self):
        node = self._make_node()
        with pytest.raises(ValueError, match="not valid base64"):
            node._normalize_image_input("!!!not_base64!!!")

    def test_wrong_type_raises_type_error(self):
        node = self._make_node()
        with pytest.raises(TypeError, match="must be bytes or base64 str"):
            node._normalize_image_input(12345)

    def test_data_uri_without_comma_raises_value_error(self):
        """data: prefix without comma → payload cannot be split, decoding fails."""
        import base64
        node = self._make_node()
        raw = b"\x00" * 4
        encoded = base64.b64encode(raw).decode()
        data_uri_no_comma = f"data:image/png;base64{encoded}"
        with pytest.raises(ValueError, match="not valid base64"):
            node._normalize_image_input(data_uri_no_comma)


# ── _extract_vlm_metrics ─────────────────────────────────────────────────────

class TestExtractVlmMetrics:

    def _make_node(self):
        from plugins.mlx_module.core.config import MLXConfig
        from plugins.mlx_module.core.chat import MLXChatNode
        MLXChatNode._model = None
        MLXChatNode._tokenizer = None
        return MLXChatNode(config=MLXConfig(model_path="/fake/model"))

    def _full_result_obj(self):
        obj = MagicMock()
        obj.prompt_tokens = 50
        obj.generation_tokens = 12
        obj.prompt_tps = 200.0
        obj.generation_tps = 55.3
        obj.peak_memory = 4096.0
        return obj

    def test_all_fields_present(self):
        node = self._make_node()
        obj = self._full_result_obj()
        out = node._extract_vlm_metrics(obj, "Hola món", 500)
        assert out["text"] == "Hola món"
        assert out["tokens"] == 12
        assert out["prompt_tokens"] == 50
        assert out["prompt_tps"] == 200.0
        assert out["peak_memory_mb"] == 4096.0
        assert out["tokens_per_second"] == 55.3
        assert out["vlm"] is True
        assert out["prefix_reused"] is False
        assert out["cached_tokens"] == 0
        assert out["actual_prefill_tokens"] == 50
        assert out["identity_hash"] == ""

    def test_missing_generation_tokens_fallback_to_word_count(self):
        node = self._make_node()
        obj = MagicMock(spec=[])
        out = node._extract_vlm_metrics(obj, "un dos tres quatre", 1000)
        assert out["tokens"] == 4

    def test_zero_gen_tps_uses_elapsed_fallback(self):
        node = self._make_node()
        obj = MagicMock()
        obj.prompt_tokens = 10
        obj.generation_tokens = 10
        obj.prompt_tps = 0.0
        obj.generation_tps = 0.0
        obj.peak_memory = 0.0
        out = node._extract_vlm_metrics(obj, "hola món test", 2000)
        assert out["tokens_per_second"] == round(10 / 2.0, 1)

    def test_missing_all_attrs_does_not_crash(self):
        node = self._make_node()
        obj = MagicMock(spec=[])
        out = node._extract_vlm_metrics(obj, "text", 100)
        assert "text" in out
        assert out["vlm"] is True
