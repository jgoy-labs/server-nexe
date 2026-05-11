"""
Tests for plugins/llama_cpp_module/config.py - targeting uncovered lines.
Lines: 63 (tilde expansion), 114-115 (validate empty path),
       125-126 (n_ctx < 512), 129-130 (max_sessions < 1), 134 (unknown chat_format).
"""

import pytest
from unittest.mock import patch
import os


class TestLlamaCppConfigPostInit:

    def test_tilde_expansion(self):
        """Line 63: expand ~ to home directory."""
        from plugins.llama_cpp_module.core.config import LlamaCppConfig
        config = LlamaCppConfig(model_path="~/models/test.gguf")
        assert not config.model_path.startswith("~")
        assert os.path.expanduser("~") in config.model_path

    def test_relative_path_resolution(self):
        """Lines 65-68: relative path resolved to project root."""
        from plugins.llama_cpp_module.core.config import LlamaCppConfig
        config = LlamaCppConfig(model_path="models/test.gguf")
        assert os.path.isabs(config.model_path)

    def test_absolute_path_unchanged(self):
        """Absolute path stays unchanged."""
        from plugins.llama_cpp_module.core.config import LlamaCppConfig
        config = LlamaCppConfig(model_path="/absolute/path/model.gguf")
        assert config.model_path == "/absolute/path/model.gguf"


class TestLlamaCppConfigValidate:

    def test_validate_empty_path(self):
        """Lines 113-115: empty model_path returns False."""
        from plugins.llama_cpp_module.core.config import LlamaCppConfig
        config = LlamaCppConfig.__new__(LlamaCppConfig)
        config.model_path = ""
        config.n_ctx = 8192
        config.n_batch = 512
        config.n_gpu_layers = -1
        config.n_threads = 8
        config.max_sessions = 1
        config.chat_format = "chatml"
        config.use_mlock = True
        config.use_mmap = True
        config.flash_attn = True
        assert config.validate() is False

    def test_validate_nonexistent_path(self, tmp_path):
        """Lines 117-122: path doesn't exist returns False."""
        from plugins.llama_cpp_module.core.config import LlamaCppConfig
        config = LlamaCppConfig(model_path=str(tmp_path / "nonexistent.gguf"))
        assert config.validate() is False

    def test_validate_n_ctx_too_small(self, tmp_path):
        """Lines 124-126: n_ctx < 512 returns False."""
        from plugins.llama_cpp_module.core.config import LlamaCppConfig
        model_file = tmp_path / "model.gguf"
        model_file.write_text("data")
        config = LlamaCppConfig(model_path=str(model_file), n_ctx=256)
        assert config.validate() is False

    def test_validate_max_sessions_zero(self, tmp_path):
        """Lines 128-130: max_sessions < 1 returns False."""
        from plugins.llama_cpp_module.core.config import LlamaCppConfig
        model_file = tmp_path / "model.gguf"
        model_file.write_text("data")
        config = LlamaCppConfig(model_path=str(model_file), max_sessions=0)
        assert config.validate() is False

    def test_validate_unknown_chat_format_warning(self, tmp_path):
        """Lines 132-139: unknown chat_format logs warning but returns True."""
        from plugins.llama_cpp_module.core.config import LlamaCppConfig
        model_file = tmp_path / "model.gguf"
        model_file.write_text("data")
        config = LlamaCppConfig(model_path=str(model_file), chat_format="unknown_format")
        # Warning, not error - should still return True
        assert config.validate() is True

    def test_validate_valid_config(self, tmp_path):
        """Valid config returns True."""
        from plugins.llama_cpp_module.core.config import LlamaCppConfig
        model_file = tmp_path / "model.gguf"
        model_file.write_text("data")
        config = LlamaCppConfig(model_path=str(model_file))
        assert config.validate() is True


class TestLlamaCppConfigFromEnv:

    def test_from_env_reads_all_vars(self, monkeypatch):
        """Lines 78-89: from_env reads all env vars."""
        from plugins.llama_cpp_module.core.config import LlamaCppConfig

        monkeypatch.setenv("NEXE_LLAMA_CPP_MODEL", "/path/to/model.gguf")
        monkeypatch.setenv("NEXE_LLAMA_CPP_N_CTX", "16384")
        monkeypatch.setenv("NEXE_LLAMA_CPP_N_BATCH", "1024")
        monkeypatch.setenv("NEXE_LLAMA_CPP_GPU_LAYERS", "32")
        monkeypatch.setenv("NEXE_LLAMA_CPP_THREADS", "16")
        monkeypatch.setenv("NEXE_LLAMA_CPP_MAX_SESSIONS", "4")
        monkeypatch.setenv("NEXE_LLAMA_CPP_CHAT_FORMAT", "llama-3")
        monkeypatch.setenv("NEXE_LLAMA_CPP_USE_MLOCK", "false")
        monkeypatch.setenv("NEXE_LLAMA_CPP_USE_MMAP", "false")
        monkeypatch.setenv("NEXE_LLAMA_CPP_FLASH_ATTN", "false")

        config = LlamaCppConfig.from_env()
        assert config.model_path == "/path/to/model.gguf"
        assert config.n_ctx == 16384
        assert config.n_batch == 1024
        assert config.n_gpu_layers == 32
        assert config.n_threads == 16
        assert config.max_sessions == 4
        assert config.chat_format == "llama-3"
        assert config.use_mlock is False
        assert config.use_mmap is False
        assert config.flash_attn is False
