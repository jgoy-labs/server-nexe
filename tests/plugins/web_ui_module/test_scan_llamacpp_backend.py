"""
────────────────────────────────────
Server Nexe
Author: Jordi Goy
Location: tests/plugins/web_ui_module/test_scan_llamacpp_backend.py
Description: Regression guards for _scan_llamacpp_backend, fixed on
             2026-05-13 after the live UI dropdown stopped showing the
             Llama.cpp engine when the user removed a stale .gguf
             symlink from storage/models/. The engine itself was still
             working (NEXE_LLAMA_CPP_MODEL env var pointed at a real
             .gguf file), but the UI scanner only looked at the models
             dir and so reported "no llama_cpp backend".

  Contract (any-of, deduplicated by resolved real path):

    1. NEXE_LLAMA_CPP_MODEL points at an existing .gguf → that file
       MUST appear in the model list (the engine WILL load it).
    2. storage/models/*.gguf → curated additions appear too.
    3. A symlink in storage/models/ that resolves to the same file as
       NEXE_LLAMA_CPP_MODEL must NOT be listed twice.
    4. If the llama_cpp_module is not loaded, return None (no UI entry
       even if .gguf files exist on disk — there's no engine to serve).

www.jgoy.net · https://server-nexe.org
────────────────────────────────────
"""

from pathlib import Path
from unittest.mock import MagicMock

import pytest

from plugins.web_ui_module.api.routes_auth import _scan_llamacpp_backend


def _module_manager_with_llama_cpp():
    """Build a stub module_manager whose registry exposes llama_cpp_module."""
    instance = MagicMock()
    reg_entry = MagicMock(instance=instance)
    mm = MagicMock()
    mm.registry.get_module = MagicMock(return_value=reg_entry)
    return mm


def _module_manager_without_llama_cpp():
    mm = MagicMock()
    mm.registry.get_module = MagicMock(return_value=None)
    return mm


class TestModulePresence:
    def test_returns_none_when_llama_cpp_module_absent(self, tmp_path, monkeypatch):
        """Hard precondition: no engine loaded → no UI entry, even with
        .gguf files on disk."""
        monkeypatch.delenv("NEXE_LLAMA_CPP_MODEL", raising=False)
        (tmp_path / "any.gguf").write_bytes(b"\x00")
        result = _scan_llamacpp_backend(_module_manager_without_llama_cpp(), tmp_path)
        assert result is None


class TestEnvVarSource:
    """Source 1 of the contract: NEXE_LLAMA_CPP_MODEL alone is enough."""

    def test_env_var_pointing_at_real_gguf_is_listed(self, tmp_path, monkeypatch):
        """Bug fix: a .gguf at any path on disk reachable via env var
        must appear, even if storage/models/ is empty (no symlink)."""
        gguf = tmp_path / "Qwen_Qwen3-30B-A3B-Q4_K_M.gguf"
        gguf.write_bytes(b"\x00" * 1024)
        monkeypatch.setenv("NEXE_LLAMA_CPP_MODEL", str(gguf))

        empty_models_dir = tmp_path / "models"
        empty_models_dir.mkdir()

        result = _scan_llamacpp_backend(_module_manager_with_llama_cpp(), empty_models_dir)
        assert result is not None
        assert result["id"] == "llamacpp"
        assert any(m["name"] == gguf.name for m in result["models"])

    def test_env_var_pointing_at_nonexistent_path_is_ignored(self, tmp_path, monkeypatch):
        """If the env var lies, fall back to scanning storage/models/
        instead of crashing or falsely advertising the model."""
        monkeypatch.setenv("NEXE_LLAMA_CPP_MODEL", "/nonexistent/ghost.gguf")
        empty_models_dir = tmp_path / "models"
        empty_models_dir.mkdir()
        result = _scan_llamacpp_backend(_module_manager_with_llama_cpp(), empty_models_dir)
        assert result is None

    def test_env_var_pointing_at_non_gguf_is_ignored(self, tmp_path, monkeypatch):
        """Misconfigured env var (points at a .bin / .safetensors etc.)
        must not pollute the dropdown with a non-gguf entry."""
        wrong = tmp_path / "model.safetensors"
        wrong.write_bytes(b"\x00")
        monkeypatch.setenv("NEXE_LLAMA_CPP_MODEL", str(wrong))
        empty_models_dir = tmp_path / "models"
        empty_models_dir.mkdir()
        result = _scan_llamacpp_backend(_module_manager_with_llama_cpp(), empty_models_dir)
        assert result is None


class TestModelsDirSource:
    """Source 2 of the contract: storage/models/*.gguf curated additions."""

    def test_storage_models_gguf_is_listed(self, tmp_path, monkeypatch):
        monkeypatch.delenv("NEXE_LLAMA_CPP_MODEL", raising=False)
        gguf = tmp_path / "extra-model.gguf"
        gguf.write_bytes(b"\x00")
        result = _scan_llamacpp_backend(_module_manager_with_llama_cpp(), tmp_path)
        assert result is not None
        assert any(m["name"] == "extra-model.gguf" for m in result["models"])

    def test_non_gguf_in_models_dir_is_ignored(self, tmp_path, monkeypatch):
        monkeypatch.delenv("NEXE_LLAMA_CPP_MODEL", raising=False)
        (tmp_path / "config.json").write_text("{}")
        (tmp_path / "model.safetensors").write_bytes(b"\x00")
        result = _scan_llamacpp_backend(_module_manager_with_llama_cpp(), tmp_path)
        assert result is None


class TestDeduplication:
    """A symlink in storage/models/ pointing at the env-var target must
    not produce two entries — the engine sees only one model regardless
    of how many filesystem paths reach it."""

    def test_symlink_to_env_var_target_is_deduplicated(self, tmp_path, monkeypatch):
        real = tmp_path / "real.gguf"
        real.write_bytes(b"\x00")
        models_dir = tmp_path / "models"
        models_dir.mkdir()
        symlink = models_dir / "real.gguf"
        symlink.symlink_to(real)

        monkeypatch.setenv("NEXE_LLAMA_CPP_MODEL", str(real))

        result = _scan_llamacpp_backend(_module_manager_with_llama_cpp(), models_dir)
        assert result is not None
        assert len(result["models"]) == 1, (
            f"Expected dedup but got {[m['name'] for m in result['models']]}"
        )


class TestEmptyEnvVar:
    def test_empty_env_var_treated_as_unset(self, tmp_path, monkeypatch):
        monkeypatch.setenv("NEXE_LLAMA_CPP_MODEL", "")
        empty_models_dir = tmp_path / "models"
        empty_models_dir.mkdir()
        result = _scan_llamacpp_backend(_module_manager_with_llama_cpp(), empty_models_dir)
        assert result is None
