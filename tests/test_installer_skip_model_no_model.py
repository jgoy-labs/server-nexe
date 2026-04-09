"""
────────────────────────────────────
Server Nexe
Author: Jordi Goy
Location: tests/test_installer_skip_model_no_model.py
Description: Tests per "Continuar sense model" (model_key buida).
             Cobreix el path en que l'usuari vol instal·lar sense
             descarregar cap model (model_key="" al JSON de config).
             Verifica que:
             - _update_env_model_config no peta amb model_config=None
             - generate_env_file accepta model_config=None (nou .env)
             - run_headless_inner amb model_key="" no peta i arriba al Step 4

www.jgoy.net · https://server-nexe.org
────────────────────────────────────
"""


# ── Tests _update_env_model_config amb model_config=None ─────────────────────

class TestUpdateEnvModelConfigNone:
    """_update_env_model_config ha de ser no-op quan model_config=None."""

    def test_none_model_config_does_not_crash(self, tmp_path):
        """.env existent + model_config=None -> no crash, .env intacte."""
        from installer.installer_setup_config import _update_env_model_config

        env_file = tmp_path / ".env"
        original = "NEXE_PRIMARY_API_KEY=abc123\nNEXE_MODEL_ENGINE=ollama\n"
        env_file.write_text(original)

        # Red gate: crashava amb TypeError: 'NoneType' object is not subscriptable
        _update_env_model_config(env_file, None)

        # .env no modificat
        assert env_file.read_text() == original

    def test_none_model_config_preserves_api_key(self, tmp_path):
        """API key no es perd quan cridem _update_env_model_config(None)."""
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


# ── Tests generate_env_file amb model_config=None ────────────────────────────

class TestGenerateEnvFileNone:
    """generate_env_file accepta model_config=None (nou install sense model)."""

    def test_new_env_file_created_without_model(self, tmp_path, capsys):
        """Nou .env generat quan model_config=None (cap model seleccionat)."""
        from installer.installer_setup_config import generate_env_file

        generate_env_file(tmp_path, model_config=None)

        env_file = tmp_path / ".env"
        assert env_file.exists(), ".env no s'ha creat"
        content = env_file.read_text()
        # Clau API generada
        assert "NEXE_PRIMARY_API_KEY=" in content
        # Comentari per afegir model manualment
        assert "nexe model pull" in content
        # Cap línia activa (no comentada) amb NEXE_DEFAULT_MODEL=
        active_model_lines = [line for line in content.splitlines() if line.startswith("NEXE_DEFAULT_MODEL=")]
        assert active_model_lines == [], f"No hauria d'haver NEXE_DEFAULT_MODEL actiu: {active_model_lines}"

    def test_existing_env_not_overwritten_with_none(self, tmp_path, capsys):
        """Si .env ja existeix i model_config=None, no es sobreescriu."""
        from installer.installer_setup_config import generate_env_file

        env_file = tmp_path / ".env"
        env_file.write_text("NEXE_PRIMARY_API_KEY=keep-this-key\n")

        generate_env_file(tmp_path, model_config=None)

        # Clau original preservada
        assert "keep-this-key" in env_file.read_text()


# ── Tests run_headless_inner amb model_key="" ─────────────────────────────────

class TestRunHeadlessNoModel:
    """run_headless_inner amb model_key="" (Continuar sense model)."""

    def test_empty_model_key_reaches_step4(self, monkeypatch, tmp_path):
        """Amb model_key='', l'installer arriba al Step 4 (config) sense crash."""
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

        # Si algu crida una descarrega -> error (no hi ha model_key)
        def _no_download(*a, **k):
            raise AssertionError("Cap descarrega esperada sense model seleccionat")

        monkeypatch.setattr(ih, "_download_ollama_model", _no_download)
        monkeypatch.setattr(ih, "_download_gguf_model", _no_download)
        monkeypatch.setattr(ih, "_download_mlx_model", _no_download)
        monkeypatch.setattr(ih, "ensure_ollama_installed", lambda: True)

        # Capturar la crida a generate_env_file
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
            "model_key": "",   # ← "Continuar sense model"
            "engine": "ollama",
        }

        try:
            ih._run_headless_inner(config)
        except SystemExit:
            pass  # Darwin login items pot fer sys.exit en test

        # generate_env_file ha de ser cridat amb model_config=None
        assert generate_called, "generate_env_file no s'ha cridat"
        assert generate_called[0] is None, (
            f"model_config hauria de ser None, got: {generate_called[0]}"
        )

    def test_empty_model_key_sets_skip_model(self, monkeypatch, tmp_path):
        """model_key='' activa skip_model_download internament."""
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
            f"Cap descarrega esperada amb model_key='', però s'han cridat: {download_calls}"
        )
