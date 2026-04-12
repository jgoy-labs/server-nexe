"""
Tests suport multimodal (imatges) a llama_cpp_module.
No requereix llama-cpp-python instal·lat — tot és mockejat.
"""

import os
import pytest
from unittest.mock import MagicMock, patch
from dataclasses import dataclass


# ── Config ───────────────────────────────────────────────────────────────────

class TestLlamaCppConfigMmproj:

    def test_mmproj_default_empty(self):
        """Per defecte mmproj_path és buit."""
        from plugins.llama_cpp_module.core.config import LlamaCppConfig
        config = LlamaCppConfig(model_path="/fake/model.gguf")
        assert config.mmproj_path == ""

    def test_mmproj_from_env(self, monkeypatch):
        """LLAMA_MMPROJ_PATH es llegeix de l'entorn."""
        monkeypatch.setenv("LLAMA_MMPROJ_PATH", "/path/to/mmproj.gguf")
        monkeypatch.setenv("NEXE_LLAMA_CPP_MODEL", "/path/to/model.gguf")
        from plugins.llama_cpp_module.core.config import LlamaCppConfig
        config = LlamaCppConfig.from_env()
        assert config.mmproj_path == "/path/to/mmproj.gguf"

    def test_mmproj_not_set_means_empty(self, monkeypatch):
        """Sense env var, mmproj_path és buit."""
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

    def test_create_instance_without_mmproj(self):
        """Sense mmproj, Llama() es crida sense clip_model_path."""
        from plugins.llama_cpp_module.core.model_pool import ModelPool
        config = self._config(mmproj="")
        pool = ModelPool(config)

        mock_llama_cls = MagicMock(return_value=MagicMock())
        with patch("llama_cpp.Llama", mock_llama_cls):
            pool._create_instance()

        call_kwargs = mock_llama_cls.call_args.kwargs
        assert "clip_model_path" not in call_kwargs

    def test_create_instance_with_mmproj(self):
        """Amb mmproj, Llama() rep clip_model_path."""
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
        # Reset singleton per cada test
        LlamaCppChatNode._pool = None
        LlamaCppChatNode._config = None
        config = LlamaCppConfig(model_path="/fake/model.gguf", mmproj_path=mmproj)
        return LlamaCppChatNode(config=config)

    @pytest.mark.asyncio
    async def test_image_without_mmproj_logs_warning(self, caplog):
        """Imatge sense mmproj → warning i fallback text-only."""
        import logging
        from plugins.llama_cpp_module.core.chat import LlamaCppChatNode

        node = self._node(mmproj="")

        # Mock del pool i la generació
        mock_model = MagicMock()
        mock_result = {
            "choices": [{"message": {"content": "Resposta"}}],
            "usage": {"prompt_tokens": 10, "completion_tokens": 5},
        }
        mock_model.create_chat_completion.return_value = mock_result
        node._get_model = MagicMock(return_value=(mock_model, False))

        with caplog.at_level(logging.WARNING, logger="llama_cpp_module.core.chat"):
            with patch("plugins.llama_cpp_module.core.chat.compute_system_hash", return_value="hash123"):
                with patch("asyncio.to_thread") as mock_thread:
                    mock_thread.return_value = {
                        "text": "Resposta",
                        "tokens": 5,
                        "prompt_tokens": 10,
                        "prefill_ms": 0,
                        "generation_ms": 100,
                        "finish_reason": "stop",
                    }
                    await node.execute({
                        "system": "Ets un assistent",
                        "messages": [{"role": "user", "content": "Hola"}],
                        "images": [b"fake_image_bytes"],
                    })

        assert any("mmproj" in rec.message.lower() for rec in caplog.records)

    @pytest.mark.asyncio
    async def test_text_only_no_regression(self):
        """Text-only sense imatge: funciona igual que abans."""
        node = self._node(mmproj="")
        mock_model = MagicMock()
        node._get_model = MagicMock(return_value=(mock_model, False))

        with patch("plugins.llama_cpp_module.core.chat.compute_system_hash", return_value="hash123"):
            with patch("asyncio.to_thread") as mock_thread:
                mock_thread.return_value = {
                    "text": "Hola!",
                    "tokens": 3,
                    "prompt_tokens": 8,
                    "prefill_ms": 0,
                    "generation_ms": 50,
                    "finish_reason": "stop",
                }
                result = await node.execute({
                    "system": "Ets un assistent",
                    "messages": [{"role": "user", "content": "Hola"}],
                })

        assert result["response"] == "Hola!"
