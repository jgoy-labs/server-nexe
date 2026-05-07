"""
Synchronisation test between the two installer model catalogues:

  - installer/installer_catalog_data.py (SSOT for download, schema small/medium/large)
  - installer/swift-wizard/Resources/models.json (SSOT for UX, schema tier_8..tier_64)

Both files coexist by design (2026-04-14). The Swift wizard passes
`model_key` to install_headless.py via JSON, so every model shown in the
UI must exist in the Python catalogue or the installer will fail with
"Model not found".

This test is a CI guard: if someone adds a model to the JSON without
adding it to the .py (or diverges the available backends), it fails.
"""

import json
from pathlib import Path

from installer.installer_catalog_data import MODEL_CATALOG


def _py_by_key():
    out = {}
    for _, models in MODEL_CATALOG.items():
        for m in models:
            out[m["key"]] = m
    return out


def _json_path():
    return (
        Path(__file__).resolve().parent.parent
        / "installer" / "swift-wizard" / "Resources" / "models.json"
    )


def _json_by_key():
    data = json.loads(_json_path().read_text(encoding="utf-8"))
    out = {}
    for _, models in data.items():
        for m in models:
            out[m["key"]] = m
    return out


def test_every_json_model_exists_in_python_catalog():
    py = _py_by_key()
    js = _json_by_key()
    missing = sorted(k for k in js if k not in py)
    assert not missing, (
        f"Models al Swift wizard JSON però no a installer_catalog_data.py: {missing}. "
        "Això provocarà [ERROR] Model not found a install_headless.py si l'usuari els tria."
    )


def test_mlx_backend_presence_matches():
    py = _py_by_key()
    js = _json_by_key()
    mismatches = []
    for k, jm in js.items():
        if k not in py:
            continue
        if bool(jm.get("mlx")) != bool(py[k].get("mlx")):
            mismatches.append(
                f"{k}: JSON mlx={jm.get('mlx')!r} vs .py mlx={py[k].get('mlx')!r}"
            )
    assert not mismatches, f"Backend mlx desincronitzat: {mismatches}"


def test_ollama_backend_presence_matches():
    py = _py_by_key()
    js = _json_by_key()
    mismatches = []
    for k, jm in js.items():
        if k not in py:
            continue
        if bool(jm.get("ollama")) != bool(py[k].get("ollama")):
            mismatches.append(
                f"{k}: JSON ollama={jm.get('ollama')!r} vs .py ollama={py[k].get('ollama')!r}"
            )
    assert not mismatches, f"Backend ollama desincronitzat: {mismatches}"


def test_gguf_backend_presence_matches():
    py = _py_by_key()
    js = _json_by_key()
    mismatches = []
    for k, jm in js.items():
        if k not in py:
            continue
        if bool(jm.get("gguf")) != bool(py[k].get("gguf")):
            mismatches.append(
                f"{k}: JSON gguf={jm.get('gguf')!r} vs .py gguf={py[k].get('gguf')!r}"
            )
    assert not mismatches, f"Backend gguf desincronitzat: {mismatches}"


def test_export_catalog_json_validates():
    """The `export_catalog_json.py` script (validator mode) must pass."""
    from installer.export_catalog_json import validate
    errors = validate(str(_json_path()))
    assert not errors, f"Validator errors: {errors}"
