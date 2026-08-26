"""
────────────────────────────────────
Server Nexe
Author: Jordi Goy
Location: tests/core/test_953_956_layering_gate_honesty.py
Description: #953 + #956 — the layering gate reported a number that was read as
            "the coupling debt" while ignoring every deferred cross-package
            import (measured 2026-08-26: 113 frozen vs 88 invisible), and its
            own failure hint sold the deferred import as the free way out.
            #956: --update could GROW the frozen baseline as a side effect,
            with human review as the only defence. Growth now needs a reason.

www.jgoy.net · https://server-nexe.org
────────────────────────────────────
"""
import ast
import importlib.util
import json
from pathlib import Path

import pytest

_REPO = Path(__file__).resolve().parents[2]
_SCRIPT = _REPO / "scripts" / "check_layering.py"


def _gate():
    """Load the gate by path — it is a script, not an importable module, and it
    deliberately does not run under pytest (that is how #941 broke CI green)."""
    spec = importlib.util.spec_from_file_location("_check_layering", _SCRIPT)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


class TestDeferredImportsAreCounted:
    """#953: not frozen is not the same as not there."""

    def test_deferred_collector_is_the_inverse_of_import_time(self):
        gate = _gate()
        src = (
            "from personality.data import models\n"          # import-time
            "def f():\n"
            "    from personality.events import event_system\n"  # deferred
        )
        tree = ast.parse(src)

        it = gate._ImportTimeCollector()
        it.visit(tree)
        assert it.modules == ["personality.data"]

        df = gate._DeferredCollector()
        df.visit(tree)
        assert df.modules == ["personality.events"], (
            "the deferred import must be seen by exactly one collector, not zero"
        )

    def test_type_checking_is_ignored_on_both_sides(self):
        """A type-only import is not runtime coupling, deferred or not (MC-102)."""
        gate = _gate()
        src = (
            "from typing import TYPE_CHECKING\n"
            "def f():\n"
            "    if TYPE_CHECKING:\n"
            "        from personality.data import models\n"
        )
        df = gate._DeferredCollector()
        df.visit(ast.parse(src))
        assert df.modules == []

    def test_the_repo_really_hides_coupling_behind_deferred_imports(self):
        """The measurement that motivated the finding, as a live anchor: the
        frozen number is NOT the whole debt. If this ever reaches zero the
        report line becomes noise and can go — it would mean the escape hatch
        is unused."""
        gate = _gate()
        assert len(gate._deferred_edges()) > 0, (
            "no deferred cross-package imports left — revisit the #953 report line"
        )


class TestBaselineGrowthNeedsAReason:
    """#956: shrinking is free, growing is a decision someone signs."""

    def test_reason_comes_from_flag_or_env(self, monkeypatch):
        gate = _gate()
        monkeypatch.delenv("NEXE_LAYERING_REASON", raising=False)

        monkeypatch.setattr(gate.sys, "argv", ["x", "--update"])
        assert gate._update_reason() == ""

        monkeypatch.setattr(gate.sys, "argv", ["x", "--update", "--reason", "  because  "])
        assert gate._update_reason() == "because", "must be stripped"

        monkeypatch.setattr(gate.sys, "argv", ["x", "--update"])
        monkeypatch.setenv("NEXE_LAYERING_REASON", "from CI")
        assert gate._update_reason() == "from CI"

    def test_dangling_reason_flag_is_not_a_reason(self, monkeypatch):
        """`--reason` with nothing after it must not count as a justification."""
        gate = _gate()
        monkeypatch.delenv("NEXE_LAYERING_REASON", raising=False)
        monkeypatch.setattr(gate.sys, "argv", ["x", "--update", "--reason"])
        assert gate._update_reason() == ""

    def test_update_refuses_to_grow_without_a_reason(self, monkeypatch, tmp_path, capsys):
        gate = _gate()
        baseline = tmp_path / "baseline.json"
        # A baseline missing one edge the code really has → --update would grow it.
        real = sorted(gate._edges())
        assert real, "the repo must have cross-package edges for this test to mean anything"
        baseline.write_text(json.dumps(real[1:]), encoding="utf-8")

        monkeypatch.setattr(gate, "BASELINE", baseline)
        monkeypatch.setattr(gate.sys, "argv", ["x", "--update"])
        monkeypatch.delenv("NEXE_LAYERING_REASON", raising=False)

        assert gate.main() == 2, "growth without a reason must fail, not pass"
        assert "REFUSED" in capsys.readouterr().out
        # And it must NOT have written anything.
        assert json.loads(baseline.read_text()) == real[1:]

    def test_update_grows_when_a_reason_is_given_and_records_it(
        self, monkeypatch, tmp_path, capsys
    ):
        gate = _gate()
        baseline = tmp_path / "baseline.json"
        real = sorted(gate._edges())
        baseline.write_text(json.dumps(real[1:]), encoding="utf-8")

        monkeypatch.setattr(gate, "BASELINE", baseline)
        monkeypatch.setattr(gate.sys, "argv", ["x", "--update", "--reason", "ADR-005 D-B"])
        monkeypatch.delenv("NEXE_LAYERING_REASON", raising=False)

        assert gate.main() == 0
        capsys.readouterr()
        written = json.loads(baseline.read_text())
        assert written["reason"] == "ADR-005 D-B", "the justification must survive in the file"
        assert set(written["edges"]) == set(real)

    def test_shrinking_needs_no_reason(self, monkeypatch, tmp_path):
        """Tightening is the good direction — never make it harder than growing."""
        gate = _gate()
        baseline = tmp_path / "baseline.json"
        real = sorted(gate._edges())
        baseline.write_text(
            json.dumps(real + ["core/gone.py -> memory.deleted"]), encoding="utf-8"
        )

        monkeypatch.setattr(gate, "BASELINE", baseline)
        monkeypatch.setattr(gate.sys, "argv", ["x", "--update"])
        monkeypatch.delenv("NEXE_LAYERING_REASON", raising=False)

        assert gate.main() == 0
        assert set(json.loads(baseline.read_text())["edges"]) == set(real)


class TestBaselineFormatCompatibility:
    """The historic baseline is a bare list; the new one carries the reason.
    Both must load, or a stale checkout fails CI for the wrong reason."""

    @pytest.mark.parametrize(
        "payload, expected",
        [
            (["a -> b"], {"a -> b"}),
            ({"edges": ["a -> b"], "reason": "x"}, {"a -> b"}),
            ({"edges": []}, set()),
        ],
    )
    def test_both_shapes_load(self, monkeypatch, tmp_path, payload, expected):
        gate = _gate()
        baseline = tmp_path / "baseline.json"
        baseline.write_text(json.dumps(payload), encoding="utf-8")
        monkeypatch.setattr(gate, "BASELINE", baseline)
        assert gate._load_baseline() == expected
