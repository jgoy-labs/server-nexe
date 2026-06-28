"""
------------------------------------
Server Nexe
Location: installer/export_catalog_json.py
Description: Sync validator between installer_catalog_data.py
             (SSOT for model downloads) and swift-wizard/Resources/models.json
             (SSOT for wizard UX, RAM-based tiers).

             Both files coexist by design (2026-04-14):
               - .py has a small/medium/large schema with rich download fields
                 (real mlx URL, chat_format, prompt_tier, lang) — consumed by
                 install_headless.py and the interactive CLI.
               - .json has a tier_8..tier_64 schema for UX with boolean flags
                 consumed by the Swift wizard (ModelCatalog.swift).

             This script does NOT regenerate the JSON (it would lose the
             RAM-tier distribution edited by hand). It validates that every
             `key` in the JSON exists in the .py and that the backends are
             consistent (mlx/ollama/gguf present in both places). Runs in CI
             (test_installer_catalog.py).

             To structurally regenerate the JSON from the .py an explicit
             `--force` is required (not recommended; will break the wizard UX).
------------------------------------
"""

import json
import sys
import os
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from installer.installer_catalog_data import MODEL_CATALOG


def _flatten_py():
    """Return dict {key: model_dict} from the Python catalog."""
    out = {}
    for _, models in MODEL_CATALOG.items():
        for m in models:
            out[m["key"]] = m
    return out


def _flatten_json(path):
    """Return dict {key: model_dict} from the JSON catalog."""
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    out = {}
    for _, models in data.items():
        for m in models:
            out[m["key"]] = m
    return out


def _duplicate_key_errors(label: str, catalog: dict) -> list[str]:
    """Detect keys present in more than one tier (B158).

    The catalog dicts are flattened with out[key]=model, so a duplicated key
    silently collapses (last wins) and any metadata divergence (e.g. ram_gb
    10 vs 22 for the same artifact) is hidden. Flag it before the flatten.
    """
    seen: dict = {}
    for tier, models in catalog.items():
        for m in models:
            seen.setdefault(m["key"], []).append((tier, m))
    errors: list[str] = []
    for key, occ in seen.items():
        if len(occ) < 2:
            continue
        tiers = ", ".join(t for t, _ in occ)
        divergent = []
        for field in ("ram_gb", "disk_gb"):
            vals = {m.get(field) for _, m in occ}
            if len(vals) > 1:
                divergent.append(
                    f"{field}={sorted(v for v in vals if v is not None)}"
                )
        detail = (
            f" amb metadades divergents ({'; '.join(divergent)})"
            if divergent
            else ""
        )
        errors.append(
            f"[DUP] {label}: clau '{key}' apareix a {len(occ)} tiers "
            f"({tiers}){detail} — el catàleg col·lapsa per clau i amaga la divergència"
        )
    return errors


def validate(json_path: str) -> list[str]:
    """Validate sync. Return list of errors (empty if all OK)."""
    py = _flatten_py()
    js = _flatten_json(json_path)
    errors: list[str] = []

    # B158: claus duplicades dins un mateix catàleg col·lapsen al flatten i
    # amaguen divergències de metadades (gemma4_31b: ram_gb 10 vs 22). Caça-ho.
    errors.extend(_duplicate_key_errors("installer_catalog_data.py", MODEL_CATALOG))
    errors.extend(
        _duplicate_key_errors(
            "models.json",
            json.loads(Path(json_path).read_text(encoding="utf-8")),
        )
    )

    for key, jm in js.items():
        if key not in py:
            errors.append(
                f"[SYNC] JSON model '{key}' NO existeix a installer_catalog_data.py "
                f"→ install_headless.py fallarà amb 'Model not found'"
            )
            continue
        pm = py[key]
        # Bool JSON vs URL .py: both must match in presence
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
    """Backward-compat: validates. Structural generation requires --force."""
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
    """CLI entry point for validating sync between Python and JSON model catalogs."""
    import argparse
    parser = argparse.ArgumentParser(
        description="Sync validator between installer_catalog_data.py and models.json"
    )
    parser.add_argument(
        "json_path",
        nargs="?",
        default=_default_json_path(),
        help="Path to models.json (default: installer/swift-wizard/Resources/models.json)",
    )
    parser.add_argument(
        "--check",
        action="store_true",
        help="Pure validator mode (CI): exit 0 if OK, exit 1 with errors to stderr",
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
