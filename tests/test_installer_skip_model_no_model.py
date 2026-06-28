"""
────────────────────────────────────
Server Nexe
Author: Jordi Goy
Location: tests/test_installer_skip_model_no_model.py
Description: Tests for "Continue without model" (empty model_key).
             Covers the path where the user wants to install without
             downloading any model (model_key="" in the config JSON).
             Verifies that:
             - _update_env_model_config does not crash with model_config=None
             - generate_env_file accepts model_config=None (new .env)
             - run_headless_inner with model_key="" does not crash and reaches Step 4

www.jgoy.net · https://server-nexe.org
────────────────────────────────────
"""


# ── Tests for _update_env_model_config with model_config=None ────────────────

class TestUpdateEnvModelConfigNone:
    """_update_env_model_config must be a no-op when model_config=None."""

    def test_none_model_config_does_not_crash(self, tmp_path):
        """Existing .env + model_config=None -> no crash, .env intact."""
        from installer.installer_setup_config import _update_env_model_config

        env_file = tmp_path / ".env"
        original = "NEXE_PRIMARY_API_KEY=abc123\nNEXE_MODEL_ENGINE=ollama\n"
        env_file.write_text(original)

        # Red gate: used to crash with TypeError: 'NoneType' object is not subscriptable
        _update_env_model_config(env_file, None)

        # .env not modified
        assert env_file.read_text() == original

    def test_none_model_config_preserves_api_key(self, tmp_path):
        """API key is not lost when calling _update_env_model_config(None)."""
        from installer.installer_setup_config import _update_env_model_config

        env_file = tmp_path / ".env"
        env_file.write_text(
            "NEXE_PRIMARY_API_KEY=secret-key-123\n"
            "NEXE_CSRF_SECRET=csrf-abc\n"
            "NEXE_MODEL_ENGINE=ollama\n"
        )

        _update_env_model_config(env_file, None)

        content = env_file.read_text()
        assert "NEXE_PRIMARY_API_KEY=secret-key-123" in content
        assert "NEXE_CSRF_SECRET=csrf-abc" in content


# ── Tests for generate_env_file with model_config=None ───────────────────────

class TestGenerateEnvFileNone:
    """generate_env_file accepts model_config=None (new install without model)."""

    def test_new_env_file_created_without_model(self, tmp_path, capsys):
        """New .env generated when model_config=None (no model selected)."""
        from installer.installer_setup_config import generate_env_file

        generate_env_file(tmp_path, model_config=None)

        env_file = tmp_path / ".env"
        assert env_file.exists(), ".env was not created"
        content = env_file.read_text()
        # API key generated
        assert "NEXE_PRIMARY_API_KEY=" in content
        # Comment instructing to add model manually (B202: text updated to 'nexe model install')
        assert "nexe model install" in content
        # No active (uncommented) line with NEXE_DEFAULT_MODEL=
        active_model_lines = [line for line in content.splitlines() if line.startswith("NEXE_DEFAULT_MODEL=")]
        assert active_model_lines == [], f"There should be no active NEXE_DEFAULT_MODEL: {active_model_lines}"

    def test_existing_env_not_overwritten_with_none(self, tmp_path, capsys):
        """If .env already exists and model_config=None, it is not overwritten."""
        from installer.installer_setup_config import generate_env_file

        env_file = tmp_path / ".env"
        env_file.write_text("NEXE_PRIMARY_API_KEY=keep-this-key\n")

        generate_env_file(tmp_path, model_config=None)

        # Original key preserved
        assert "keep-this-key" in env_file.read_text()


# ── Tests for run_headless_inner with model_key="" ────────────────────────────

class TestRunHeadlessNoModel:
    """run_headless_inner with model_key="" (Continue without model)."""

    def test_empty_model_key_reaches_step4(self, monkeypatch, tmp_path):
        """With model_key='', the installer reaches Step 4 (config) without crashing."""
        import installer.install_headless as ih
        import subprocess

        project_root = tmp_path / "nexe-install"
        project_root.mkdir()

        # Stubs
        monkeypatch.setattr(ih, "detect_existing_install", lambda _: False)
        monkeypatch.setattr(
            ih, "detect_hardware",
            lambda: {"ram_gb": 16, "has_metal": True, "chip_model": "M1", "disk_free_gb": 100},
        )
        monkeypatch.setattr(
            ih, "setup_environment",
            lambda root, hw, engine=None: str(project_root / "venv" / "bin" / "python"),
        )
        (project_root / "venv" / "bin").mkdir(parents=True)
        (project_root / "venv" / "bin" / "python").write_text("#!/bin/bash\n")

        # If anything calls a download -> error (no model_key)
        def _no_download(*a, **k):
            raise AssertionError("No download expected without a selected model")

        monkeypatch.setattr(ih, "_download_ollama_model", _no_download)
        monkeypatch.setattr(ih, "_download_gguf_model", _no_download)
        monkeypatch.setattr(ih, "_download_mlx_model", _no_download)
        monkeypatch.setattr(ih, "ensure_ollama_installed", lambda: True)

        # Capture the call to generate_env_file
        generate_called = []

        def _fake_generate(root, model_cfg):
            generate_called.append(model_cfg)
            env_file = root / ".env"
            env_file.write_text("NEXE_PRIMARY_API_KEY=test-key\n")

        monkeypatch.setattr(ih, "generate_env_file", _fake_generate)
        monkeypatch.setattr(ih, "_write_commands_file", lambda *a, **k: None)
        monkeypatch.setattr(
            subprocess, "run",
            lambda *a, **k: type("R", (), {"returncode": 0, "stdout": "", "stderr": ""})(),
        )

        config = {
            "lang": "ca",
            "path": str(project_root),
            "model_key": "",   # ← "Continue without model"
            "engine": "ollama",
        }

        try:
            ih._run_headless_inner(config)
        except SystemExit:
            pass  # Darwin login items may call sys.exit in test

        # generate_env_file must be called with model_config=None
        assert generate_called, "generate_env_file was not called"
        assert generate_called[0] is None, (
            f"model_config should be None, got: {generate_called[0]}"
        )

    def test_empty_model_key_sets_skip_model(self, monkeypatch, tmp_path):
        """model_key='' activates skip_model_download internally."""
        import installer.install_headless as ih
        import subprocess

        project_root = tmp_path / "nexe-install2"
        project_root.mkdir()

        monkeypatch.setattr(ih, "detect_existing_install", lambda _: False)
        monkeypatch.setattr(
            ih, "detect_hardware",
            lambda: {"ram_gb": 8, "has_metal": False, "chip_model": "Intel", "disk_free_gb": 50},
        )
        monkeypatch.setattr(
            ih, "setup_environment",
            lambda root, hw, engine=None: str(project_root / "venv" / "bin" / "python"),
        )
        (project_root / "venv" / "bin").mkdir(parents=True)
        (project_root / "venv" / "bin" / "python").write_text("#!/bin/bash\n")
        monkeypatch.setattr(ih, "ensure_ollama_installed", lambda: True)

        download_calls = []
        monkeypatch.setattr(ih, "_download_ollama_model", lambda *a, **k: download_calls.append("ollama"))
        monkeypatch.setattr(ih, "_download_gguf_model", lambda *a, **k: download_calls.append("gguf"))
        monkeypatch.setattr(ih, "_download_mlx_model", lambda *a, **k: download_calls.append("mlx"))
        monkeypatch.setattr(ih, "generate_env_file", lambda r, m: (r / ".env").write_text("NEXE_PRIMARY_API_KEY=k\n"))
        monkeypatch.setattr(ih, "_write_commands_file", lambda *a, **k: None)
        monkeypatch.setattr(
            subprocess, "run",
            lambda *a, **k: type("R", (), {"returncode": 0, "stdout": "", "stderr": ""})(),
        )

        config = {
            "lang": "ca",
            "path": str(project_root),
            "model_key": "",
            "engine": "ollama",
        }

        try:
            ih._run_headless_inner(config)
        except SystemExit:
            pass

        assert download_calls == [], (
            f"No download expected with model_key='', but these were called: {download_calls}"
        )
