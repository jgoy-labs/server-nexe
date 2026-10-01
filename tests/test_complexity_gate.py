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
import importlib.util
import json
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
SCRIPT = ROOT / "scripts" / "check_complexity.py"
BASELINE = ROOT / "scripts" / "complexity_baseline.json"


def _gate_module():
    """Load the gate as a module, to exercise its internals directly."""
    spec = importlib.util.spec_from_file_location("_cc_gate", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


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


class TestDiscovery:
    """WHICH functions the gate can see — the other half of the counter.

    Finding #968: the walk recursed only into defs and classes, so a def
    written inside an `if` / `try` / `with` / `for` was never reached. 43 of
    them in this repo, every method of `OllamaNode` and of `NexeSettings`
    among them, because both classes live inside a `try: import ...` guard for
    an optional dependency. They counted NOWHERE — not as an entry of their
    own, and not towards the parent, which skips nested bodies on purpose.
    None of the 43 was above the threshold the day it was found (highest CCN
    11), but none would have failed the gate at CCN 40 either.

    What `_scan_tree` records is what `main()` compares against the baseline,
    so "recorded here" is "can fail the gate there" —
    `test_a_new_function_above_the_threshold_fails_the_gate` closes that half.
    """

    @staticmethod
    def _names(source: str) -> set[str]:
        return {q for q, _ in _gate_module()._iter_functions(ast.parse(source))}

    @staticmethod
    def _scanned(source: str) -> dict[str, int]:
        found: dict[str, int] = {}
        _gate_module()._scan_tree("fake.py", ast.parse(source), found)
        return found

    def test_a_function_inside_a_try_is_found(self) -> None:
        src = (
            "try:\n"
            "    import httpx\n"
            "    def guarded():\n"
            "        return httpx\n"
            "except ImportError:\n"
            "    guarded = None\n"
        )
        assert "guarded" in self._names(src)

    @pytest.mark.parametrize(
        "header",
        [
            "if TYPE_CHECKING:",
            "with suppress(ImportError):",
            "for _ in range(1):",
            "while True:",
        ],
    )
    def test_a_function_inside_any_block_is_found(self, header: str) -> None:
        assert "buried" in self._names(f"{header}\n    def buried():\n        pass\n")

    def test_a_method_of_a_class_inside_a_try_keeps_its_qualified_name(self) -> None:
        # The real shape of plugins/ollama_module/.../ollama_node.py.
        src = (
            "try:\n"
            "    class Node:\n"
            "        def execute(self):\n"
            "            pass\n"
            "except ImportError:\n"
            "    Node = None\n"
        )
        assert "Node.execute" in self._names(src)

    def test_a_complex_function_inside_a_try_reaches_the_baseline(self) -> None:
        """The regression #968 asks for: buried debt must be recordable."""
        body = "".join(
            f"        if x == {i}:\n            return {i}\n" for i in range(16)
        )
        src = f"try:\n    def guarded(x):\n{body}        return None\nexcept ImportError:\n    guarded = None\n"

        found = self._scanned(src)

        assert found.get("fake.py::guarded") == 17, (
            "a CCN 17 function inside a try must be recorded — before #968 it "
            "was invisible and could have grown to any value unseen"
        )

    def test_a_def_inside_a_try_does_not_count_towards_its_parent(self) -> None:
        # Discovery and counting have to agree: now that the buried def gets an
        # entry of its own, its decisions must NOT also land on the parent.
        module = _gate_module()
        src = (
            "def outer(x):\n"
            "    try:\n"
            "        def inner(y):\n"
            "            if y:\n"
            "                return 1\n"
            "            return 0\n"
            "    except ImportError:\n"
            "        inner = None\n"
            "    return inner\n"
        )
        outer = ast.parse(src).body[0]

        assert module._ccn(outer) == 2, "1 + the except handler, not the inner if"
        assert self._names(src) == {"outer", "outer.inner"}

    def test_the_gate_can_see_itself(self) -> None:
        # `_scan.visit` was on the invisible list: the gate did not measure its
        # own walk. It is module-level now, so this asserts the shape stays.
        assert "_iter_functions" in self._names(SCRIPT.read_text(encoding="utf-8"))

    def test_the_real_ollama_node_case_is_visible(self) -> None:
        path = ROOT / "plugins/ollama_module/workflow/nodes/ollama_node.py"
        if not path.exists():  # pragma: no cover - the file moved, not a gate bug
            pytest.skip("ollama_node.py moved; the #968 case is covered by the unit tests above")
        names = self._names(path.read_text(encoding="utf-8"))
        assert "OllamaNode._execute_streaming" in names, (
            "the whole class is inside `try: import httpx` — this is the real "
            "case that made #968 worth fixing"
        )


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
        # C4.6: the canary was `routes_chat.py::_generate_streaming_response`,
        # deleted with the Continue path's legacy body.
        key = "core/endpoints/installer_gguf.py::_stream_gguf"
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
