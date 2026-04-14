"""
------------------------------------
Server Nexe
Location: installer/export_catalog_json.py
Description: Validador de sincronia entre installer_catalog_data.py
             (SSOT per a descarrega de models) i swift-wizard/Resources/models.json
             (SSOT per a UX del wizard, tiers basats en RAM).

             Els dos fitxers conviuen per disseny (2026-04-14):
               - .py té schema small/medium/large i camps de descarrega rics
                 (mlx URL real, chat_format, prompt_tier, lang) — consumit
                 per install_headless.py i la CLI interactiva.
               - .json té schema tier_8..tier_64 per UX i flags booleans
                 consumit pel Swift wizard (ModelCatalog.swift).

             Aquest script NO regenera el JSON (perdria la distribucio RAM-tier
             editada a ma). Valida que tot `key` al JSON existeixi al .py
             i que els backends siguin coherents (mlx/ollama/gguf presents
             als dos llocs). S'executa al CI (test_installer_catalog.py).

             Per regenerar estructural el JSON des del .py cal un `--force`
             explicit (no recomanat; trencarà la UX del wizard).
------------------------------------
"""

import json
import sys
import os
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from installer.installer_catalog_data import MODEL_CATALOG


def _flatten_py():
    """Retorna dict {key: model_dict} del catàleg Python."""
    out = {}
    for _, models in MODEL_CATALOG.items():
        for m in models:
            out[m["key"]] = m
    return out


def _flatten_json(path):
    """Retorna dict {key: model_dict} del catàleg JSON."""
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    out = {}
    for _, models in data.items():
        for m in models:
            out[m["key"]] = m
    return out


def validate(json_path: str) -> list[str]:
    """Valida sincronia. Retorna llista d'errors (buida si tot OK)."""
    py = _flatten_py()
    js = _flatten_json(json_path)
    errors: list[str] = []

    for key, jm in js.items():
        if key not in py:
            errors.append(
                f"[SYNC] JSON model '{key}' NO existeix a installer_catalog_data.py "
                f"→ install_headless.py fallarà amb 'Model not found'"
            )
            continue
        pm = py[key]
        # Bool JSON vs URL .py: tots dos han de coincidir en presència
        if bool(jm.get("mlx")) != bool(pm.get("mlx")):
            errors.append(
                f"[SYNC] '{key}': mlx mismatch — JSON={jm.get('mlx')!r} "
                f"(bool) vs .py={pm.get('mlx')!r} (URL or None)"
            )
        if bool(jm.get("ollama")) != bool(pm.get("ollama")):
            errors.append(
                f"[SYNC] '{key}': ollama presence mismatch — "
                f"JSON={jm.get('ollama')!r} vs .py={pm.get('ollama')!r}"
            )
        if bool(jm.get("gguf")) != bool(pm.get("gguf")):
            errors.append(
                f"[SYNC] '{key}': gguf presence mismatch — "
                f"JSON={jm.get('gguf')!r} vs .py={pm.get('gguf')!r}"
            )
    return errors


def _default_json_path():
    return os.path.join(
        os.path.dirname(__file__), "swift-wizard", "Resources", "models.json"
    )


def export_catalog(output_path: str):
    """Backward-compat: valida. Per generar estructural cal --force."""
    errors = validate(output_path)
    if errors:
        print("Errors de sincronia detectats:", file=sys.stderr)
        for e in errors:
            print(f"  - {e}", file=sys.stderr)
        sys.exit(1)
    py = _flatten_py()
    js = _flatten_json(output_path)
    print(f"Sync OK: {len(js)} models al JSON, {len(py)} al .py, tots alineats.")


def _cli():
    import argparse
    parser = argparse.ArgumentParser(
        description="Validador de sincronia entre installer_catalog_data.py i models.json"
    )
    parser.add_argument(
        "json_path",
        nargs="?",
        default=_default_json_path(),
        help="Path al models.json (default: installer/swift-wizard/Resources/models.json)",
    )
    parser.add_argument(
        "--check",
        action="store_true",
        help="Mode validator pur (CI): exit 0 si OK, exit 1 amb errors a stderr",
    )
    args = parser.parse_args()

    errors = validate(args.json_path)
    if errors:
        print("Errors de sincronia detectats:", file=sys.stderr)
        for e in errors:
            print(f"  - {e}", file=sys.stderr)
        sys.exit(1)

    py = _flatten_py()
    js = _flatten_json(args.json_path)
    print(f"Sync OK: {len(js)} models al JSON, {len(py)} al .py, tots alineats.")
    sys.exit(0)


if __name__ == "__main__":
    _cli()
