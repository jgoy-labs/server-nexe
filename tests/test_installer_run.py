"""
────────────────────────────────────
Server Nexe
Author: Jordi Goy
Location: tests/test_installer_run.py
Description: Tests dels helpers privats extrets de run_installer
             (refactor CCN 42→≤10, façana facade).
────────────────────────────────────
"""
import os
import subprocess
import sys
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from installer.install import (
    _TeeWriter,
    _cleanup_module_cache,
    _confirm_proceed,
    _create_nexe_wrapper,
    _create_storage_folders,
    _download_embeddings,
    _handle_mlx_engine,
    _handle_reinstall_or_clean,
    _ingest_knowledge_if_present,
    _perform_linux_relocation,
    _resolve_skip_model_config,
    _setup_install_log,
    _setup_knowledge_dir,
    _show_download_confirmation,
)


# ── _perform_linux_relocation ─────────────────────────────────────────────────

class TestPerformLinuxRelocation:
    def test_copies_source_to_project(self, tmp_path, monkeypatch):
        source = tmp_path / "source"
        source.mkdir()
        (source / "main.py").write_text("# main")
        (source / "venv").mkdir()

        dest = tmp_path / "dest"
        monkeypatch.setattr(os, "chdir", lambda p: None)
        _perform_linux_relocation(source, dest)

        assert (dest / "main.py").exists()
        assert not (dest / "venv").exists()

    def test_removes_existing_dest(self, tmp_path, monkeypatch):
        # dest has NO install markers (.env/storage/venv) → detect_existing_install
        # is False → the clean-slate rmtree path is taken (unchanged by B148 fix).
        source = tmp_path / "source"
        source.mkdir()
        (source / "file.py").write_text("x")

        dest = tmp_path / "dest"
        dest.mkdir()
        (dest / "old.txt").write_text("old")

        monkeypatch.setattr(os, "chdir", lambda p: None)
        _perform_linux_relocation(source, dest)

        assert not (dest / "old.txt").exists()
        assert (dest / "file.py").exists()

    def test_existing_install_data_is_preserved_during_relocation(self, tmp_path, monkeypatch):
        # B148: re-running the installer from Downloads must NOT wipe an existing
        # install at ~/.local/share/nexe before the reinstall dialog/backup runs.
        source = tmp_path / "source"
        source.mkdir()
        (source / "main.py").write_text("# fresh system file")

        dest = tmp_path / "dest"
        dest.mkdir()
        # prior install: .env is an INSTALL_MARKER → detect_existing_install True
        (dest / ".env").write_text("NEXE_PRIMARY_API_KEY=secret")
        (dest / "storage").mkdir()
        (dest / "storage" / "user.db").write_text("user data")

        monkeypatch.setattr(os, "chdir", lambda p: None)
        _perform_linux_relocation(source, dest)

        # user data survives the relocation (no premature wipe)
        assert (dest / "storage" / "user.db").read_text() == "user data"
        assert (dest / ".env").exists()
        # fresh system files still arrive
        assert (dest / "main.py").exists()

    def test_calls_chdir_with_project_root(self, tmp_path, monkeypatch):
        source = tmp_path / "source"
        source.mkdir()
        dest = tmp_path / "dest"

        chdir_calls = []
        monkeypatch.setattr(os, "chdir", lambda p: chdir_calls.append(Path(p)))
        _perform_linux_relocation(source, dest)

        assert dest in chdir_calls


# ── _setup_install_log ────────────────────────────────────────────────────────

class TestSetupInstallLog:
    def test_creates_log_inside_storage_logs(self, tmp_path):
        tee, log_path = _setup_install_log(tmp_path)
        try:
            assert log_path.parent == tmp_path / "storage" / "logs"
            assert log_path.exists()
        finally:
            tee.close()

    def test_redirects_stdout_to_tee(self, tmp_path):
        original = sys.stdout
        tee, _ = _setup_install_log(tmp_path)
        assert sys.stdout is tee
        tee.close()
        assert sys.stdout is original


# ── _confirm_proceed ──────────────────────────────────────────────────────────

class TestConfirmProceed:
    @pytest.mark.parametrize("answer", ["y", "yes", "s", "si", "sí"])
    def test_returns_true_for_affirmative(self, tmp_path, monkeypatch, answer):
        tee = _TeeWriter(tmp_path / "log.log")
        monkeypatch.setattr("builtins.input", lambda _: answer)
        result = _confirm_proceed(tee)
        tee.close()
        assert result is True

    def test_returns_false_for_no(self, tmp_path, monkeypatch):
        tee = _TeeWriter(tmp_path / "log.log")
        monkeypatch.setattr("builtins.input", lambda _: "n")
        result = _confirm_proceed(tee)
        assert result is False

    def test_false_closes_tee_restoring_stdout(self, tmp_path, monkeypatch):
        tee = _TeeWriter(tmp_path / "log.log")
        original_stdout = sys.stdout
        sys.stdout = tee
        monkeypatch.setattr("builtins.input", lambda _: "abort")
        _confirm_proceed(tee)
        assert sys.stdout is original_stdout


# ── _handle_reinstall_or_clean ────────────────────────────────────────────────

class TestHandleReinstallOrClean:
    def test_no_existing_install_no_venv_returns_true(self, tmp_path, monkeypatch):
        import installer.install as inst
        monkeypatch.setattr(inst, "detect_existing_install", lambda _: False)
        assert _handle_reinstall_or_clean(tmp_path) is True

    def test_no_existing_install_removes_venv(self, tmp_path, monkeypatch):
        import installer.install as inst
        monkeypatch.setattr(inst, "detect_existing_install", lambda _: False)
        venv = tmp_path / "venv"
        venv.mkdir()
        assert _handle_reinstall_or_clean(tmp_path) is True
        assert not venv.exists()

    def test_reinstall_success_returns_true(self, tmp_path, monkeypatch):
        import installer.install as inst
        monkeypatch.setattr(inst, "detect_existing_install", lambda _: True)
        monkeypatch.setattr("builtins.input", lambda _: "3")
        monkeypatch.setattr(
            inst, "apply_reinstall_mode",
            lambda *a, **k: {"backup_dir": None, "removed": []},
        )
        assert _handle_reinstall_or_clean(tmp_path) is True

    def test_reinstall_failure_returns_false(self, tmp_path, monkeypatch):
        import installer.install as inst
        monkeypatch.setattr(inst, "detect_existing_install", lambda _: True)
        monkeypatch.setattr("builtins.input", lambda _: "1")

        def _raise(*a, **k):
            raise RuntimeError("disk full")

        monkeypatch.setattr(inst, "apply_reinstall_mode", _raise)
        assert _handle_reinstall_or_clean(tmp_path) is False


# ── _resolve_skip_model_config ────────────────────────────────────────────────

class TestResolveSkipModelConfig:
    def test_detects_local_ollama_model(self, monkeypatch):
        import urllib.request

        class _FakeResp:
            def read(self):
                return b'{"models": [{"name": "llama3:8b"}]}'
            def __enter__(self): return self
            def __exit__(self, *a): pass

        monkeypatch.setattr(urllib.request, "urlopen", lambda *a, **k: _FakeResp())
        result = _resolve_skip_model_config()
        assert result["id"] == "llama3:8b"
        assert result["engine"] == "ollama"

    def test_falls_back_when_ollama_unavailable(self, monkeypatch):
        import urllib.request

        def _fail(*a, **k):
            raise ConnectionRefusedError()

        monkeypatch.setattr(urllib.request, "urlopen", _fail)
        result = _resolve_skip_model_config()
        assert result["engine"] == "ollama"
        assert result["id"]

    def test_falls_back_when_no_models_in_response(self, monkeypatch):
        import urllib.request

        class _FakeResp:
            def read(self):
                return b'{"models": []}'
            def __enter__(self): return self
            def __exit__(self, *a): pass

        monkeypatch.setattr(urllib.request, "urlopen", lambda *a, **k: _FakeResp())
        result = _resolve_skip_model_config()
        assert result["engine"] == "ollama"
        assert result["id"]


# ── _show_download_confirmation ───────────────────────────────────────────────

class TestShowDownloadConfirmation:
    def test_calls_input_exactly_once(self, monkeypatch):
        count = []
        monkeypatch.setattr("builtins.input", lambda _: count.append(1) or "")
        _show_download_confirmation()
        assert len(count) == 1


# ── _create_storage_folders ───────────────────────────────────────────────────

class TestCreateStorageFolders:
    def test_creates_four_subdirs(self, tmp_path):
        _create_storage_folders(tmp_path)
        for sub in ("cache", "logs", "models", "vectors"):
            assert (tmp_path / "storage" / sub).is_dir()

    def test_idempotent(self, tmp_path):
        _create_storage_folders(tmp_path)
        _create_storage_folders(tmp_path)


# ── _handle_mlx_engine ────────────────────────────────────────────────────────

class TestHandleMlxEngine:
    def _metal_result(self, available: bool):
        r = MagicMock()
        r.stdout = "True\n" if available else "False\n"
        return r

    def test_downloads_mlx_when_metal_available(self, tmp_path, monkeypatch):
        import installer.install as inst

        model_config = {"engine": "mlx", "id": "mlx-community/llama-3.2-3b", "size": "small"}
        download_calls = []
        monkeypatch.setattr(inst, "_download_mlx_model", lambda cfg, r, py: download_calls.append(True))
        monkeypatch.setattr(subprocess, "run", lambda *a, **k: self._metal_result(True))

        _handle_mlx_engine(model_config, tmp_path, Path("/venv/bin/python"))
        assert len(download_calls) == 1

    def test_exits_when_metal_unavailable_and_user_cancels(self, tmp_path, monkeypatch):
        model_config = {"engine": "mlx", "id": "mlx-community/llama-3.2-3b", "size": "small"}
        monkeypatch.setattr(subprocess, "run", lambda *a, **k: self._metal_result(False))
        monkeypatch.setattr("builtins.input", lambda _: "2")

        with pytest.raises(SystemExit):
            _handle_mlx_engine(model_config, tmp_path, Path("/venv/bin/python"))

    def test_switches_to_ollama_when_metal_unavailable_and_user_picks_1(self, tmp_path, monkeypatch):
        import installer.install as inst
        from installer.installer_catalog import MODEL_CATALOG

        mlx_id = ollama_id = None
        for cat in MODEL_CATALOG.values():
            for m in cat:
                if m.get("mlx") and m.get("ollama"):
                    mlx_id, ollama_id = m["mlx"], m["ollama"]
                    break
            if mlx_id:
                break
        if not mlx_id:
            pytest.skip("No hi ha cap model amb mlx i ollama al catàleg")

        model_config = {"engine": "mlx", "id": mlx_id, "size": "small"}
        monkeypatch.setattr(subprocess, "run", lambda *a, **k: self._metal_result(False))
        monkeypatch.setattr("builtins.input", lambda _: "1")

        ensure_calls = []
        download_calls = []
        monkeypatch.setattr(inst, "ensure_ollama_installed", lambda: ensure_calls.append(True))
        monkeypatch.setattr(inst, "_download_ollama_model", lambda cfg: download_calls.append(cfg["id"]))

        _handle_mlx_engine(model_config, tmp_path, Path("/venv/bin/python"))

        assert model_config["engine"] == "ollama"
        assert model_config["id"] == ollama_id
        assert ensure_calls
        assert download_calls == [ollama_id]


# ── _cleanup_module_cache ─────────────────────────────────────────────────────

class TestCleanupModuleCache:
    def test_deletes_cache_when_exists(self, tmp_path):
        cache_dir = tmp_path / "personality"
        cache_dir.mkdir()
        cache_file = cache_dir / ".module_cache.json"
        cache_file.write_text("{}")
        _cleanup_module_cache(tmp_path)
        assert not cache_file.exists()

    def test_noop_when_cache_absent(self, tmp_path):
        _cleanup_module_cache(tmp_path)


# ── _create_nexe_wrapper ──────────────────────────────────────────────────────

class TestCreateNexeWrapper:
    def test_creates_executable_script(self, tmp_path):
        python_path = tmp_path / "venv" / "bin" / "python"
        _create_nexe_wrapper(tmp_path, python_path)
        nexe = tmp_path / "nexe"
        assert nexe.exists()
        assert nexe.stat().st_mode & 0o111
        content = nexe.read_text()
        assert "#!/bin/bash" in content
        assert str(python_path) in content

    def test_script_contains_project_root(self, tmp_path):
        python_path = Path("/some/python")
        _create_nexe_wrapper(tmp_path, python_path)
        content = (tmp_path / "nexe").read_text()
        assert str(tmp_path) in content

    def test_returns_false_symlink_on_permission_error(self, tmp_path, monkeypatch):
        python_path = tmp_path / "python"
        original = Path.symlink_to

        def _fail_symlink(self, target, **kw):
            if str(self) == "/usr/local/bin/nexe":
                raise PermissionError("no write")
            return original(self, target, **kw)

        monkeypatch.setattr(Path, "symlink_to", _fail_symlink)
        _, created = _create_nexe_wrapper(tmp_path, python_path)
        assert created is False


# ── _setup_knowledge_dir ──────────────────────────────────────────────────────

class TestSetupKnowledgeDir:
    def test_creates_and_returns_knowledge_dir(self, tmp_path):
        kd = _setup_knowledge_dir(tmp_path)
        assert kd == tmp_path / "knowledge"
        assert kd.is_dir()

    def test_idempotent_when_dir_exists(self, tmp_path):
        (tmp_path / "knowledge").mkdir()
        kd = _setup_knowledge_dir(tmp_path)
        assert kd.is_dir()


# ── _download_embeddings ──────────────────────────────────────────────────────

class TestDownloadEmbeddings:
    def test_skips_subprocess_when_user_says_no(self, tmp_path, monkeypatch):
        run_calls = []
        monkeypatch.setattr(subprocess, "run", lambda *a, **k: run_calls.append(True))
        monkeypatch.setattr("builtins.input", lambda _: "n")
        _download_embeddings(tmp_path, Path("/venv/bin/python"))
        assert run_calls == []

    def test_calls_subprocess_when_user_says_yes(self, tmp_path, monkeypatch):
        run_calls = []

        def _fake_run(*a, **k):
            run_calls.append(True)

        monkeypatch.setattr(subprocess, "run", _fake_run)
        monkeypatch.setattr("builtins.input", lambda _: "y")
        _download_embeddings(tmp_path, Path("/venv/bin/python"))
        assert len(run_calls) == 1


# ── _ingest_knowledge_if_present ─────────────────────────────────────────────

class TestIngestKnowledgeIfPresent:
    def test_noop_when_no_knowledge_files(self, tmp_path, monkeypatch):
        run_calls = []
        monkeypatch.setattr(subprocess, "run", lambda *a, **k: run_calls.append(True))
        kd = tmp_path / "knowledge"
        kd.mkdir()
        _ingest_knowledge_if_present(tmp_path, Path("/venv/bin/python"), kd, "ca")
        assert run_calls == []

    def test_calls_subprocess_when_md_file_present(self, tmp_path, monkeypatch):
        run_calls = []
        monkeypatch.setattr(subprocess, "run", lambda *a, **k: run_calls.append(True))
        kd = tmp_path / "knowledge"
        kd.mkdir()
        (kd / "doc.md").write_text("# test")
        _ingest_knowledge_if_present(tmp_path, Path("/venv/bin/python"), kd, "ca")
        assert len(run_calls) == 1

    def test_creates_knowledge_ingested_marker(self, tmp_path, monkeypatch):
        monkeypatch.setattr(subprocess, "run", lambda *a, **k: None)
        (tmp_path / "storage").mkdir(parents=True)
        kd = tmp_path / "knowledge"
        kd.mkdir()
        (kd / "doc.md").write_text("# test")
        _ingest_knowledge_if_present(tmp_path, Path("/venv/bin/python"), kd, "ca")
        assert (tmp_path / "storage" / ".knowledge_ingested").exists()
