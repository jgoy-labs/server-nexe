"""I1's second line: no step asks which door it is (ADR-007 §1, C4.0).

`test_i1_one_sequence.py::test_entry_is_a_label_not_a_switch` is the invariant
— it is behavioural, which is what the ADR demands. This is the convenience:
it says WHERE, with file:line, instead of "the two runs differ", which is much
more expensive to debug.

**AST, not grep**, for two reasons, both measured by running the two tools
against the same source rather than reasoned about:

* a door literal inside a DOCSTRING is prose, not a branch. A grep marks it,
  the parser sees a string constant and moves on. The repo has one today
  (`tests/core/memory_facts/test_intents.py:392`) — outside this lint's scope,
  since nothing under `tests/` is scanned, so it is an example of the hazard
  rather than a case this test files. Verified INSIDE the scope by putting such
  a docstring in `core/turn/policy.py`: grep flags it, this lint stays green.
* a comparison split across two lines is invisible to a line-oriented grep and
  perfectly visible to a parser — checked the same way, in the same file.

Scope: the modules that must be door-blind — the turn engine, the memory brain
and the UI door's adapter table (an adapter may READ `ctx.entry` to label a
lease or a trace; what it may not do is branch the turn on it). Directories
listed here that do not exist yet are skipped: `core/files/` is created by
C4.3, and this test should not have to be edited on the day it appears.
"""
from __future__ import annotations

import ast
from pathlib import Path

#: The repo root: tests/core/turn/<this file> → three levels up.
REPO_ROOT = Path(__file__).resolve().parents[3]

#: Where a door literal is forbidden. Trees are walked recursively; a plain
#: file is checked on its own. Anything absent is skipped (see the docstring).
SCANNED = (
    "core/turn",
    "core/memory_facts",
    "core/files",  # C4.3 creates it; absent at C4.0
    "plugins/web_ui_module/api/turn_adapters.py",
)

#: The door names. A comparison against any other constant is not I1's business.
DOOR_NAMES = frozenset({"ui", "api"})


def _is_entry(node: ast.AST) -> bool:
    """`ctx.entry` (any owner) or a bare `entry`."""
    if isinstance(node, ast.Attribute):
        return node.attr == "entry"
    return isinstance(node, ast.Name) and node.id == "entry"


def _is_door_constant(node: ast.AST) -> bool:
    """A `"ui"`/`"api"` literal, or a container of them (`in {"ui", "api"}`)."""
    if isinstance(node, ast.Constant):
        return node.value in DOOR_NAMES
    if isinstance(node, (ast.Tuple, ast.List, ast.Set)):
        return bool(node.elts) and all(_is_door_constant(elt) for elt in node.elts)
    return False


def _door_comparisons(tree: ast.AST, path: Path) -> list[str]:
    """Every `entry ==/!=/in <door>` comparison in `tree`, as file:line strings.

    Both sides are checked in both directions: `ctx.entry == "ui"` and
    `"ui" == ctx.entry` are the same branch written two ways. `in`/`not in`
    only counts with `entry` on the left — `"ui" in something_else` is not a
    door switch, and `entry in <container>` is.
    """
    found: list[str] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Compare):
            continue
        # A chained comparison (`a == b == c`) is n operators over n+1
        # operands; pairing them this way covers the chain as well as the
        # ordinary two-operand case.
        operands = [node.left, *node.comparators]
        for index, op in enumerate(node.ops):
            left, right = operands[index], operands[index + 1]
            if isinstance(op, (ast.Eq, ast.NotEq)):
                hit = (_is_entry(left) and _is_door_constant(right)) or (
                    _is_entry(right) and _is_door_constant(left)
                )
            elif isinstance(op, (ast.In, ast.NotIn)):
                hit = _is_entry(left) and _is_door_constant(right)
            else:
                hit = False
            if hit:
                found.append(f"{path.relative_to(REPO_ROOT)}:{node.lineno}")
                break
    return found


def _python_files() -> list[Path]:
    files: list[Path] = []
    for entry in SCANNED:
        target = REPO_ROOT / entry
        if not target.exists():
            continue
        if target.is_dir():
            files.extend(sorted(p for p in target.rglob("*.py") if "__pycache__" not in p.parts))
        else:
            files.append(target)
    return files


#: What `SCANNED` must be. Frozen on purpose, and not as a count
#: (`len(SCANNED) >= 4` consents to swapping `core/memory_facts` for anything
#: else): the guard below iterates `SCANNED`, so it cannot see an entry that has
#: been DELETED from it — removing `core/memory_facts` shrinks the lint from 23
#: files to 9 in silence (measured, audit 08/09). Naming the expected scope here
#: means widening or narrowing it takes a deliberate edit in two places, the
#: same shape as `FOLDED_BASELINE` versus each door's own folded list.
EXPECTED_SCOPE = (
    "core/turn",
    "core/memory_facts",
    "core/files",
    "plugins/web_ui_module/api/turn_adapters.py",
)


def test_the_scanned_scope_is_the_one_this_lint_promises():
    """Nobody narrows I1's blind spot by editing a tuple."""
    assert SCANNED == EXPECTED_SCOPE, (
        "the I1 lint's scope changed. Widening it is welcome — update "
        "EXPECTED_SCOPE in the same commit and say why; narrowing it needs a "
        f"reason in the commit message.\n  now:      {SCANNED}\n  expected: {EXPECTED_SCOPE}"
    )


def test_every_scanned_entry_that_exists_contributes_a_file():
    """A lint over an empty file list is a green test about nothing — the exact
    failure mode a renamed or moved package would cause silently.

    Asserted per ENTRY, not as a total: a floor on the count (this used to be
    `>= 15` against a real 23) leaves room for a whole package of `SCANNED` to
    vanish without a word. `core/files/` is the one entry allowed to contribute
    nothing, because it does not exist until C4.3 — and the moment it does, it
    is covered like the rest with no edit here.
    """
    for entry in SCANNED:
        target = REPO_ROOT / entry
        if not target.exists():
            assert entry == "core/files", (
                f"{entry} is in SCANNED but does not exist — the I1 lint is "
                "silently skipping it (renamed? moved?)"
            )
            continue
        found = [p for p in _python_files() if p == target or target in p.parents]
        assert found, f"{entry} exists but contributed no Python file to the I1 lint"

    names = {p.name for p in _python_files()}
    assert {"run.py", "steps.py", "adapters_api.py", "turn_adapters.py"} <= names, sorted(names)


def test_no_step_asks_which_door_it_is():
    """No module of the turn branches on the name of the door."""
    offenders: list[str] = []
    for path in _python_files():
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        offenders.extend(_door_comparisons(tree, path))
    assert not offenders, (
        "I1 (ADR-007 §1): the door is a label, not a switch — these compare "
        "`entry` against a door name:\n  " + "\n  ".join(offenders)
    )
