"""
Tests per installer/installer_catalog_data.py — Bug 29 fix release v0.9.0.

Phi-3.5 ha estat retirat del catàleg perquè la URL GGUF de Microsoft
requereix login HF i només descarregava 29 bytes (HTML d'error),
provocant falles silencioses durant la instal·lació.
"""

import json
from pathlib import Path

from installer.installer_catalog_data import MODEL_CATALOG


def _all_keys():
    keys = []
    for category in MODEL_CATALOG.values():
        for model in category:
            keys.append(model["key"])
    return keys


def test_phi35_not_in_python_catalog():
    assert "phi35" not in _all_keys()


def test_no_phi3_mini_ollama_tag():
    for category in MODEL_CATALOG.values():
        for model in category:
            assert model.get("ollama") != "phi3:mini"


def test_no_phi35_gguf_url():
    for category in MODEL_CATALOG.values():
        for model in category:
            gguf = model.get("gguf") or ""
            assert "Phi-3.5" not in gguf
            assert "phi-3.5" not in gguf.lower()


def test_phi35_not_in_swift_wizard_models_json():
    """El catàleg JSON paral·lel del Swift wizard també ha d'estar net."""
    json_path = (
        Path(__file__).resolve().parent.parent
        / "installer" / "swift-wizard" / "Resources" / "models.json"
    )
    if not json_path.exists():
        # Si no hi és en aquest checkout, no fallem el test.
        return
    data = json.loads(json_path.read_text())
    keys = []
    for category_models in data.values():
        for model in category_models:
            keys.append(model.get("key"))
    assert "phi35" not in keys


def test_catalog_still_has_small_models():
    """Sanity: encara hi ha models petits després de treure phi35."""
    assert len(MODEL_CATALOG.get("small", [])) >= 2
