"""
────────────────────────────────────
Server Nexe
Author: Jordi Goy
Location: tests/test_installer_setup_config.py
Description: Tests for installer_setup_config.py façade helpers — CCN reduction
             refactor. Covers branching principals in:
             _compute_approved_modules, _rewrite_env_lines,
             _append_missing_env_keys, _atomic_write_env,
             _update_env_model_config.

www.jgoy.net · https://server-nexe.org
────────────────────────────────────
"""
import pytest
from pathlib import Path

from installer.installer_setup_config import (
    _compute_approved_modules,
    _rewrite_env_lines,
    _append_missing_env_keys,
    _atomic_write_env,
    _update_env_model_config,
)


# ── _compute_approved_modules ─────────────────────────────────────────────


class TestComputeApprovedModules:
    def test_ollama(self):
        result = _compute_approved_modules('ollama')
        assert 'ollama_module' in result
        assert 'mlx_module' not in result
        assert 'llama_cpp_module' not in result

    def test_mlx(self):
        result = _compute_approved_modules('mlx')
        assert 'mlx_module' in result
        assert 'ollama_module' in result

    def test_llama_cpp(self):
        result = _compute_approved_modules('llama_cpp')
        assert 'llama_cpp_module' in result
        assert 'ollama_module' in result

    def test_unknown_engine_returns_all(self):
        result = _compute_approved_modules('unknown')
        assert 'ollama_module' in result
        assert 'mlx_module' in result
        assert 'llama_cpp_module' in result

    def test_base_modules_always_present(self):
        for engine in ('ollama', 'mlx', 'llama_cpp', 'other'):
            result = _compute_approved_modules(engine)
            assert result.startswith('security,web_ui_module')


# ── _rewrite_env_lines ────────────────────────────────────────────────────


def _ollama_cfg(model_id="llama3:8b"):
    return {'id': model_id, 'engine': 'ollama', 'prompt_tier': 'full', 'chat_format': 'chatml'}


def _mlx_cfg(model_id="org/mlx-model"):
    return {'id': model_id, 'engine': 'mlx', 'prompt_tier': 'full'}


def _llama_cfg(model_id="models/model.gguf"):
    return {'id': model_id, 'engine': 'llama_cpp', 'prompt_tier': 'small', 'chat_format': 'llama-2'}


class TestRewriteEnvLines:
    def test_updates_model_id(self):
        lines = ["NEXE_DEFAULT_MODEL=old-model:7b\n", "NEXE_ENV=production\n"]
        new_lines, found = _rewrite_env_lines(lines, _ollama_cfg("new-model:8b"))
        assert found['model'] is True
        assert any("NEXE_DEFAULT_MODEL=new-model:8b" in l for l in new_lines)

    def test_updates_model_engine(self):
        lines = ["NEXE_MODEL_ENGINE=mlx\n"]
        new_lines, found = _rewrite_env_lines(lines, _ollama_cfg())
        assert found['engine'] is True
        assert any("NEXE_MODEL_ENGINE=ollama" in l for l in new_lines)

    def test_preserves_csrf(self):
        lines = ["NEXE_CSRF_SECRET=abc123\n"]
        new_lines, found = _rewrite_env_lines(lines, _ollama_cfg())
        assert found['csrf'] is True
        assert any("NEXE_CSRF_SECRET=abc123" in l for l in new_lines)

    def test_mlx_model_updated_when_engine_mlx(self):
        lines = ["NEXE_MLX_MODEL=storage/models/old-model\n"]
        new_lines, found = _rewrite_env_lines(lines, _mlx_cfg("org/new-mlx-model"))
        assert found['mlx_model'] is True
        assert any("NEXE_MLX_MODEL=storage/models/new-mlx-model" in l for l in new_lines)

    def test_mlx_model_preserved_when_engine_not_mlx(self):
        lines = ["NEXE_MLX_MODEL=storage/models/old-model\n"]
        new_lines, found = _rewrite_env_lines(lines, _ollama_cfg())
        assert found['mlx_model'] is True
        assert any("storage/models/old-model" in l for l in new_lines)

    def test_llama_cpp_model_updated(self):
        lines = ["NEXE_LLAMA_CPP_MODEL=storage/models/old.gguf\n"]
        new_lines, found = _rewrite_env_lines(lines, _llama_cfg("repo/new.gguf"))
        assert found['llama_cpp_model'] is True
        assert any("storage/models/new.gguf" in l for l in new_lines)

    def test_llama_cpp_chat_format_updated(self):
        lines = ["NEXE_LLAMA_CPP_CHAT_FORMAT=chatml\n"]
        new_lines, found = _rewrite_env_lines(lines, _llama_cfg())
        assert found['llama_cpp_chat_format'] is True
        assert any("llama-2" in l for l in new_lines)

    def test_llama_cpp_chat_format_preserved_for_other_engine(self):
        lines = ["NEXE_LLAMA_CPP_CHAT_FORMAT=chatml\n"]
        new_lines, found = _rewrite_env_lines(lines, _ollama_cfg())
        assert found['llama_cpp_chat_format'] is True
        assert any("chatml" in l for l in new_lines)

    def test_prompt_tier_updated(self):
        lines = ["NEXE_PROMPT_TIER=small\n"]
        new_lines, found = _rewrite_env_lines(lines, _ollama_cfg())
        assert found['prompt_tier'] is True
        assert any("NEXE_PROMPT_TIER=full" in l for l in new_lines)

    def test_approved_modules_updated(self):
        lines = ["NEXE_APPROVED_MODULES=old\n"]
        new_lines, found = _rewrite_env_lines(lines, _ollama_cfg())
        assert found['approved_modules'] is True
        assert any("ollama_module" in l for l in new_lines)

    def test_ollama_model_updated(self):
        lines = ["NEXE_OLLAMA_MODEL=old:7b\n"]
        new_lines, found = _rewrite_env_lines(lines, _ollama_cfg("new:8b"))
        assert found['ollama_model'] is True
        assert any("NEXE_OLLAMA_MODEL=new:8b" in l for l in new_lines)

    def test_ollama_model_preserved_for_other_engine(self):
        lines = ["NEXE_OLLAMA_MODEL=old:7b\n"]
        new_lines, found = _rewrite_env_lines(lines, _mlx_cfg())
        assert found['ollama_model'] is True
        assert any("NEXE_OLLAMA_MODEL=old:7b" in l for l in new_lines)

    def test_unrelated_lines_preserved(self):
        lines = ["NEXE_ENV=production\n", "NEXE_LOG_LEVEL=INFO\n"]
        new_lines, _ = _rewrite_env_lines(lines, _ollama_cfg())
        assert any("NEXE_ENV=production" in l for l in new_lines)
        assert any("NEXE_LOG_LEVEL=INFO" in l for l in new_lines)

    def test_all_found_keys_false_for_empty_env(self):
        new_lines, found = _rewrite_env_lines([], _ollama_cfg())
        assert all(v is False for v in found.values())


# ── _append_missing_env_keys ──────────────────────────────────────────────


class TestAppendMissingEnvKeys:
    def _all_false(self):
        return {k: False for k in (
            'model', 'engine', 'csrf', 'mlx_model', 'llama_cpp_model',
            'llama_cpp_chat_format', 'prompt_tier', 'ollama_model', 'approved_modules',
        )}

    def test_appends_model_when_missing(self):
        new_lines = []
        found = self._all_false()
        _append_missing_env_keys(new_lines, found, _ollama_cfg("test:7b"))
        assert any("NEXE_DEFAULT_MODEL=test:7b" in l for l in new_lines)

    def test_appends_engine_when_missing(self):
        new_lines = []
        found = self._all_false()
        _append_missing_env_keys(new_lines, found, _ollama_cfg())
        assert any("NEXE_MODEL_ENGINE=ollama" in l for l in new_lines)

    def test_appends_csrf_when_missing(self):
        new_lines = []
        found = self._all_false()
        _append_missing_env_keys(new_lines, found, _ollama_cfg())
        assert any("NEXE_CSRF_SECRET=" in l for l in new_lines)

    def test_csrf_not_appended_when_found(self):
        new_lines = []
        found = self._all_false()
        found['csrf'] = True
        _append_missing_env_keys(new_lines, found, _ollama_cfg())
        assert not any("NEXE_CSRF_SECRET=" in l for l in new_lines)

    def test_mlx_model_appended_only_for_mlx_engine(self):
        new_lines = []
        found = self._all_false()
        _append_missing_env_keys(new_lines, found, _mlx_cfg("org/mymodel"))
        assert any("NEXE_MLX_MODEL=storage/models/mymodel" in l for l in new_lines)

    def test_mlx_model_not_appended_for_ollama(self):
        new_lines = []
        found = self._all_false()
        _append_missing_env_keys(new_lines, found, _ollama_cfg())
        assert not any("NEXE_MLX_MODEL=" in l for l in new_lines)

    def test_llama_cpp_keys_appended_only_for_llama_cpp(self):
        new_lines = []
        found = self._all_false()
        _append_missing_env_keys(new_lines, found, _llama_cfg("repo/file.gguf"))
        assert any("NEXE_LLAMA_CPP_MODEL=storage/models/file.gguf" in l for l in new_lines)
        assert any("NEXE_LLAMA_CPP_CHAT_FORMAT=llama-2" in l for l in new_lines)

    def test_ollama_model_appended_only_for_ollama(self):
        new_lines = []
        found = self._all_false()
        _append_missing_env_keys(new_lines, found, _ollama_cfg("mymodel:7b"))
        assert any("NEXE_OLLAMA_MODEL=mymodel:7b" in l for l in new_lines)

    def test_ollama_model_not_appended_for_mlx(self):
        new_lines = []
        found = self._all_false()
        _append_missing_env_keys(new_lines, found, _mlx_cfg())
        assert not any("NEXE_OLLAMA_MODEL=" in l for l in new_lines)

    def test_newline_appended_if_last_line_missing_newline(self):
        new_lines = ["NEXE_ENV=production"]  # no trailing newline
        found = {k: True for k in self._all_false()}  # all found → nothing appended except newline
        _append_missing_env_keys(new_lines, found, _ollama_cfg())
        assert new_lines[0] == "NEXE_ENV=production"
        assert new_lines[1] == "\n"


# ── _atomic_write_env ─────────────────────────────────────────────────────


class TestAtomicWriteEnv:
    def test_writes_content_correctly(self, tmp_path):
        env_file = tmp_path / ".env"
        env_file.write_text("NEXE_ENV=production\n")
        _atomic_write_env(env_file, ["NEXE_ENV=production\n", "NEXE_MODEL_ENGINE=ollama\n"])
        content = env_file.read_text()
        assert "NEXE_MODEL_ENGINE=ollama" in content

    def test_no_tmp_file_left_on_success(self, tmp_path):
        env_file = tmp_path / ".env"
        env_file.write_text("")
        _atomic_write_env(env_file, ["NEXE_ENV=test\n"])
        tmp_files = list(tmp_path.glob(".env.tmp.*"))
        assert tmp_files == []

    def test_fsyncs_before_rename(self, tmp_path, monkeypatch):
        """A power cut between rename and the OS flushing the tmp file
        contents would leave a zero-byte .env. _atomic_write_env must
        fsync before rename.

        Patches ``os.fsync`` on the canonical module object. ``_atomic_write_env``
        does ``import os as _os`` lazily inside the helper, but the binding
        resolves to the same module object — patching ``os.fsync`` is
        visible everywhere ``os`` was imported."""
        import os

        seen_fds: list[int] = []
        real_fsync = os.fsync

        def _spy(fd: int) -> None:
            seen_fds.append(fd)
            real_fsync(fd)

        monkeypatch.setattr(os, "fsync", _spy)
        env_file = tmp_path / ".env"
        env_file.write_text("")
        _atomic_write_env(env_file, ["NEXE_ENV=test\n"])
        assert seen_fds, "_atomic_write_env must fsync the tmp fd before rename"


# ── _update_env_model_config (integration) ────────────────────────────────


class TestUpdateEnvModelConfig:
    def test_none_model_config_is_noop(self, tmp_path):
        env_file = tmp_path / ".env"
        env_file.write_text("NEXE_ENV=production\n")
        _update_env_model_config(env_file, None)
        assert env_file.read_text() == "NEXE_ENV=production\n"

    def test_adds_model_keys_to_minimal_env(self, tmp_path):
        env_file = tmp_path / ".env"
        env_file.write_text("NEXE_ENV=production\n")
        _update_env_model_config(env_file, _ollama_cfg("gemma3:8b"))
        content = env_file.read_text()
        assert "NEXE_DEFAULT_MODEL=gemma3:8b" in content
        assert "NEXE_MODEL_ENGINE=ollama" in content
        assert "NEXE_OLLAMA_MODEL=gemma3:8b" in content

    def test_updates_existing_model_keys(self, tmp_path):
        env_file = tmp_path / ".env"
        env_file.write_text(
            "NEXE_ENV=production\n"
            "NEXE_DEFAULT_MODEL=old:7b\n"
            "NEXE_MODEL_ENGINE=mlx\n"
        )
        _update_env_model_config(env_file, _ollama_cfg("new:8b"))
        content = env_file.read_text()
        assert "NEXE_DEFAULT_MODEL=new:8b" in content
        assert "NEXE_MODEL_ENGINE=ollama" in content
        assert "old:7b" not in content

    def test_mlx_engine_writes_mlx_model_path(self, tmp_path):
        env_file = tmp_path / ".env"
        env_file.write_text("NEXE_ENV=production\n")
        _update_env_model_config(env_file, _mlx_cfg("org/mymlxmodel"))
        content = env_file.read_text()
        assert "NEXE_MLX_MODEL=storage/models/mymlxmodel" in content

    def test_llama_cpp_engine_writes_gguf_path_and_format(self, tmp_path):
        env_file = tmp_path / ".env"
        env_file.write_text("NEXE_ENV=production\n")
        _update_env_model_config(env_file, _llama_cfg("repo/model.gguf"))
        content = env_file.read_text()
        assert "NEXE_LLAMA_CPP_MODEL=storage/models/model.gguf" in content
        assert "NEXE_LLAMA_CPP_CHAT_FORMAT=llama-2" in content

    def test_env_file_is_valid_after_update(self, tmp_path):
        env_file = tmp_path / ".env"
        env_file.write_text(
            "NEXE_PRIMARY_API_KEY=secret\n"
            "NEXE_CSRF_SECRET=csrfsecret\n"
            "NEXE_ENV=production\n"
        )
        _update_env_model_config(env_file, _ollama_cfg("llama3:8b"))
        content = env_file.read_text()
        # CSRF preserved
        assert "NEXE_CSRF_SECRET=csrfsecret" in content
        # API key untouched
        assert "NEXE_PRIMARY_API_KEY=secret" in content
        # Model written
        assert "NEXE_DEFAULT_MODEL=llama3:8b" in content
