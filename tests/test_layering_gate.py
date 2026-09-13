"""
────────────────────────────────────
Server Nexe
Author: Jordi Goy
Location: tests/test_layering_gate.py
Description: The layering freeze must run on every `pytest`, not only in its
             own CI job and not only when someone remembers the script.

             Why this test exists: on 2026-09-06, C1.3 added four import-time
             cross-package edges and `scripts/check_layering.py` went red —
             while the suite stayed green at 8724 passed, because nothing
             under tests/ compared the real edges against the VERSIONED
             baseline. The edges were caught by running the script by hand.
             The same shape had already been noted on 2026-09-04: a branch
             sitting at 8633 passed with the gate in the red.

             Its sibling `tests/test_complexity_gate.py` has had that mirror
             since #1007. This is the same contract for the other gate.

             The gate's internals — the collectors, TYPE_CHECKING, `--update`
             needing a reason, the per-edge `reasons` — are covered by
             tests/core/test_953_956_layering_gate_honesty.py and
             tests/core/test_mc102_103_layering.py. What was missing, and what
             lives here, is the gate AS A WHOLE: that it passes on this repo,
             and that it actually BITES when it should. Both failure paths of
             `main()` — a new frozen edge, and the D-M door (plugins → memory)
             — had never been executed by any test: only the collectors under
             them had.

www.jgoy.net · https://server-nexe.org
────────────────────────────────────
"""
from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
SCRIPT_REL = "scripts/check_layering.py"
SCRIPT = ROOT / SCRIPT_REL
BASELINE = ROOT / "scripts" / "layering_baseline.json"
CI = ROOT / ".github" / "workflows" / "ci.yml"


def _gate():
    """Load the gate by path — it is a script, not an importable module."""
    spec = importlib.util.spec_from_file_location("_layering_gate", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _run(*args: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, str(SCRIPT), *args],
        capture_output=True, text=True, cwd=str(ROOT),
    )


def _fake_repo(tmp_path: Path, files: dict[str, str], baseline: object = ()) -> tuple[Path, Path]:
    """A miniature repo the gate can walk, plus its baseline file.

    Pointing the gate at a tree of our own is what lets the failure paths run
    for real — detector included — instead of being mocked out. Writing to the
    versioned baseline instead would leave the repo dirty if a test died
    mid-run, and would race under parallel execution.
    """
    for rel, src in files.items():
        path = tmp_path / "repo" / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(src, encoding="utf-8")
    baseline_path = tmp_path / "layering_baseline.json"
    baseline_path.write_text(json.dumps(baseline if baseline != () else []), encoding="utf-8")
    return tmp_path / "repo", baseline_path


def _point_gate_at(monkeypatch, gate, root: Path, baseline: Path) -> None:
    monkeypatch.setattr(gate, "ROOT", root)
    monkeypatch.setattr(gate, "BASELINE", baseline)
    # `main()` reads sys.argv directly; under pytest that is pytest's own
    # command line, and a stray `--update` in it would silently turn a check
    # into a write.
    monkeypatch.setattr(gate.sys, "argv", ["check_layering.py"])


class TestGateRuns:
    """The half that was missing: the real repo, measured against the file
    that is actually committed."""

    def test_the_repo_is_within_the_frozen_layering_baseline(self) -> None:
        """A failure here means a new import-time cross-package import was
        added — freeze it with `--update --reason "..."`, or route it through
        a port. This is the assert that C1.3 did not have."""
        result = _run()
        assert result.returncode == 0, (
            f"layering gate failed:\n{result.stdout}\n{result.stderr}"
        )

    def test_the_versioned_baseline_is_well_formed(self) -> None:
        data = json.loads(BASELINE.read_text(encoding="utf-8"))
        assert isinstance(data, dict), "the current shape is an object, not a bare list"
        edges = data["edges"]
        assert edges, "the baseline must not be empty"
        assert all(" -> " in edge for edge in edges), "entries are 'path -> module'"
        assert edges == sorted(edges), "the gate writes them sorted; a hand edit did not"
        assert len(edges) == len(set(edges)), "a duplicated edge hides a second one"

    def test_no_reason_is_left_behind_by_an_edge_that_is_gone(self) -> None:
        """`_write_baseline` drops the reason of an edge that leaves the
        baseline. A stray key means someone hand-edited `edges` and left the
        justification of something that is no longer frozen."""
        data = json.loads(BASELINE.read_text(encoding="utf-8"))
        edges = set(data["edges"])
        stray = [k for k in data.get("reasons", {}) if k != "_legacy" and k not in edges]
        assert not stray, f"reasons for edges that are not in the baseline: {stray}"


class TestGateActuallyBites:
    """A gate nobody has watched fail is not a gate.

    Each case pairs the shape that must fail with the legitimate twin that must
    NOT — a gate that blocks everything is as useless as one that blocks
    nothing.
    """

    def test_a_new_import_time_cross_package_edge_fails_the_gate(
        self, monkeypatch, tmp_path, capsys
    ) -> None:
        gate = _gate()
        root, baseline = _fake_repo(
            tmp_path, {"core/newcomer.py": "from personality.data import models\n"}
        )
        _point_gate_at(monkeypatch, gate, root, baseline)

        assert gate.main() == 1, "a module-level cross-package import must fail the freeze"
        out = capsys.readouterr().out
        assert "LAYERING GATE FAILED" in out
        assert "core/newcomer.py -> personality.data" in out, (
            "the report must name the offending edge, or nobody can act on it"
        )

    def test_the_same_import_deferred_does_not_fail_the_gate(
        self, monkeypatch, tmp_path, capsys
    ) -> None:
        """The sanctioned escape hatch: coupling, but not frozen coupling —
        and it must still be COUNTED in the report (#953)."""
        gate = _gate()
        root, baseline = _fake_repo(
            tmp_path,
            {"core/newcomer.py": "def f():\n    from personality.data import models\n    return models\n"},
        )
        _point_gate_at(monkeypatch, gate, root, baseline)

        assert gate.main() == 0, "a function-local import is not frozen"
        out = capsys.readouterr().out
        assert "not frozen: 1 deferred" in out, (
            "the deferred edge must be reported, or the frozen number reads as the whole debt"
        )

    def test_a_plugin_reaching_into_memory_fails_the_gate_even_when_deferred(
        self, monkeypatch, tmp_path, capsys
    ) -> None:
        """D-M / #875. The whole point of this rule is that hiding the import
        inside a function does NOT buy you the exception it buys everywhere
        else — which is exactly the path no test had ever run."""
        gate = _gate()
        root, baseline = _fake_repo(
            tmp_path,
            {"plugins/rogue/thing.py":
             "def f():\n    from memory.memory.api import MemoryAPI\n    return MemoryAPI\n"},
        )
        _point_gate_at(monkeypatch, gate, root, baseline)

        assert gate.main() == 1, "plugins → memory must fail, deferred or not"
        out = capsys.readouterr().out
        assert "D-M" in out and "#875" in out
        assert "plugins/rogue/thing.py -> memory.memory.api" in out
        assert "core.memory_access" in out, "the report must point at the porter"

    def test_a_plugin_going_through_the_porter_is_allowed(
        self, monkeypatch, tmp_path
    ) -> None:
        """The legitimate twin of the case above: same plugin, same need, via
        `core.memory_access`. If this ever goes red the rule has stopped being
        a door and started being a wall."""
        gate = _gate()
        root, baseline = _fake_repo(
            tmp_path,
            {"plugins/wellbehaved/thing.py":
             "def f():\n    from core.memory_access import get_memory_view\n    return get_memory_view()\n"},
        )
        _point_gate_at(monkeypatch, gate, root, baseline)

        assert gate.main() == 0, "the porter is the sanctioned way in"

    def test_a_missing_baseline_is_an_error_not_a_pass(
        self, monkeypatch, tmp_path, capsys
    ) -> None:
        """Exit 2, never 0: a gate that cannot find its baseline must not
        report success — that is how a freeze silently stops freezing."""
        gate = _gate()
        root, baseline = _fake_repo(tmp_path, {"core/a.py": "import os\n"})
        baseline.unlink()
        _point_gate_at(monkeypatch, gate, root, baseline)

        assert gate.main() == 2
        assert "baseline missing" in capsys.readouterr().out

    def test_the_versioned_baseline_is_never_written_by_these_tests(self) -> None:
        """The point of the fake tree: the tracked file comes out untouched.

        Deliberately says nothing about the return code — a red gate is the
        business of the test above, and a check that fails for someone else's
        reason is noise exactly when the report needs to be readable."""
        before = BASELINE.read_bytes()
        _run()
        assert BASELINE.read_bytes() == before


class TestBothDoorsAgree:
    """The pytest mirror is a second door, not a replacement. The gate keeps
    its own CI job (which is what the complexity gate lacked in #1007); this
    test is what makes the freeze show up on a developer's machine too."""

    def test_a_ci_job_runs_the_same_script_this_mirror_runs(self) -> None:
        config = yaml.safe_load(CI.read_text(encoding="utf-8")) or {}
        runners = {
            job_id
            for job_id, job in (config.get("jobs") or {}).items()
            for step in (job.get("steps") or [])
            if SCRIPT_REL in str(step.get("run", ""))
        }
        assert runners, (
            f"no CI job runs `{SCRIPT_REL}`. With the standalone job gone, this "
            "pytest mirror is the only path left — say so here before removing it."
        )
