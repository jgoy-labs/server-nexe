# -*- coding: utf-8 -*-
"""The complexity gate must run on every `pytest`, not only when someone
remembers to call the script.

Why this test exists: between 2026-06-23 and 2026-08-20,
`_generate_streaming_response` went from CCN 44 to 66 and `_handle_chat_engine`
from 41 to 58 across 21 legitimate commits. Both were closed findings
(MC-026/MC-027) and no check anywhere was watching those numbers, so nothing
said a word. `scripts/check_complexity.py` freezes those
numbers; this test is what makes the freeze show up in the local run and in CI
(inside the existing `tests` job) instead of waiting for an audit.

See `scripts/check_complexity.py` for the counting rule and for its calibration
against lizard (2429/2456 functions exact, never below lizard).
"""
import ast
import json
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
SCRIPT = ROOT / "scripts" / "check_complexity.py"
BASELINE = ROOT / "scripts" / "complexity_baseline.json"


def _run(*args: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, str(SCRIPT), *args],
        capture_output=True, text=True, cwd=str(ROOT),
    )


class TestGateRuns:
    def test_repo_is_within_the_frozen_complexity_baseline(self) -> None:
        """The gate itself. A failure here means a function above CCN 15 grew,
        or a new one appeared — split it, or `--update` and justify it."""
        result = _run()
        assert result.returncode == 0, (
            f"complexity gate failed:\n{result.stdout}\n{result.stderr}"
        )

    def test_baseline_is_present_and_well_formed(self) -> None:
        data = json.loads(BASELINE.read_text(encoding="utf-8"))
        assert data, "the baseline must not be empty"
        assert all(isinstance(k, str) and "::" in k for k in data), (
            "keys are 'path::Qualified.name'"
        )
        assert all(isinstance(v, int) and v >= 15 for v in data.values()), (
            "the baseline only records functions at or above the threshold"
        )


class TestCounter:
    """The counter is the load-bearing part: if it under-counts, the gate lets
    complexity through. These are the cases that made it wrong while it was
    being written."""

    @staticmethod
    def _ccn_of(source: str) -> int:
        spec = __import__("importlib.util", fromlist=["util"]).spec_from_file_location(
            "_cc_gate", SCRIPT
        )
        module = __import__("importlib.util", fromlist=["util"]).module_from_spec(spec)
        spec.loader.exec_module(module)
        fn = ast.parse(source).body[0]
        return module._ccn(fn)

    def test_straight_line_function_is_one(self) -> None:
        assert self._ccn_of("def f():\n    return 1\n") == 1

    def test_boolop_counts_each_extra_operand(self) -> None:
        # `a and b and c` is two decisions, not one.
        assert self._ccn_of("def f(a, b, c):\n    return a and b and c\n") == 3

    def test_try_finally_counts(self) -> None:
        # lizard counts the finally; without this the gate drifts below it on
        # every function that cleans up after itself.
        src = "def f():\n    try:\n        g()\n    finally:\n        h()\n"
        assert self._ccn_of(src) == 2

    def test_lambda_body_counts_towards_the_enclosing_function(self) -> None:
        # A lambda gets no entry of its own — not here and not in lizard — so
        # its decisions must land on the parent or they vanish. Real case:
        # plugins/mlx_module/core/config.py::_model_path_autodiscover.
        src = "def f(xs):\n    return g(lambda p: p.a and p.b)\n"
        assert self._ccn_of(src) == 2

    def test_nested_def_body_does_not_count_towards_the_parent(self) -> None:
        # A nested def IS reported separately (qualified), so counting it twice
        # would inflate the parent.
        src = (
            "def outer():\n"
            "    def inner(x):\n"
            "        if x:\n"
            "            return 1\n"
            "        return 0\n"
            "    return inner\n"
        )
        assert self._ccn_of(src) == 1

    def test_comprehension_with_filter_counts_both(self) -> None:
        assert self._ccn_of("def f(xs):\n    return [x for x in xs if x]\n") == 3


class TestGateActuallyBites:
    """A gate nobody has watched fail is not a gate.

    Both cases tamper with a COPY in tmp_path and point the script at it with
    `--baseline`. Writing to the versioned baseline would leave the repo dirty
    if a test died mid-run, and would race under parallel execution.
    """

    @staticmethod
    def _tampered(tmp_path: Path, mutate) -> Path:
        baseline = json.loads(BASELINE.read_text(encoding="utf-8"))
        mutate(baseline)
        path = tmp_path / "complexity_baseline.json"
        path.write_text(json.dumps(baseline, indent=1) + "\n", encoding="utf-8")
        return path

    def test_a_function_that_grows_fails_the_gate(self, tmp_path: Path) -> None:
        key = "plugins/web_ui_module/api/routes_chat.py::_generate_streaming_response"
        assert key in json.loads(BASELINE.read_text(encoding="utf-8")), (
            "the canary function must be in the baseline"
        )
        # Lower its recorded value by one and the current code reads as grown —
        # the same effect as someone adding an `if` to the real function.
        path = self._tampered(tmp_path, lambda b: b.__setitem__(key, b[key] - 1))

        result = _run("--baseline", str(path))
        assert result.returncode == 1, "the gate must fail when a function grows"
        assert key in result.stdout
        assert "COMPLEXITY GATE FAILED" in result.stdout

    def test_a_new_function_above_the_threshold_fails_the_gate(self, tmp_path: Path) -> None:
        key = "core/lifespan.py::_startup_init"
        assert key in json.loads(BASELINE.read_text(encoding="utf-8"))
        path = self._tampered(tmp_path, lambda b: b.pop(key))

        result = _run("--baseline", str(path))
        assert result.returncode == 1
        assert "new function above the threshold" in result.stdout

    def test_the_versioned_baseline_is_never_written_by_these_tests(self) -> None:
        # The point of --baseline: the tracked file comes out untouched.
        assert _run().returncode == 0


@pytest.mark.parametrize("flag", ["--list"])
def test_read_only_flags_do_not_touch_the_baseline(flag: str) -> None:
    before = BASELINE.read_bytes()
    assert _run(flag).returncode == 0
    assert BASELINE.read_bytes() == before
