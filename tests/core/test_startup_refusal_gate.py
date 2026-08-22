"""
Gate: no startup site may refuse to start without naming why.

The audit found the refusal logic spread over eight sites in five files with no
type and no common name — sys.exit here, RuntimeError there, ValueError over
there. Naming them once is worth little if the next site added skips the
register, so this gate reads the source and fails when one does.

It is deliberately narrow: only the files where startup actually refuses, and
only the two shapes that refuse (a hard exit, or a raise that aborts startup).
Widening it to every raise in core/ would produce false reds and get switched
off, which is worse than no gate.
"""

import ast
from pathlib import Path

import pytest

_ROOT = Path(__file__).resolve().parents[2]

# Files where a refusal is a real possibility, with the shapes that refuse.
_RAISING_STARTUP_FILES = {
    "core/lifespan.py": {"RuntimeError"},
    "core/server/factory.py": {"RuntimeError"},
    "core/server/factory_security.py": {"ValueError"},
}

_RECORDERS = {"record_refusal", "_refuse"}


def _functions(tree):
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            yield node


def _calls_a_recorder(func) -> bool:
    for node in ast.walk(func):
        if isinstance(node, ast.Call):
            name = getattr(node.func, "id", None) or getattr(node.func, "attr", None)
            if name in _RECORDERS:
                return True
    return False


def _raises(func, exception_names) -> bool:
    for node in ast.walk(func):
        if isinstance(node, ast.Raise) and isinstance(node.exc, ast.Call):
            if getattr(node.exc.func, "id", None) in exception_names:
                return True
    return False


def _is_hard_exit(node) -> bool:
    """sys.exit(1) — exit(0) is a clean stop, not a refusal."""
    if not isinstance(node, ast.Call):
        return False
    if getattr(node.func, "attr", None) != "exit":
        return False
    return bool(node.args) and getattr(node.args[0], "value", None) == 1


def test_every_hard_exit_in_the_runner_goes_through_the_register():
    """core/server/runner.py: five of the eight sites were the same cause said
    five ways. They now share one door — and only that door may exit."""
    path = _ROOT / "core/server/runner.py"
    tree = ast.parse(path.read_text())

    offenders = [
        func.name
        for func in _functions(tree)
        if func.name != "_refuse"
        and any(_is_hard_exit(n) for n in ast.walk(func))
    ]
    assert offenders == [], (
        "these functions exit(1) without going through _refuse(), so the server "
        f"refuses to start for a reason nothing can read: {offenders}"
    )


@pytest.mark.parametrize("relative_path", sorted(_RAISING_STARTUP_FILES))
def test_every_aborting_raise_names_its_reason(relative_path):
    exception_names = _RAISING_STARTUP_FILES[relative_path]
    tree = ast.parse((_ROOT / relative_path).read_text())

    offenders = [
        func.name
        for func in _functions(tree)
        if _raises(func, exception_names) and not _calls_a_recorder(func)
    ]
    assert offenders == [], (
        f"{relative_path}: these functions abort startup without recording a "
        f"RefusalReason: {offenders}"
    )


def test_the_gate_reads_something():
    """Negative control: an empty parse would make every assertion above pass
    in vain — the same trap as a glob that matches no files."""
    tree = ast.parse((_ROOT / "core/server/runner.py").read_text())
    exits = [n for n in ast.walk(tree) if _is_hard_exit(n)]
    assert exits, "the gate found no hard exit at all — it is not reading the file"
