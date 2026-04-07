"""
────────────────────────────────────
Server Nexe
Author: Jordi Goy
Location: tests/test_install_skip_model.py
Description: Tests per Bug 28 — flag --skip-model-download al installer
             headless. Permet a l'usuari saltar la descarrega proactivament;
             el model escollit queda registrat al .env i `storage/models/`
             queda buit (l'usuari el descarrega despres via `nexe model pull`).

www.jgoy.net · https://server-nexe.org
────────────────────────────────────
"""
import sys

import pytest

from installer.install_headless import _parse_cli_overrides


def test_parse_cli_skip_model_download_flag():
    """`--skip-model-download` -> overrides['skip_model_download'] = True."""
    overrides = _parse_cli_overrides(["--skip-model-download"])
    assert overrides.get("skip_model_download") is True


def test_parse_cli_skip_model_download_combined_with_reinstall():
    """Combinacio amb --reinstall-mode segueix funcionant."""
    overrides = _parse_cli_overrides([
        "--skip-model-download",
        "--reinstall-mode", "wipe",
    ])
    assert overrides["skip_model_download"] is True
    assert overrides["reinstall_mode"] == "wipe"


def test_parse_cli_no_flag_default_off():
    """Sense flag, no apareix la clau (default off via .get())."""
    overrides = _parse_cli_overrides([])
    assert "skip_model_download" not in overrides


def test_run_headless_skip_model_does_not_download(monkeypatch, tmp_path):
    """`run_headless` amb skip_model_download no crida cap _download_*.

    Verifica el comportament Bug 28: el model NO es descarrega, pero el
    .env s'escriu igualment (registrant el model_key + engine).
    Storage/models queda buit.
    """
    import installer.install_headless as ih

    project_root = tmp_path / "nexe-install"
    project_root.mkdir()

    # Stubs de tot el que toca disc/xarxa
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

    # Si algu crida una descarrega -> test failure
    def _no_download(*a, **k):
        raise AssertionError("Model download must NOT be called when skip_model_download=True")

    monkeypatch.setattr(ih, "_download_ollama_model", _no_download)
    monkeypatch.setattr(ih, "_download_gguf_model", _no_download)
    monkeypatch.setattr(ih, "_download_mlx_model", _no_download)
    monkeypatch.setattr(ih, "ensure_ollama_installed", lambda: True)

    # Stub generate_env_file: simula escriptura del .env amb el model
    captured_env = {}

    def _fake_generate(root, model_cfg):
        captured_env["model_id"] = model_cfg["id"]
        captured_env["engine"] = model_cfg["engine"]
        env_file = root / ".env"
        env_file.write_text(
            f"NEXE_PRIMARY_API_KEY=test-key\n"
            f"NEXE_MODEL_ID={model_cfg['id']}\n"
            f"NEXE_ENGINE={model_cfg['engine']}\n"
        )

    monkeypatch.setattr(ih, "generate_env_file", _fake_generate)
    # Q5.5 reobert (2026-04-08): download_qdrant eliminat — Qdrant és embedded.
    # El mock que abans existia aquí ja no cal perquè la funció no existeix.
    monkeypatch.setattr(ih, "_write_commands_file", lambda *a, **k: None)

    # Curtcircuit per al subprocess d'embeddings i ingestio
    import subprocess
    monkeypatch.setattr(
        subprocess, "run",
        lambda *a, **k: type("R", (), {"returncode": 0, "stdout": "", "stderr": ""})(),
    )

    # Catalog reduit per al test (busca model_key real existent)
    from installer.installer_catalog_data import MODEL_CATALOG
    sample_key = None
    for cat in MODEL_CATALOG.values():
        for m in cat:
            if m.get("ollama"):
                sample_key = m["key"]
                break
        if sample_key:
            break
    assert sample_key, "Catalog buit, no es pot fer test"

    config = {
        "lang": "ca",
        "path": str(project_root),
        "model_key": sample_key,
        "engine": "ollama",
        "skip_model_download": True,
    }

    # Aïllem el SystemExit final per platforms no-Darwin / Login Items
    try:
        ih._run_headless_inner(config)
    except SystemExit:
        pass

    # .env escrit amb el model
    env_file = project_root / ".env"
    assert env_file.exists(), ".env no s'ha generat"
    content = env_file.read_text()
    assert "NEXE_MODEL_ID=" in content
    # storage/models buit (cap descarrega)
    models_dir = project_root / "storage" / "models"
    if models_dir.exists():
        assert list(models_dir.iterdir()) == [], (
            f"storage/models hauria d'estar buit: {list(models_dir.iterdir())}"
        )
