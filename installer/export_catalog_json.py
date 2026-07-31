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


# ── Tier coherence (#852 follow-up) ────────────────────────────────────────
# Minimum machine RAM each tier targets. NOT invented here: it is the inverse
# of the wizard's own tier resolution, HardwareDetector.swift:15-20
#     if ramGB >= 32 { "tier_32" }; >= 24 { "tier_24" }; >= 16 { "tier_16" }
#     else { "tier_8" }
# so a machine sitting on tier_N has AT LEAST N GB (and tier_32 is open-ended —
# tier_48/tier_64 were removed when the catalog narrowed to four tiers, see
# CHANGELOG "Installer wizard tier mismatch on 48+ GB machines").
_TIER_MIN_RAM_GB = {"tier_8": 8, "tier_16": 16, "tier_24": 24, "tier_32": 32}

# ── The two usable-RAM fractions, side by side and ON PURPOSE ──────────────
#
# They are DIFFERENT, and as of 31/07 nobody has decided which one is right —
# so they live here together instead of hand-written at each call site, which
# is how they drifted apart in the first place. Changing either is a product
# decision; changing one WITHOUT the other is a bug, and the guards below say so.
#
# WIZARD (0.75) — ModelPickerView.swift:141-146. A model is greyed out when
#   `model.ramGB > hardware.ramGB * 0.75`, strict `>` (B171) so a model exactly
#   on the boundary stays selectable. Explicit product decision (Jordi, 31/07).
#
# CLI (0.55) — installer_catalog.py. It has its own written support: the wizard
#   prints "~N GB (50-60%)" to the user (installer_catalog.py:212) and
#   `ram_reserved_note` promises the rest goes to macOS and other apps, in all
#   three languages. Its category thresholds (5/20/28) are calibrated on it too
#   — see the B159 comment: ">=28GB usable ~ 52GB+ RAM" only works out at 0.55.
#   So moving the CLI to 0.75 is not a one-number change: it drags the category
#   thresholds and the user-facing text with it.
#
# See dev2_result_f7.md for the measured verdict-by-verdict divergence.
WIZARD_USABLE_FRACTION = 0.75
CLI_USABLE_FRACTION = 0.55

# Backwards-compatible alias (the tier guards below were written against it).
_PICKER_USABLE_FRACTION = WIZARD_USABLE_FRACTION


def resolve_tier(ram_gb: int) -> str:
    """Tier a machine with ``ram_gb`` lands on — inverse of HardwareDetector.swift:15-20."""
    for tier, minimum in sorted(_TIER_MIN_RAM_GB.items(), key=lambda kv: -kv[1]):
        if ram_gb >= minimum:
            return tier
    return "tier_8"


def simulate_picker(json_path: str, ram_gb: int, tier: str | None = None) -> dict:
    """What the wizard shows a machine with ``ram_gb``, computed in Python.

    A faithful replica of ModelPickerView's arithmetic — the Swift package ships
    no test target, so this is how the "who is recommended, who is greyed out"
    contract gets covered at all. It mirrors, in this order:

      * the tab that opens: ``hardware.ramTier`` (HardwareDetector.swift:15-20);
      * disabled: ``model.ramGB > hardware.ramGB * 0.75`` — STRICT ``>``, so a
        model sitting exactly on the limit stays selectable (B171 comment at
        ModelPickerView.swift:67; mistral_small_24b is exactly 18.0 on a 24 GB
        machine and depends on it);
      * recommended: the first model of the tier that is NOT disabled, or none
        at all (ModelPickerView.swift:140-146, decision B of 31/07).

    Being a replica, it can drift from the Swift. The guards below pin the
    catalog against it; the smoke test is what pins the Swift.
    """
    data = json.loads(Path(json_path).read_text(encoding="utf-8"))
    tier = tier or resolve_tier(ram_gb)
    usable = ram_gb * _PICKER_USABLE_FRACTION
    models = data.get(tier, [])
    enabled = [m["key"] for m in models if m.get("ram_gb", 0) <= usable]
    return {
        "tier": tier,
        "usable_gb": usable,
        "recommended": enabled[0] if enabled else None,
        "enabled": enabled,
        "disabled": [m["key"] for m in models if m.get("ram_gb", 0) > usable],
    }


def tier_consistency_errors(json_path: str) -> list[str]:
    """Flag tiers that offer NOTHING installable on the RAM that selects them.

    Decision D (Jordi, 31/07). The phase-5 invariant — "the FIRST model of a
    tier must fit" — died with decision B: the recommendation is now the first
    model that FITS, so a heavy entry at the head of a tier is harmless. What
    remains intolerable is a tier that hands its own machine an empty list:

      * a machine on tier_N has at least N GB (HardwareDetector.swift:15-20);
      * it opens the tier_N tab (ModelPickerView.swift:136);
      * everything above 75% of its RAM is greyed out (ModelPickerView.swift:67).

    If nothing in tier_N clears N × 0.75, that machine reaches the picker and
    can select nothing at all. Heavier models may live in the tier (alia_40b
    and mixtral_8x7b stay in tier_32 by explicit product decision — the tier is
    "32 GB+", open-ended); they simply must not be the only ones.

    Returns a list of error strings (empty when coherent).
    """
    data = json.loads(Path(json_path).read_text(encoding="utf-8"))
    errors: list[str] = []
    for tier, models in data.items():
        if not models:
            continue
        min_ram = _TIER_MIN_RAM_GB.get(tier)
        if min_ram is None:
            errors.append(
                f"[TIER] '{tier}' no té RAM mínima coneguda — "
                f"HardwareDetector.swift no el pot proposar mai"
            )
            continue
        view = simulate_picker(json_path, min_ram, tier=tier)
        if not view["enabled"]:
            lightest = min(m.get("ram_gb", 0) for m in models)
            errors.append(
                f"[TIER] '{tier}': cap model instal·lable en una màquina de "
                f"{min_ram} GB (límit {view['usable_gb']:.1f} GB = {min_ram}×"
                f"{_PICKER_USABLE_FRACTION}; el més lleuger demana {lightest} GB) "
                f"— aquest tier no ofereix res a la seva pròpia RAM"
            )
    return errors


# Numeric metadata that BOTH catalogs must agree on. ram_gb drives what the
# wizard tells the user will fit; disk_gb drives the download-size UX and the
# RAM floor derived from it (installer_catalog_data.estimate_min_ram_gb).
_SYNCED_NUMERIC_FIELDS = ("ram_gb", "disk_gb")


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


# What each side is EXPECTED to use. A change here is a deliberate act; a change
# at a call site without one here is the drift this guard exists to catch.
_EXPECTED_FRACTIONS = {"wizard": 0.75, "cli": 0.55}


def _usable_fraction_errors() -> list[str]:
    """Both usable-RAM fractions must be the documented ones AND come from here.

    Not "both must be equal": today they are not, deliberately, and deciding
    which one wins is a product call. What is guarded is that neither moves
    unnoticed and that the CLI reads the shared constant instead of a literal
    of its own — a literal is exactly how the two drifted apart.
    """
    errors: list[str] = []
    for side, expected in _EXPECTED_FRACTIONS.items():
        actual = WIZARD_USABLE_FRACTION if side == "wizard" else CLI_USABLE_FRACTION
        if actual != expected:
            errors.append(
                f"[RAM-FRACTION] la fracció del camí '{side}' ha canviat "
                f"({expected} → {actual}) — revisa l'ALTRE camí i el snapshot de "
                f"divergència (tests/test_catalog_sync.py) abans de donar-ho per bo"
            )
    try:
        from installer.installer_catalog import usable_ram_gb
    except ImportError as exc:  # pragma: no cover - the CLI must be importable
        errors.append(f"[RAM-FRACTION] no puc importar el CLI per verificar-lo: {exc}")
        return errors
    # 100 GB keeps the truncation out of the way: 100 × 0.55 = 55.0 exactly.
    if usable_ram_gb(100) != int(100 * CLI_USABLE_FRACTION):
        errors.append(
            "[RAM-FRACTION] el CLI no calcula la RAM utilitzable amb "
            "CLI_USABLE_FRACTION — torna a tenir un literal propi"
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

    errors.extend(_usable_fraction_errors())

    # Decision D (31/07): a tier that offers nothing to its own machine is a
    # broken catalog. Left out of validate() in phase 5 because the invariant of
    # the day ("the first model of a tier must fit") was violated by the shipped
    # catalog; decision B removed that violation, so the guard now belongs on
    # the CI path like the rest.
    errors.extend(tier_consistency_errors(json_path))

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
        # #852: the sizing numbers must agree between the two files. The #852
        # fix corrected the Python catalog and never reached models.json, which
        # is the file the DMG wizard reads — alia_40b kept telling a 24 GB Mac
        # that 42 GB of weights fit, and every guard in the house passed. Keys
        # and backends matching says nothing about the number the user is shown.
        for field in _SYNCED_NUMERIC_FIELDS:
            jv, pv = jm.get(field), pm.get(field)
            if jv != pv:
                errors.append(
                    f"[SYNC] '{key}': {field} mismatch — JSON={jv!r} vs "
                    f".py={pv!r} — el wizard del DMG llegeix el JSON"
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
