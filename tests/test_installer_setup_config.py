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
import os
import stat

import pytest
from pathlib import Path

from installer.installer_setup_config import (
    _compute_approved_modules,
    _rewrite_env_lines,
    _append_missing_env_keys,
    _atomic_write_env,
    _update_env_model_config,
    generate_env_file,
)


# ── _compute_approved_modules ─────────────────────────────────────────────


class TestComputeApprovedModules:
    def test_returns_all_backends_for_every_engine(self):
        """B153: every engine must approve ALL backends so the UI Motor dropdown
        can switch engines after a reinstall without re-running the installer
        (mirroring the fresh-install path). Mutation 'gate per engine' → red."""
        for engine in ('ollama', 'mlx', 'llama_cpp', 'unknown'):
            result = _compute_approved_modules(engine)
            assert 'ollama_module' in result, engine
            assert 'mlx_module' in result, engine
            assert 'llama_cpp_module' in result, engine

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

    def test_tmp_file_created_with_0600_mode(self, tmp_path):
        # B147: the .env carries NEXE_PRIMARY_API_KEY + NEXE_CSRF_SECRET; it must
        # never be world-readable, not even in the tmp window. The mode is set at
        # create time (0o600), so the final renamed .env inherits it.
        old_umask = os.umask(0o022)  # permissive umask: a plain open() would yield 0o644
        try:
            env_file = tmp_path / ".env"
            _atomic_write_env(env_file, ["NEXE_PRIMARY_API_KEY=secret\n"])
            mode = stat.S_IMODE(env_file.stat().st_mode)
        finally:
            os.umask(old_umask)
        assert mode == 0o600  # fail-before: open() → 0o644 under umask 0o022


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


# ── generate_env_file: secret tmp file is born 0o600 (INST-004 TOCTOU) ──────


class TestGenerateEnvFileTmpPermissions:
    """The fresh .env is written to a tmp file FIRST, then renamed. The tmp
    file holds NEXE_PRIMARY_API_KEY + NEXE_CSRF_SECRET. If it is created with
    the default umask (0o644) and only chmod'd after the rename, the secrets
    are world-readable during the TOCTOU window. INST-004 fix: the tmp file
    must be created with mode 0o600 from the start (os.open O_CREAT|O_EXCL)."""

    def test_tmp_file_created_with_0600_mode(self, tmp_path, monkeypatch):
        """Spy on os.open: the .env tmp file must be opened with mode 0o600.

        Fails with the old code, which used builtin open() (no mode arg →
        umask-derived 0o644). Passes once os.open(..., 0o600) is used."""
        captured_modes: dict[str, int] = {}
        real_os_open = os.open

        def _spy_open(path, flags, mode=0o777, *args, **kwargs):
            spath = os.fspath(path)
            if ".env.tmp." in spath:
                captured_modes[spath] = mode
            return real_os_open(path, flags, mode, *args, **kwargs)

        monkeypatch.setattr(os, "open", _spy_open)

        generate_env_file(tmp_path)

        assert captured_modes, (
            "the .env tmp file must be created via os.open with an explicit "
            "mode (INST-004): no os.open call for a .env.tmp.* path was seen"
        )
        for spath, mode in captured_modes.items():
            assert mode == 0o600, (
                f"tmp file {spath} opened with mode {oct(mode)}; "
                "secrets must be born 0o600, not exposed via umask"
            )

    def test_final_env_is_0600(self, tmp_path):
        generate_env_file(tmp_path)
        env_file = tmp_path / ".env"
        assert env_file.exists()
        mode = stat.S_IMODE(env_file.stat().st_mode)
        assert mode == 0o600, f"final .env expected 0o600, got {oct(mode)}"

    def test_no_tmp_left_behind(self, tmp_path):
        generate_env_file(tmp_path)
        assert list(tmp_path.glob(".env.tmp.*")) == []


# ── _sha256_check: unexpected verification error fails CLOSED (INST-003) ────
#
# Placed here (rather than test_installer_endpoints.py, which is edited by a
# parallel agent) because both modules cover installer-side security. The unit
# under test is core.endpoints.installer._sha256_check.


class TestSha256CheckFailClosed:
    """A security integrity check must NOT silently skip on an unexpected
    error. Before INST-003, the catch-all `except Exception` logged "skipped"
    and returned None → the caller treated it as success and continued the
    install with an unverified model (fail-open). The fix makes the catch-all
    return an error event (fail-closed)."""

    def _run(self):
        import asyncio
        from core.endpoints import installer as inst_mod
        return asyncio.run(inst_mod._sha256_check("gguf", "repo/model.gguf"))

    def test_unexpected_error_returns_error_event(self, monkeypatch):
        """An unforeseen RuntimeError (not DownloadIntegrityError) inside the
        verification path must yield an error event, aborting the install."""
        import installer.download_verify as dv

        def _boom(*args, **kwargs):
            raise RuntimeError("simulated hashing-chain bug")

        monkeypatch.setattr(dv, "verify_download_integrity", _boom)
        # Avoid touching the real model dir during the gguf branch.
        from core.endpoints import installer as inst_mod
        monkeypatch.setattr(inst_mod, "_resolve_model_path", lambda e, m: "/nonexistent")

        result = self._run()
        assert result is not None, (
            "an unexpected error in the SHA256 check must NOT be swallowed as "
            "skip→None (fail-open); it must return an error event (fail-closed)"
        )
        assert result.get("type") == "error"
        assert result.get("code") == "SHA256_FAIL"

    def test_unpinned_digest_warns_not_errors(self, monkeypatch):
        """Legitimate 'not pinned' (verify returns False) must NOT be a hard
        error (INST-003: fail-closed only fires on UNEXPECTED errors), but it
        must also NOT be silent (INST-002: surface a warning so the GUI shows
        the same ⚠️ the CLI prints). So the unpinned path returns a warning
        event, not None and not an error."""
        import installer.download_verify as dv

        monkeypatch.setattr(dv, "verify_download_integrity", lambda *a, **k: False)
        from core.endpoints import installer as inst_mod
        monkeypatch.setattr(inst_mod, "_resolve_model_path", lambda e, m: "/nonexistent")

        result = self._run()
        assert result is not None, "unpinned digest must surface a warning (INST-002), not be silent"
        assert result.get("type") == "warning", "unpinned must warn, not error (INST-003 intact)"
        assert result.get("code") == "SHA256_NOT_PINNED"
