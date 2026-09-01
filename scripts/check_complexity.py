#!/usr/bin/env python3
"""Complexity gate — freeze the cyclomatic-complexity debt of the hot functions.

Companion to `check_layering.py`, same contract: this gate does NOT undo the
existing complexity, it FREEZES it. Every function at or above THRESHOLD is
recorded in the baseline with its current CCN; a function that grows, or a NEW
function that appears above the threshold, fails. So the debt cannot silently
grow the way it did between 2026-06-23 and 2026-08-20, when
`_generate_streaming_response` went 44 -> 66 (+50%) and `_handle_chat_engine`
41 -> 58 (+41%) across 21 legitimate commits, while the findings that had
tracked it (MC-026/MC-027) were already closed and nothing in the repo was
watching those numbers. Nobody could see it.

Why a hand-written counter instead of lizard: lizard is not a project
dependency, and this gate has to run in CI with nothing but the stdlib. The counter was calibrated against
lizard over all 2514 functions of this repo before being committed:
**2481 exact matches (98.7%)**, 33 divergent, only 3 of them in functions with
CCN >= 15. Every divergence is UPWARD — this counter never reports less than
lizard. The known cause is `and`/`or` inside f-strings, which we count as
decision points and lizard does not.

Re-calibrated 2026-08-27 over 2605 functions in 445 files: zero divergences
downward, 16 upward of 1-2 points, same known cause. The count went 2514 ->
2605 because that same measurement is what exposed finding #968 — the walk
that FINDS the functions was missing 43 of them, so they were never calibrated
against anything.

Known divergence, in our favour: lizard does not support `match` statements
(3.10+) and scores a `match` with N cases as 1; we count the cases. There are
zero `match` statements in production code today, so it changes nothing yet —
but the first one written will read higher here than under lizard, and this
gate is the one that is right.

Counting rule (McCabe): start at 1, then
  +1  If / IfExp / For / AsyncFor / While / ExceptHandler / Assert / match_case
  +1  Try that has a `finally` block
  +(n-1) for a BoolOp with n operands  (`a and b and c` = +2)
  +(1 + len(ifs)) per comprehension clause
Bodies of nested `def`s are NOT counted in their parent — they are reported as
their own entry, qualified (`parent.child`), exactly like lizard does. That
holds wherever the def is written, a `try` or an `if` included: see
`_iter_functions`, which is the part #968 got wrong. Lambdas
ARE counted in the enclosing function: neither this gate nor lizard gives them
an entry of their own, so skipping them would hide their decisions entirely.

SCOPE: Python production code only. JavaScript is NOT covered — `ui/app.js`
(`sendMessage` CCN 43, `processChunk` CCN 37) is known debt that this gate does
not see. A green run here does not mean the repo is clean.

The exclusion list is hardcoded and deliberately self-contained: a gate that
reads optional tool configuration stops working wherever that configuration is
absent. What it leaves out is everything that is not product code — virtualenvs
and caches, the pre-compiled `.app` bundles, tests, and `dev-tools/` (internal
tooling that ships to nobody).

Usage:
    python scripts/check_complexity.py            # check against baseline (CI)
    python scripts/check_complexity.py --update   # regenerate the baseline
    python scripts/check_complexity.py --list     # print every function >= threshold
    python scripts/check_complexity.py --baseline PATH   # use another baseline file

`--baseline` exists so the gate's own tests can exercise a tampered baseline in
a tmp dir instead of writing to the versioned one: a test that mutates a
tracked file leaves the repo dirty if it dies mid-run, and breaks outright
under parallel test execution.
"""
from __future__ import annotations

import ast
import json
import sys
from collections.abc import Iterator
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
BASELINE = Path(__file__).resolve().parent / "complexity_baseline.json"
THRESHOLD = 15  # above this, a function is considered in need of splitting

EXCLUDE_PARTS = {
    "venv", ".venv", ".test_venv", "node_modules", "__pycache__", "worktrees",
    "build", "dist", "tests", "dev-tools",
    "InstallNexe.app", "Nexe.app",   # pre-compiled bundles, not our source
    "diari", "specialists", "nexe",  # internal docs / QA tools, not product
    "storage", "uploads", "_tmp",
}

_DECISION_NODES = (
    ast.If, ast.IfExp, ast.For, ast.AsyncFor, ast.While,
    ast.ExceptHandler, ast.Assert, ast.match_case,
)
# Only def/async def are skipped: they are reported as their own entry. A lambda
# is NOT — neither here nor in lizard — so its body must count towards the
# enclosing function, or the decisions inside it vanish from both sides.
# Real case: `plugins/mlx_module/core/config.py::_model_path_autodiscover` is a
# bare `return discover_first_model(lambda p: p.is_dir() and ...)`; skipping the
# lambda made this gate report 1 where lizard reports 2.
_FUNCTION_NODES = (ast.FunctionDef, ast.AsyncFunctionDef)


def _ccn(fn: ast.AST) -> int:
    """McCabe complexity of one function, excluding nested function bodies."""
    total = 1

    def walk(node: ast.AST) -> None:
        nonlocal total
        for child in ast.iter_child_nodes(node):
            if isinstance(child, _FUNCTION_NODES):
                continue  # counted as its own entry
            if isinstance(child, _DECISION_NODES):
                total += 1
            elif isinstance(child, ast.BoolOp):
                total += len(child.values) - 1
            elif isinstance(child, ast.comprehension):
                total += 1 + len(child.ifs)
            elif isinstance(child, ast.Try) and child.finalbody:
                total += 1
            walk(child)

    walk(fn)
    return total


def _iter_functions(node: ast.AST, prefix: str = "") -> Iterator[tuple[str, ast.AST]]:
    """Every def in the tree, paired with its qualified name.

    Descends through EVERY node, not only defs and classes. A function defined
    inside an `if` / `try` / `with` / `for` is a function like any other, and
    until 2026-08-27 this walk never reached it: 43 of them were invisible to
    the gate (finding #968), and their decisions counted nowhere — not as an
    entry of their own, and not towards the parent, which skips nested bodies
    on purpose. This repo hits the case constantly because optional
    dependencies are guarded: the whole of `OllamaNode` lives inside a
    `try: import httpx`, and so does `NexeSettings`. None of the 43 was at or
    above the threshold when the hole was found (the highest was CCN 11) — but
    none of them would have failed the gate at CCN 40 either, which is the
    exact failure this gate exists to prevent.
    """
    for child in ast.iter_child_nodes(node):
        if isinstance(child, _FUNCTION_NODES):
            qualified = f"{prefix}{child.name}"
            yield qualified, child
            yield from _iter_functions(child, f"{qualified}.")
        elif isinstance(child, ast.ClassDef):
            yield from _iter_functions(child, f"{prefix}{child.name}.")
        else:
            yield from _iter_functions(child, prefix)


def _scan_tree(rel: str, tree: ast.AST, found: dict[str, int]) -> None:
    """Record every function of one parsed file at or above THRESHOLD.

    Split out of `_scan()` so discovery can be tested on a source string: what
    #968 broke is WHICH functions are found, and proving that from `_scan()`
    alone would mean writing a file into the repo for the gate to pick up.

    A duplicate key (a @property and its setter share a qualified name — there
    is exactly one such pair in this repo) keeps the higher of the two.
    """
    for qualified, fn in _iter_functions(tree):
        ccn = _ccn(fn)
        if ccn >= THRESHOLD:
            key = f"{rel}::{qualified}"
            found[key] = max(found.get(key, 0), ccn)


def _scan() -> dict[str, int]:
    """Every product function at or above THRESHOLD, keyed `path::Qualified.name`."""
    found: dict[str, int] = {}
    for path in sorted(ROOT.rglob("*.py")):
        rel_parts = path.relative_to(ROOT).parts
        if EXCLUDE_PARTS & set(rel_parts):
            continue
        try:
            tree = ast.parse(path.read_text(encoding="utf-8"))
        except (SyntaxError, UnicodeDecodeError):
            continue
        _scan_tree(path.relative_to(ROOT).as_posix(), tree, found)
    return found


def _report_failures(grown: list, appeared: list) -> None:
    print(f"COMPLEXITY GATE FAILED (threshold CCN {THRESHOLD}):")
    for key, was, now in grown:
        print(f"  ^ {key}: CCN {was} -> {now}")
    for key, ccn in appeared:
        print(f"  + {key}: CCN {ccn} (new function above the threshold)")
    print(
        "\nSplit the function into helpers that each stay under the threshold. "
        "If the growth is genuinely unavoidable, run "
        "`python scripts/check_complexity.py --update` and justify it in review — "
        "that is the decision this gate exists to make visible."
    )


def _report_improvements(current: dict[str, int], baseline: dict[str, int]) -> None:
    """Print what got better. Never fails the gate — only invites --update."""
    shrunk = sorted(
        (k, baseline[k], v) for k, v in current.items()
        if k in baseline and v < baseline[k]
    )
    gone = sorted(set(baseline) - set(current))
    for key, was, now in shrunk:
        print(f"OK (improved): {key}: CCN {was} -> {now}")
    for key in gone:
        print(f"OK (improved): {key}: now below CCN {THRESHOLD}")
    if shrunk or gone:
        print("Run `python scripts/check_complexity.py --update` to lock the improvement in.")


def _baseline_path() -> Path:
    """`--baseline PATH` wins over the default, for hermetic testing."""
    if "--baseline" in sys.argv:
        i = sys.argv.index("--baseline")
        if i + 1 < len(sys.argv):
            return Path(sys.argv[i + 1])
        print("ERROR: --baseline needs a path")
        raise SystemExit(2)
    return BASELINE


def main() -> int:
    baseline_file = _baseline_path()
    current = _scan()

    if "--list" in sys.argv:
        for key, ccn in sorted(current.items(), key=lambda kv: -kv[1]):
            print(f"  {ccn:4}  {key}")
        print(f"\n{len(current)} function(s) at or above CCN {THRESHOLD}")
        return 0

    if "--update" in sys.argv:
        baseline_file.write_text(
            json.dumps(dict(sorted(current.items())), indent=1) + "\n", encoding="utf-8"
        )
        print(f"baseline updated: {len(current)} function(s) >= CCN {THRESHOLD} -> {baseline_file.name}")
        return 0

    if not baseline_file.exists():
        print("ERROR: baseline missing. Run: python scripts/check_complexity.py --update")
        return 2

    baseline: dict[str, int] = json.loads(baseline_file.read_text(encoding="utf-8"))
    grown = sorted(
        (k, baseline[k], v) for k, v in current.items()
        if k in baseline and v > baseline[k]
    )
    appeared = sorted((k, v) for k, v in current.items() if k not in baseline)
    if grown or appeared:
        _report_failures(grown, appeared)
        return 1

    _report_improvements(current, baseline)
    print(f"complexity gate OK: {len(current)} function(s) >= CCN {THRESHOLD}, none grew.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
