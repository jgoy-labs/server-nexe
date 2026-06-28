"""
Tests for multimodal support (images) in llama_cpp_module.
Does not require llama-cpp-python to be installed — everything is mocked.
"""

import importlib.util
import pytest
from unittest.mock import MagicMock, patch


# ── Config ───────────────────────────────────────────────────────────────────

class TestLlamaCppConfigMmproj:

    def test_mmproj_default_empty(self):
        """By default mmproj_path is empty."""
        from plugins.llama_cpp_module.core.config import LlamaCppConfig
        config = LlamaCppConfig(model_path="/fake/model.gguf")
        assert config.mmproj_path == ""

    def test_mmproj_from_env(self, monkeypatch):
        """LLAMA_MMPROJ_PATH is read from the environment."""
        monkeypatch.setenv("LLAMA_MMPROJ_PATH", "/path/to/mmproj.gguf")
        monkeypatch.setenv("NEXE_LLAMA_CPP_MODEL", "/path/to/model.gguf")
        from plugins.llama_cpp_module.core.config import LlamaCppConfig
        config = LlamaCppConfig.from_env()
        assert config.mmproj_path == "/path/to/mmproj.gguf"

    def test_mmproj_not_set_means_empty(self, monkeypatch):
        """Without the env var, mmproj_path is empty."""
        monkeypatch.delenv("LLAMA_MMPROJ_PATH", raising=False)
        monkeypatch.setenv("NEXE_LLAMA_CPP_MODEL", "/path/to/model.gguf")
        from plugins.llama_cpp_module.core.config import LlamaCppConfig
        config = LlamaCppConfig.from_env()
        assert config.mmproj_path == ""


# ── ModelPool — clip_model_path ───────────────────────────────────────────────

class TestModelPoolMmproj:

    def _config(self, mmproj=""):
        from plugins.llama_cpp_module.core.config import LlamaCppConfig
        return LlamaCppConfig(model_path="/fake/model.gguf", mmproj_path=mmproj)

    @pytest.mark.skipif(
        importlib.util.find_spec("llama_cpp") is None,
        reason="llama_cpp not installed"
    )
    def test_create_instance_without_mmproj(self):
        """Without mmproj, Llama() is called without clip_model_path."""
        from plugins.llama_cpp_module.core.model_pool import ModelPool
        config = self._config(mmproj="")
        pool = ModelPool(config)

        # Patch at the source module: model_pool does `from llama_cpp import Llama`
        # lazily inside _create_instance, so the name never lives on model_pool.
        mock_llama_cls = MagicMock(return_value=MagicMock())
        with patch("llama_cpp.Llama", mock_llama_cls):
            pool._create_instance()

        call_kwargs = mock_llama_cls.call_args.kwargs
        assert "clip_model_path" not in call_kwargs

    @pytest.mark.skipif(
        importlib.util.find_spec("llama_cpp") is None,
        reason="llama_cpp not installed"
    )
    def test_create_instance_with_mmproj(self):
        """With mmproj, Llama() receives clip_model_path."""
        from plugins.llama_cpp_module.core.model_pool import ModelPool
        config = self._config(mmproj="/path/mmproj.gguf")
        pool = ModelPool(config)

        mock_llama_cls = MagicMock(return_value=MagicMock())
        with patch("llama_cpp.Llama", mock_llama_cls):
            pool._create_instance()

        call_kwargs = mock_llama_cls.call_args.kwargs
        assert call_kwargs.get("clip_model_path") == "/path/mmproj.gguf"


# ── ChatNode — graceful fallback ──────────────────────────────────────────────

class TestLlamaCppChatNodeImages:

    def _node(self, mmproj=""):
        from plugins.llama_cpp_module.core.config import LlamaCppConfig
        from plugins.llama_cpp_module.core.chat import LlamaCppChatNode
        # Reset singleton for each test
        LlamaCppChatNode._pool = None
        LlamaCppChatNode._config = None
        config = LlamaCppConfig(model_path="/fake/model.gguf", mmproj_path=mmproj)
        return LlamaCppChatNode(config=config)

    @pytest.mark.asyncio
    async def test_image_without_mmproj_logs_warning(self, caplog):
        """Image without mmproj → warning and text-only fallback."""
        import logging

        node = self._node(mmproj="")

        # Mock for the pool and generation
        mock_model = MagicMock()
        mock_result = {
            "choices": [{"message": {"content": "Resposta"}}],
            "usage": {"prompt_tokens": 10, "completion_tokens": 5},
        }
        mock_model.create_chat_completion.return_value = mock_result
        node._get_model = MagicMock(return_value=(mock_model, False))

        gen_result = {
            "text": "Resposta", "tokens": 5, "prompt_tokens": 10,
            "timing": {"prefill_ms": 0, "generation_ms": 100},
        }
        with caplog.at_level(logging.WARNING, logger="llama_cpp_module.core.chat"):
            with patch("plugins.llama_cpp_module.core.chat.compute_system_hash", return_value="hash123"):
                with patch.object(node, "_generate", return_value=gen_result):
                    await node.execute({
                        "system": "Ets un assistent",
                        "messages": [{"role": "user", "content": "Hola"}],
                        "images": [b"fake_image_bytes"],
                    })

        assert any("mmproj" in rec.message.lower() for rec in caplog.records)

    @pytest.mark.asyncio
    async def test_text_only_no_regression(self):
        """Text-only without image: works the same as before."""
        node = self._node(mmproj="")
        mock_model = MagicMock()
        node._get_model = MagicMock(return_value=(mock_model, False))

        gen_result = {
            "text": "Hola!", "tokens": 3, "prompt_tokens": 8,
            "timing": {"prefill_ms": 0, "generation_ms": 50},
        }
        with patch("plugins.llama_cpp_module.core.chat.compute_system_hash", return_value="hash123"):
            with patch.object(node, "_generate", return_value=gen_result):
                result = await node.execute({
                    "system": "Ets un assistent",
                    "messages": [{"role": "user", "content": "Hola"}],
                })

        assert result["response"] == "Hola!"

    @pytest.mark.asyncio
    async def test_vlm_images_passed_to_generate_vlm(self):
        """With images + mmproj, execute() must call _generate_vlm."""
        node = self._node(mmproj="/path/mmproj.gguf")
        mock_model = MagicMock()
        node._get_model = MagicMock(return_value=(mock_model, False))

        vlm_result = {
            "text": "Veig un gat",
            "tokens": 4,
            "prompt_tokens": 20,
            "timing": {"prefill_ms": 50, "generation_ms": 100, "overhead_ms": 0, "prefill_available": False},
        }

        with patch("plugins.llama_cpp_module.core.chat.compute_system_hash", return_value="hash123"), \
             patch.object(node, "_generate_vlm", return_value=vlm_result) as mock_vlm, \
             patch.object(node, "_generate") as mock_text:
            result = await node.execute({
                "system": "Ets un assistent visual",
                "messages": [{"role": "user", "content": "Què veus?"}],
                "images": [b"fake_image_bytes"],
            })

        # Verify _generate_vlm was called (not _generate)
        assert mock_vlm.called
        assert not mock_text.called
        assert result["response"] == "Veig un gat"

    @pytest.mark.asyncio
    async def test_vlm_streaming_images_passed(self):
        """With images + mmproj + stream_callback, execute() must call _generate_vlm_streaming."""
        node = self._node(mmproj="/path/mmproj.gguf")
        mock_model = MagicMock()
        node._get_model = MagicMock(return_value=(mock_model, False))

        vlm_result = {
            "text": "Un paisatge",
            "tokens": 3,
            "prompt_tokens": 15,
            "timing": {"prefill_ms": 40, "generation_ms": 80, "overhead_ms": 0, "prefill_available": True},
        }

        callback = MagicMock()

        with patch("plugins.llama_cpp_module.core.chat.compute_system_hash", return_value="hash123"), \
             patch.object(node, "_generate_vlm_streaming", return_value=vlm_result) as mock_vlm_stream:
            result = await node.execute({
                "system": "Ets un assistent visual",
                "messages": [{"role": "user", "content": "Descriu"}],
                "images": [b"fake_image_bytes"],
                "stream_callback": callback,
            })

        assert mock_vlm_stream.called
        assert result["response"] == "Un paisatge"

    @pytest.mark.asyncio
    async def test_vlm_format_messages_with_image(self):
        """_generate_vlm formats messages with base64 data URIs for llama-cpp-python."""
        node = self._node(mmproj="/path/mmproj.gguf")
        mock_model = MagicMock()

        mock_response = {
            "choices": [{"message": {"content": "Un gat negre"}}],
            "usage": {"prompt_tokens": 30, "completion_tokens": 4},
        }
        mock_model.create_chat_completion.return_value = mock_response

        import base64
        fake_image = b"\x89PNG_fake_image_data"
        result = node._generate_vlm(
            model=mock_model,
            system="Descriu la imatge",
            messages=[{"role": "user", "content": "Què veus?"}],
            images=[fake_image],
        )

        # Verify create_chat_completion was called with image in messages
        call_args = mock_model.create_chat_completion.call_args
        sent_messages = call_args.kwargs.get("messages") or call_args[1].get("messages") or call_args[0][0]
        user_msg = [m for m in sent_messages if m["role"] == "user"][0]

        # Content should be a list (multimodal format)
        assert isinstance(user_msg["content"], list)
        # Should contain image_url type
        image_parts = [p for p in user_msg["content"] if p.get("type") == "image_url"]
        assert len(image_parts) == 1
        # Verify base64 encoding
        expected_b64 = base64.b64encode(fake_image).decode("utf-8")
        assert expected_b64 in image_parts[0]["image_url"]["url"]
        assert result["text"] == "Un gat negre"
