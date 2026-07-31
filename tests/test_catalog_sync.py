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


# ═══════════════════════════════════════════════════════════════════════════
# #852 follow-up — the RAM numbers must match ACROSS the two files.
#
# The #852 fix landed in the Python catalog and did NOT reach models.json, the
# file the DMG wizard actually reads: alia_40b kept telling users that 42 GB of
# weights fit in a 24 GB machine. Nothing in the house caught it — the sync
# guard only ever compared keys and backend presence, and the repo already knew
# this field lies (B158 cites "ram_gb 10 vs 22"), but only WITHIN one file.
# ═══════════════════════════════════════════════════════════════════════════

import pytest  # noqa: E402  # after the module's own helpers

from installer.installer_catalog_data import estimate_min_ram_gb  # noqa: E402

_SYNCED_NUMERIC_FIELDS = ("ram_gb", "disk_gb")


@pytest.mark.parametrize("field", _SYNCED_NUMERIC_FIELDS)
def test_numeric_fields_match_between_the_two_catalogs(field):
    """Same model, same numbers, whichever file the caller reads."""
    py, js = _py_by_key(), _json_by_key()
    mismatches = {
        k: (js[k].get(field), py[k].get(field))
        for k in js if k in py and js[k].get(field) != py[k].get(field)
    }
    assert not mismatches, (
        f"{field} desincronitzat (JSON vs .py): {mismatches} — "
        f"el wizard del DMG llegeix el JSON"
    )


def test_json_entries_clear_the_ram_floor():
    """The wizard's own copy must obey the verified formula too — the gate in
    tests/test_f852_catalog_ram_formula.py only covers the Python catalog."""
    offenders = {
        k: (m.get("ram_gb"), estimate_min_ram_gb(m.get("disk_gb", 0)))
        for k, m in _json_by_key().items()
        if m.get("ram_gb", 0) < estimate_min_ram_gb(m.get("disk_gb", 0))
    }
    assert not offenders, f"models.json declara menys RAM que pesos+1,15 GB: {offenders}"


def test_validate_catches_a_diverging_ram_gb(tmp_path):
    """The guard itself, driven on a doctored copy — the real models.json is
    never touched.

    Mutation guard: drop the numeric comparison from validate() and this goes
    RED. This is the test that would have caught the #852 fix stopping at the
    Python catalog.
    """
    from installer.export_catalog_json import validate

    data = json.loads(_json_path().read_text(encoding="utf-8"))
    patched = False
    for models in data.values():
        for m in models:
            if m["key"] == "alia_40b":
                m["ram_gb"] = 24.0  # the historical lie
                patched = True
    assert patched, "alia_40b ha desaparegut del JSON — actualitza aquest test"

    doctored = tmp_path / "models.json"
    doctored.write_text(json.dumps(data), encoding="utf-8")

    errors = validate(str(doctored))
    assert any("ram_gb" in e and "alia_40b" in e for e in errors), errors


def test_validate_catches_a_diverging_disk_gb(tmp_path):
    """Same guard, the other field: disk_gb feeds the download-size UX and the
    RAM floor, so a divergence there is not cosmetic either."""
    from installer.export_catalog_json import validate

    data = json.loads(_json_path().read_text(encoding="utf-8"))
    for models in data.values():
        for m in models:
            if m["key"] == "qwen35_9b":
                m["disk_gb"] = 99.9

    doctored = tmp_path / "models.json"
    doctored.write_text(json.dumps(data), encoding="utf-8")

    errors = validate(str(doctored))
    assert any("disk_gb" in e and "qwen35_9b" in e for e in errors), errors


def test_validate_is_quiet_on_the_real_pair():
    """No false positives: the shipped files must validate clean."""
    from installer.export_catalog_json import validate

    assert validate(str(_json_path())) == []


# ═══════════════════════════════════════════════════════════════════════════
# Tier coherence, decisions B + D (Jordi, 31/07).
#
# Phase 5 guarded "the first model of a tier must fit", because isRecommended
# returned models(for: tier).first blindly. Decision B changed the Swift: the
# recommendation is now the first model that FITS the detected RAM, so a heavy
# entry at the head of a tier is no longer a defect — and qwen35_27b stops
# being an offender by construction.
#
# What replaces it: a tier may never leave its OWN machine with nothing
# installable. tier_32 is "32 GB+" and deliberately holds models only a bigger
# Mac can run (alia_40b, mixtral_8x7b — product decision); that is fine as long
# as something in it runs on 32 GB.
#
# The Swift package ships no test target (no Tests/, no testTarget in
# Package.swift), so the picker arithmetic is covered here against a Python
# replica, simulate_picker(). What the replica cannot prove — that the real
# GUI paints the same — is covered by the manual smoke in docs/PROVES-WIZARD.md.
# ═══════════════════════════════════════════════════════════════════════════


def test_no_tier_is_empty_for_its_own_machine():
    """The shipped catalog must offer something at every tier's minimum RAM.

    Mutation guard: demonstrated green→red→green on the real file by moving the
    only light model out of a tier.
    """
    from installer.export_catalog_json import tier_consistency_errors

    assert tier_consistency_errors(str(_json_path())) == []


def test_tier_guard_reaches_validate_and_therefore_the_ci():
    """Decision D: the guard must ride the existing CI path, not a new one.

    test_export_catalog_json_validates already calls validate(); this pins that
    validate() actually consults the tier guard.

    Mutation guard: drop the tier_consistency_errors call from validate() and
    this goes RED.
    """
    from installer.export_catalog_json import validate

    data = json.loads(_json_path().read_text(encoding="utf-8"))
    # A tier whose only model needs more than 8 × 0.75 = 6 GB.
    heavy = next(m for ms in data.values() for m in ms if m["key"] == "alia_40b")
    data["tier_8"] = [heavy]
    import tempfile
    with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False) as fh:
        json.dump(data, fh)
        doctored = fh.name
    errors = validate(doctored)
    assert any("[TIER]" in e and "tier_8" in e for e in errors), errors


def test_empty_tier_is_reported(tmp_path):
    from installer.export_catalog_json import tier_consistency_errors

    data = json.loads(_json_path().read_text(encoding="utf-8"))
    heavy = next(m for ms in data.values() for m in ms if m["key"] == "mixtral_8x7b")
    doctored = tmp_path / "models.json"
    doctored.write_text(json.dumps({"tier_8": [heavy]}), encoding="utf-8")

    errors = tier_consistency_errors(str(doctored))
    assert any("tier_8" in e and "cap model instal·lable" in e for e in errors), errors


def test_tier_thresholds_match_the_swift_wizard():
    """The mapping is the inverse of HardwareDetector.swift:15-20.

    Mutation guard: change any threshold and this goes RED.
    """
    from installer.export_catalog_json import _TIER_MIN_RAM_GB

    assert _TIER_MIN_RAM_GB == {"tier_8": 8, "tier_16": 16, "tier_24": 24, "tier_32": 32}


# ── Simulated RAM: the decisions B and C, machine by machine ────────────────

class TestSimulatedMachines:
    """Every case Jordi asked to see, computed on the shipped catalog."""

    def _view(self, ram_gb):
        from installer.export_catalog_json import simulate_picker
        return simulate_picker(str(_json_path()), ram_gb)

    def test_24gb_crowns_mistral_small_and_greys_out_qwen35_27b(self):
        """Decision C, and it must fall out of B — no reordering of the JSON.

        Mutation guard: revert the recommendation to "first of the tier" and
        this goes RED (qwen35_27b would be crowned while disabled).
        """
        v = self._view(24)
        assert v["tier"] == "tier_24"
        assert v["recommended"] == "mistral_small_24b"
        assert "qwen35_27b" in v["disabled"]
        assert "gpt_oss_20b" in v["disabled"]

    def test_24gb_recommendation_sits_exactly_on_the_limit(self):
        """mistral_small_24b needs 18.0 and the limit is 24 × 0.75 = 18.0.

        Strict '>' (B171) is what keeps it selectable. With '>=' this machine
        would have NO recommendation at all.

        Mutation guard: swap '>' for '>=' in simulate_picker and this goes RED.
        """
        v = self._view(24)
        assert v["usable_gb"] == 18.0
        assert v["recommended"] == "mistral_small_24b"

    def test_64gb_enables_alia_40b(self):
        """Decision A: tier_32 is "32 GB+", and the big machine gets the big
        model without moving it anywhere (43.2 <= 64 × 0.75 = 48)."""
        v = self._view(64)
        assert v["tier"] == "tier_32"
        assert v["disabled"] == []
        assert "alia_40b" in v["enabled"]

    def test_32gb_disables_alia_40b(self):
        """Same tier, smaller machine: 43.2 > 32 × 0.75 = 24."""
        v = self._view(32)
        assert v["tier"] == "tier_32"
        assert "alia_40b" in v["disabled"]
        assert "mixtral_8x7b" in v["disabled"]
        assert v["recommended"] == "qwen35_35b_moe"

    def test_8gb_and_16gb_have_a_working_recommendation(self):
        assert self._view(8)["recommended"] == "qwen35_4b"
        assert self._view(16)["recommended"] == "qwen35_9b"

    def test_every_simulated_machine_can_install_something(self):
        """The user-facing meaning of decision D."""
        for ram in (8, 16, 24, 32, 64):
            v = self._view(ram)
            assert v["recommended"] is not None, f"{ram} GB: cap model instal·lable ({v})"
            assert v["recommended"] in v["enabled"]

    def test_the_recommendation_is_never_a_disabled_model(self):
        """The invariant decision B buys: it cannot crown what it greys out."""
        for ram in (4, 8, 12, 16, 20, 24, 31, 32, 48, 64, 128):
            v = self._view(ram)
            assert v["recommended"] not in v["disabled"]


# ═══════════════════════════════════════════════════════════════════════════
# CLI ≡ wizard — unified at 0.75 (product decision, 31/07), truncation removed.
#
# The two paths used to give different verdicts for the same machine (0.55 vs
# 0.75, int vs float). Both are gone: one fraction, one float comparison, and
# the CLI category thresholds recalibrated with it (5/20/28 → 7/27/38). What is
# guarded now is ALIGNMENT: any reintroduced literal, truncation or comparator
# drift must land in review, not in a user's install.
# Full history: the fraction comment in export_catalog_json.py.
# ═══════════════════════════════════════════════════════════════════════════


def _cli_verdict(ram_gb):
    from installer.installer_catalog import (
        usable_ram_gb, _determine_recommended_category, _resolve_category,
    )
    from installer.installer_catalog_data import MODEL_CATALOG

    usable = usable_ram_gb(ram_gb)
    choice, _ = _determine_recommended_category(usable)
    category, _ = _resolve_category(choice, choice)
    fits = [m["key"] for m in MODEL_CATALOG[category] if usable >= m["ram_gb"]]
    return usable, category, fits


class TestCliWizardAlignment:

    def test_fractions_unified_and_shared(self):
        """One value, one source. Mutation guard: put `int(ram * 0.55)` back in
        installer_catalog (or move either constant alone) and this goes RED."""
        from installer.export_catalog_json import (
            CLI_USABLE_FRACTION, WIZARD_USABLE_FRACTION,
        )
        from installer.installer_catalog import usable_ram_gb

        assert (CLI_USABLE_FRACTION, WIZARD_USABLE_FRACTION) == (0.75, 0.75)
        assert usable_ram_gb(100) == 100 * CLI_USABLE_FRACTION == 75.0

    def test_cli_no_longer_truncates(self):
        """The int() was the last divergence: it starved non-multiple-of-4
        machines (18 GB lost half a GB) and kept 6 GB dead (int(4.5)=4 < 4.1)."""
        from installer.installer_catalog import usable_ram_gb

        assert usable_ram_gb(24) == 18.0
        assert usable_ram_gb(32) == 24.0
        assert usable_ram_gb(18) == 13.5
        assert usable_ram_gb(6) == 4.5

    def test_cli_and_wizard_agree_on_every_model_at_every_ram(self):
        """The alignment tripwire, model by model over 2-256 GB: the CLI accepts
        a model iff the wizard would enable it. The CLI side goes through the
        real usable_ram_gb(); the wizard side through simulate_picker()'s own
        arithmetic — fraction drift, truncation or a comparator flip on either
        side breaks the equivalence somewhere in the sweep."""
        import json as _json
        from installer.export_catalog_json import simulate_picker
        from installer.installer_catalog import usable_ram_gb

        path = str(_json_path())
        data = _json.loads(_json_path().read_text(encoding="utf-8"))
        for ram in range(2, 257):
            view = simulate_picker(path, ram)
            usable = usable_ram_gb(ram)
            assert usable == view["usable_gb"], f"ram={ram}: fraccions divergents"
            for m in data.get(view["tier"], []):
                cli_accepts = usable >= m["ram_gb"]
                wizard_enables = m["key"] in view["enabled"]
                assert cli_accepts == wizard_enables, (
                    f"ram={ram} model={m['key']}: CLI={cli_accepts} "
                    f"wizard={wizard_enables}"
                )

    def test_the_fraction_guard_reaches_validate(self):
        """It must ride the CI path like the tier guard, not a new one.

        Mutation guard: drop _usable_fraction_errors() from validate() and this
        goes RED. (0.55 is the historical value someone could "restore".)"""
        import installer.export_catalog_json as ecj

        original = ecj.CLI_USABLE_FRACTION
        ecj.CLI_USABLE_FRACTION = 0.55  # somebody splits the two paths again
        try:
            errors = ecj.validate(str(_json_path()))
        finally:
            ecj.CLI_USABLE_FRACTION = original
        assert any("[RAM-FRACTION]" in e for e in errors), errors

    def test_no_machine_from_6gb_up_is_left_without_a_cli_model(self):
        """The dead range (a machine the wizard served but the CLI refused) is
        closed: at 6 GB, 6 × 0.75 = 4.5 ≥ 4.1. Swept over the dead range and
        every real Mac size. Below 6 GB the emptiness is physical (the smallest
        model needs 4.1 GB), not arithmetic — pinned as deliberate."""
        for ram in (6, 7, 8, 9, 16, 18, 24, 32, 36, 48, 64, 96, 128):
            _, category, fits = _cli_verdict(ram)
            assert fits, f"ram={ram} (categoria {category}): el CLI no ofereix cap model"
        for ram in (2, 3, 4, 5):
            _, _, fits = _cli_verdict(ram)
            assert not fits, f"ram={ram}: hauria de ser buit (cap model hi cap)"

    def test_exact_boundary_model_selectable_on_both_sides(self):
        """The zero-margin property, now shared: the CLI's `usable >= need`
        (inclusive) is the exact inverse of the wizard's strict `need > usable`
        (B171), so a model sitting exactly on the limit is selectable on BOTH
        paths. mistral_small_24b needs 18.0 on a 24 GB machine — 18.0 == 18.0."""
        from installer.export_catalog_json import simulate_picker
        from installer.installer_catalog import usable_ram_gb

        from installer.installer_catalog_data import MODEL_CATALOG

        assert usable_ram_gb(24) == 18.0
        view = simulate_picker(str(_json_path()), 24)
        assert "mistral_small_24b" in view["enabled"]
        # CLI side: the model lives in "large" (a category the user can pick
        # explicitly at any RAM); at exactly 18.0 usable it must fit.
        large_fits = [
            m["key"] for m in MODEL_CATALOG["large"]
            if usable_ram_gb(24) >= m["ram_gb"]
        ]
        assert "mistral_small_24b" in large_fits
