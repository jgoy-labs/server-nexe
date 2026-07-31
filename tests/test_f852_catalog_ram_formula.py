"""
────────────────────────────────────
Server Nexe
Author: Jordi Goy
Location: tests/test_f852_catalog_ram_formula.py
Description: #852 — the model recommenders lean on the catalog's ``ram_gb``, and
             four entries declared LESS RAM than the model's own weights plus
             the runtime floor (ALIA-40B: 42 GB of weights declared as 24 GB of
             RAM). Verified formula (23/07):

                 footprint = weights + kv_size × kv_per_tok + ~1.15 GB

             The catalog carries no kv_per_tok, so the gate below applies the
             formula with the KV term at zero: a hard floor that every entry
             must clear, never a full estimate.

www.jgoy.net · https://server-nexe.org
────────────────────────────────────
"""

import logging

import pytest

from installer.installer_catalog_data import MODEL_CATALOG, RUNTIME_FLOOR_GB, estimate_min_ram_gb


def _all_models():
    return [(tier, m) for tier, models in MODEL_CATALOG.items() for m in models]


class TestFormula:
    """The verified formula lives in ONE place, with the KV term explicit."""

    def test_floor_is_the_verified_constant(self):
        assert RUNTIME_FLOOR_GB == 1.15

    def test_weights_plus_floor_without_kv(self):
        assert estimate_min_ram_gb(17.0) == pytest.approx(18.15)

    def test_kv_term_is_added_when_known(self):
        # 4096 tokens × 128 KB/token = 0.5 GB
        got = estimate_min_ram_gb(2.9, kv_tokens=4096, kv_bytes_per_token=128 * 1024)
        assert got == pytest.approx(2.9 + 0.5 + 1.15)

    def test_kv_term_defaults_to_zero(self):
        """No kv_per_tok in the catalog → the floor stays a floor, not a guess."""
        assert estimate_min_ram_gb(6.6) == estimate_min_ram_gb(6.6, kv_tokens=8192)


class TestCatalogEntriesClearTheFloor:
    """#852 gate: a model may declare MORE RAM than the floor (its own margin),
    never less. Four entries did — including one off by 19 GB.

    Mutation guard: set any ram_gb back below disk_gb + 1.15 and this goes RED.
    """

    @pytest.mark.parametrize("tier,model", _all_models(), ids=lambda x: x if isinstance(x, str) else x.get("key", "?"))
    def test_ram_gb_clears_the_physical_floor(self, tier, model):
        floor = estimate_min_ram_gb(model["disk_gb"])
        assert model["ram_gb"] >= floor, (
            f"[{tier}/{model['key']}] declares ram_gb={model['ram_gb']} GB for "
            f"{model['disk_gb']} GB of weights — below the {floor:.2f} GB floor"
        )

    def test_the_four_historical_offenders_are_fixed(self):
        """Named so a regression is legible, not just a parametrized failure."""
        by_key = {m["key"]: m for _, m in _all_models()}
        for key in ("qwen35_4b", "salamandra7b", "gpt_oss_20b", "alia_40b"):
            m = by_key[key]
            assert m["ram_gb"] >= estimate_min_ram_gb(m["disk_gb"]), key


class TestHeadlessRamWarning:
    """#852: install_headless is the one recommender with NO RAM check at all
    (the CLI wizard and the Swift picker both read the machine's total RAM).
    It must warn — never block: the guard policy is warn (FD-S3)."""

    def _model(self, disk_gb=42.0, ram_gb=43.2, key="alia_40b"):
        return {"key": key, "name": "ALIA-40B", "disk_gb": disk_gb, "ram_gb": ram_gb}

    def test_warns_when_the_machine_is_too_small(self, caplog):
        from installer.install_headless import _warn_if_model_exceeds_ram

        with caplog.at_level(logging.WARNING):
            fits = _warn_if_model_exceeds_ram(self._model(), {"ram": 32})
        assert fits is False
        msgs = " ".join(r.getMessage() for r in caplog.records)
        assert "alia_40b" in msgs, msgs
        assert "43" in msgs and "32" in msgs, msgs

    def test_silent_when_the_model_fits(self, caplog):
        from installer.install_headless import _warn_if_model_exceeds_ram

        with caplog.at_level(logging.WARNING):
            fits = _warn_if_model_exceeds_ram(self._model(disk_gb=2.9, ram_gb=4.1,
                                                          key="qwen35_4b"), {"ram": 16})
        assert fits is True
        assert not caplog.records, caplog.text

    def test_no_model_selected_is_not_a_warning(self, caplog):
        """'Continue without model' must stay quiet."""
        from installer.install_headless import _warn_if_model_exceeds_ram

        with caplog.at_level(logging.WARNING):
            assert _warn_if_model_exceeds_ram(None, {"ram": 8}) is True
        assert not caplog.records

    def test_unknown_ram_does_not_warn(self, caplog):
        """A hardware probe that failed (ram=0) must not fabricate a verdict."""
        from installer.install_headless import _warn_if_model_exceeds_ram

        with caplog.at_level(logging.WARNING):
            assert _warn_if_model_exceeds_ram(self._model(), {"ram": 0}) is True
        assert not caplog.records

    def test_a_lying_catalog_entry_still_triggers_the_warning(self):
        """The floor must win over the declared number, not average with it.

        This is the historical ALIA-40B shape: 42 GB of weights advertised as
        24 GB of RAM. On a 32 GB machine the declared number says "fits" and
        the physics say it cannot. If the catalog ever regresses, the install
        must still warn.

        Mutation guard: `needed = declared` (drop the max() with the formula
        floor) and this goes RED — added after that exact mutant survived the
        first version of these tests.
        """
        from installer.install_headless import _warn_if_model_exceeds_ram

        lying = {"key": "alia_40b", "name": "ALIA-40B", "disk_gb": 42.0, "ram_gb": 24.0}
        assert _warn_if_model_exceeds_ram(lying, {"ram": 32}) is False

    def test_the_check_is_wired_into_the_headless_run(self):
        """Anti-theatre: the helper above could pass forever while the
        installer stopped calling it. Pinning the call site is a source guard,
        not a behavioural test — driving _run_headless_inner would run a real
        install (venv, downloads).

        Mutation guard: delete the call in _run_headless_inner and this goes RED.
        """
        import inspect
        from installer import install_headless

        src = inspect.getsource(install_headless._run_headless_inner)
        assert "_warn_if_model_exceeds_ram(" in src

    def test_verdict_comes_from_the_passed_total_ram_only(self, monkeypatch):
        """lesson-guard-ram-available-no-prediu-si-funciona: the verdict must
        come from the machine's TOTAL RAM (detect_hardware → sysctl
        hw.memsize), never from momentarily-available RAM.

        Behavioural, not a source grep: psutil is booby-trapped, so a helper
        that reached for the available RAM would raise instead of answering.

        Mutation guard: read psutil.virtual_memory().available (or
        .total - .used) in the helper and this goes RED.
        """
        import psutil
        from installer.install_headless import _warn_if_model_exceeds_ram

        def _boom(*a, **kw):
            raise AssertionError("the RAM check must not consult live memory")

        monkeypatch.setattr(psutil, "virtual_memory", _boom)

        # Same model, two machines: only the number handed in decides.
        assert _warn_if_model_exceeds_ram(self._model(), {"ram": 64}) is True
        assert _warn_if_model_exceeds_ram(self._model(), {"ram": 32}) is False
