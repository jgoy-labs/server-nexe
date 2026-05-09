"""
────────────────────────────────────
Server Nexe
Author: Jordi Goy
Location: tests/test_install_headless.py
Description: Tests for _run_headless_inner façade helpers — CCN reduction
             refactor. Covers branching principals in:
             _parse_headless_config, _apply_reinstall_if_needed,
             _resolve_model_config, _run_model_download.

www.jgoy.net · https://server-nexe.org
────────────────────────────────────
"""
from pathlib import Path

import pytest

import installer.install_headless as ih
from installer.installer_reinstall import DEFAULT_REINSTALL_MODE, VALID_REINSTALL_MODES


# ── _parse_headless_config ─────────────────────────────────────────────────


class TestParseHeadlessConfig:
    def test_defaults(self, tmp_path):
        lang, project_root, model_key, engine, skip_model, reinstall = ih._parse_headless_config(
            {"path": str(tmp_path)}
        )
        assert lang == "ca"
        assert engine == "ollama"
        assert skip_model is False
        assert reinstall == DEFAULT_REINSTALL_MODE
        assert model_key is None

    def test_valid_reinstall_preserved(self, tmp_path):
        for mode in VALID_REINSTALL_MODES:
            _, _, _, _, _, reinstall = ih._parse_headless_config(
                {"path": str(tmp_path), "reinstall_mode": mode}
            )
            assert reinstall == mode

    def test_invalid_reinstall_falls_back_to_default(self, tmp_path):
        _, _, _, _, _, reinstall = ih._parse_headless_config(
            {"path": str(tmp_path), "reinstall_mode": "bogus_mode"}
        )
        assert reinstall == DEFAULT_REINSTALL_MODE

    def test_skip_model_download_parsed(self, tmp_path):
        _, _, _, _, skip_model, _ = ih._parse_headless_config(
            {"path": str(tmp_path), "skip_model_download": True}
        )
        assert skip_model is True

    def test_all_fields_parsed(self, tmp_path):
        lang, project_root, model_key, engine, skip_model, reinstall = ih._parse_headless_config(
            {
                "path": str(tmp_path),
                "lang": "es",
                "model_key": "gemma3_4b",
                "engine": "mlx",
                "skip_model_download": True,
                "reinstall_mode": "wipe",
            }
        )
        assert lang == "es"
        assert engine == "mlx"
        assert model_key == "gemma3_4b"
        assert skip_model is True
        assert reinstall == "wipe"


# ── _apply_reinstall_if_needed ────────────────────────────────────────────


class TestApplyReinstallIfNeeded:
    def test_missing_project_root_is_noop(self, tmp_path):
        missing = tmp_path / "does_not_exist"
        ih._apply_reinstall_if_needed(missing, DEFAULT_REINSTALL_MODE)

    def test_no_existing_install_is_noop(self, tmp_path, monkeypatch):
        monkeypatch.setattr(ih, "detect_existing_install", lambda _: False)
        called = []
        monkeypatch.setattr(ih, "apply_reinstall_mode", lambda *a, **k: called.append(True) or {})
        ih._apply_reinstall_if_needed(tmp_path, DEFAULT_REINSTALL_MODE)
        assert called == []

    def test_existing_install_applies_mode(self, tmp_path, monkeypatch, capsys):
        monkeypatch.setattr(ih, "detect_existing_install", lambda _: True)
        monkeypatch.setattr(ih, "apply_reinstall_mode", lambda root, mode: {
            "mode": mode, "removed": [], "backup_dir": None,
        })
        ih._apply_reinstall_if_needed(tmp_path, "overwrite")
        out = capsys.readouterr().out
        assert "[REINSTALL] mode=overwrite" in out

    def test_existing_install_backup_dir_printed(self, tmp_path, monkeypatch, capsys):
        monkeypatch.setattr(ih, "detect_existing_install", lambda _: True)
        monkeypatch.setattr(ih, "apply_reinstall_mode", lambda root, mode: {
            "mode": mode, "removed": [], "backup_dir": "/tmp/nexe-backup",  # nosemgrep
        })
        ih._apply_reinstall_if_needed(tmp_path, "backup")
        out = capsys.readouterr().out
        assert "[BACKUP] /tmp/nexe-backup" in out
        assert "[REINSTALL] mode=backup" in out

    def test_apply_reinstall_failure_exits(self, tmp_path, monkeypatch):
        monkeypatch.setattr(ih, "detect_existing_install", lambda _: True)

        def _fail(*a, **k):
            raise RuntimeError("disk full")

        monkeypatch.setattr(ih, "apply_reinstall_mode", _fail)
        with pytest.raises(SystemExit):
            ih._apply_reinstall_if_needed(tmp_path, DEFAULT_REINSTALL_MODE)

    def test_apply_reinstall_failure_prints_error(self, tmp_path, monkeypatch, capsys):
        monkeypatch.setattr(ih, "detect_existing_install", lambda _: True)

        def _fail(*a, **k):
            raise RuntimeError("disk full")

        monkeypatch.setattr(ih, "apply_reinstall_mode", _fail)
        with pytest.raises(SystemExit):
            ih._apply_reinstall_if_needed(tmp_path, DEFAULT_REINSTALL_MODE)
        out = capsys.readouterr().out
        assert "[ERROR]" in out


# ── _resolve_model_config ─────────────────────────────────────────────────


class TestResolveModelConfig:
    def test_no_model_key_returns_none_and_forces_skip(self):
        model_config, engine, skip, selected = ih._resolve_model_config(None, "ollama", False)
        assert model_config is None
        assert skip is True
        assert selected is None

    def test_no_model_key_preserves_engine(self):
        _, engine, _, _ = ih._resolve_model_config(None, "mlx", False)
        assert engine == "mlx"

    def test_model_key_not_found_exits(self, capsys):
        with pytest.raises(SystemExit):
            ih._resolve_model_config("nonexistent_model_xyz_404", "ollama", False)
        out = capsys.readouterr().out
        assert "[ERROR]" in out
        assert "Model not found" in out

    def test_valid_model_key_returns_complete_config(self):
        from installer.installer_catalog_data import MODEL_CATALOG

        sample_key = None
        for cat in MODEL_CATALOG.values():
            for m in cat:
                if m.get("ollama"):
                    sample_key = m["key"]
                    break
            if sample_key:
                break
        assert sample_key, "Catalog is empty"

        model_config, engine, skip, selected = ih._resolve_model_config(sample_key, "ollama", False)
        assert model_config is not None
        assert "engine" in model_config
        assert "id" in model_config
        assert "name" in model_config
        assert "size" in model_config
        assert "ram" in model_config
        assert selected is not None

    def test_skip_model_download_preserved_when_model_found(self):
        from installer.installer_catalog_data import MODEL_CATALOG

        sample_key = None
        for cat in MODEL_CATALOG.values():
            for m in cat:
                if m.get("ollama"):
                    sample_key = m["key"]
                    break
            if sample_key:
                break
        assert sample_key

        _, _, skip, _ = ih._resolve_model_config(sample_key, "ollama", True)
        assert skip is True

    def test_engine_fallback_when_requested_engine_unavailable(self):
        from installer.installer_catalog_data import MODEL_CATALOG

        # Find a model that has ollama but whose gguf field is absent
        sample_key = None
        for cat in MODEL_CATALOG.values():
            for m in cat:
                if m.get("ollama") and not m.get("gguf"):
                    sample_key = m["key"]
                    break
            if sample_key:
                break

        if not sample_key:
            pytest.skip("No model with ollama but without gguf in catalog")

        model_config, engine, _, _ = ih._resolve_model_config(sample_key, "llama_cpp", False)
        assert engine != "llama_cpp"
        assert model_config["engine"] != "llama_cpp"


# ── _run_model_download ───────────────────────────────────────────────────


class TestRunModelDownload:
    _FAKE_ROOT = Path("/tmp/nexe-test")  # nosemgrep
    _FAKE_PYTHON = Path("/tmp/nexe-test/venv/bin/python")  # nosemgrep

    def _model_config(self, engine="ollama"):
        return {
            "engine": engine,
            "id": "test-model:7b",
            "name": "Test Model",
            "size": "medium",
            "disk_size": "~5 GB",
            "ram": 8,
            "prompt_tier": "full",
            "chat_format": "chatml",
        }

    def test_skip_model_download_true_returns_ok(self, monkeypatch, capsys):
        monkeypatch.setattr(ih, "_download_ollama_model", lambda *a, **k: (_ for _ in ()).throw(AssertionError("must not download")))
        model_ok, cfg = ih._run_model_download(
            self._model_config(), "ollama", True, "key", None, {},
            self._FAKE_ROOT, self._FAKE_PYTHON,
        )
        assert model_ok is True
        assert "[MODEL_SKIPPED]" in capsys.readouterr().out

    def test_model_config_none_skips_without_download(self, capsys):
        model_ok, cfg = ih._run_model_download(
            None, "ollama", False, None, None, {},
            self._FAKE_ROOT, self._FAKE_PYTHON,
        )
        assert model_ok is True
        assert cfg is None
        assert "[MODEL_SKIPPED]" in capsys.readouterr().out

    def test_ollama_install_failure_returns_false(self, monkeypatch, capsys):
        monkeypatch.setattr(ih, "ensure_ollama_installed", lambda **k: False)
        model_ok, _ = ih._run_model_download(
            self._model_config("ollama"), "ollama", False, "key", None, {},
            self._FAKE_ROOT, self._FAKE_PYTHON,
        )
        assert model_ok is False

    def test_ollama_download_success_returns_true(self, monkeypatch, capsys):
        monkeypatch.setattr(ih, "ensure_ollama_installed", lambda **k: True)
        monkeypatch.setattr(ih, "_download_ollama_model", lambda *a, **k: None)
        model_ok, cfg = ih._run_model_download(
            self._model_config("ollama"), "ollama", False, "key", None, {},
            self._FAKE_ROOT, self._FAKE_PYTHON,
        )
        assert model_ok is True

    def test_mlx_no_metal_falls_back_to_ollama(self, monkeypatch, capsys):
        monkeypatch.setattr(ih, "ensure_ollama_installed", lambda **k: True)
        monkeypatch.setattr(ih, "_download_ollama_model", lambda *a, **k: None)
        selected_model = {"ollama": "test-model:7b", "key": "test", "name": "Test"}
        hw = {"has_metal": False}
        model_ok, updated_cfg = ih._run_model_download(
            self._model_config("mlx"), "mlx", False, "test", selected_model,
            hw, self._FAKE_ROOT, self._FAKE_PYTHON,
        )
        assert model_ok is True
        assert updated_cfg["engine"] == "ollama"

    def test_mlx_no_metal_no_ollama_fallback_returns_false(self, monkeypatch, capsys):
        monkeypatch.setattr(ih, "ensure_ollama_installed", lambda **k: True)
        selected_model = {"key": "test", "name": "Test"}  # no "ollama" key
        hw = {"has_metal": False}
        model_ok, _ = ih._run_model_download(
            self._model_config("mlx"), "mlx", False, "test", selected_model,
            hw, self._FAKE_ROOT, self._FAKE_PYTHON,
        )
        assert model_ok is False

    def test_download_exception_returns_false(self, monkeypatch, capsys):
        monkeypatch.setattr(ih, "ensure_ollama_installed", lambda **k: True)

        def _boom(*a, **k):
            raise RuntimeError("network timeout")

        monkeypatch.setattr(ih, "_download_ollama_model", _boom)
        model_ok, _ = ih._run_model_download(
            self._model_config("ollama"), "ollama", False, "key", None, {},
            self._FAKE_ROOT, self._FAKE_PYTHON,
        )
        assert model_ok is False
        out = capsys.readouterr().out
        assert "[ERROR]" in out
