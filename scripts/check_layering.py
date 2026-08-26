#!/usr/bin/env python3
"""Layering gate (finding #471) — freeze the inter-package coupling debt.

server-nexe's four top packages (core, memory, personality, plugins) form a
fully-connected import graph. The verification (2026-06-19) confirmed there are
NO real import-time cycles (deferred imports break them) — so this is a
maintainability concern (P3), not a runtime bug. This gate does NOT try to undo
the existing coupling; it FREEZES it: any NEW import-time (module-level) cross-
package import that is not already in the baseline fails CI, so the debt cannot
silently grow.

Only IMPORT-TIME imports are considered for the freeze: imports at module scope
(incl. top-level try/if blocks), NOT imports nested inside functions/methods.
Deferred (function-local) imports are the legitimate escape hatch between core,
memory and personality, and are ignored by the freeze.

Exception (D-M / #875): plugins/ must not import memory/ at all — import-time
OR deferred. The porter is `core.memory_access.get_memory_view`. A function-local
`from memory...` inside a plugin is the shortcut this gate exists to close.

`if TYPE_CHECKING:` blocks are ignored in both checks — they never execute at
runtime, so a type-only import there is not runtime coupling (MC-102).

Deferred imports are NOT free (#953). They are the sanctioned escape hatch, but
they cross the same boundaries, so the report prints them next to the frozen
count — the baseline number alone must never be read as the total coupling debt.

Growing the baseline is a decision, not a side effect (#956): `--update` refuses
to ADD edges without a stated reason, which is recorded in the baseline file.
Shrinking it (tightening) needs no reason.

Usage:
    python scripts/check_layering.py                      # check against baseline (CI)
    python scripts/check_layering.py --update             # tighten (shrink) the baseline
    python scripts/check_layering.py --update --reason "" # grow it, with justification
"""
from __future__ import annotations

import ast
import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PACKAGES = ("core", "memory", "personality", "plugins")
EXCLUDE_PARTS = {"venv", ".venv", "node_modules", "__pycache__", "worktrees",
                 "tests", "dev-tools", "build", "dist"}
BASELINE = Path(__file__).resolve().parent / "layering_baseline.json"


def _top_pkg(module: str | None) -> str | None:
    return module.split(".")[0] if module else None


class _ImportTimeCollector(ast.NodeVisitor):
    """Collect module-level (import-time) imports; skip function/method bodies."""

    def __init__(self) -> None:
        self.modules: list[str] = []
        self._fn_depth = 0

    def visit_FunctionDef(self, node: ast.FunctionDef) -> None:
        self._fn_depth += 1
        self.generic_visit(node)
        self._fn_depth -= 1

    visit_AsyncFunctionDef = visit_FunctionDef  # type: ignore[assignment]

    def visit_Import(self, node: ast.Import) -> None:
        if self._fn_depth == 0:
            for alias in node.names:
                self.modules.append(alias.name)

    def visit_ImportFrom(self, node: ast.ImportFrom) -> None:
        if self._fn_depth == 0 and node.level == 0 and node.module:
            self.modules.append(node.module)

    def visit_If(self, node: ast.If) -> None:
        # `if TYPE_CHECKING:` blocks NEVER execute at runtime — their imports are
        # type-only and create no runtime coupling, so they must not count as an
        # import-time edge. Skip the whole block (body + orelse).
        if self._is_type_checking(node.test):
            return
        self.generic_visit(node)

    @staticmethod
    def _is_type_checking(test: ast.expr) -> bool:
        # matches `TYPE_CHECKING` and `typing.TYPE_CHECKING`
        return (
            (isinstance(test, ast.Name) and test.id == "TYPE_CHECKING")
            or (isinstance(test, ast.Attribute) and test.attr == "TYPE_CHECKING")
        )


class _DeferredCollector(ast.NodeVisitor):
    """The exact inverse of `_ImportTimeCollector`: imports nested INSIDE a
    function/method body. #953 — these cross the same package boundaries but are
    invisible to the freeze, so they are counted and reported, never frozen."""

    def __init__(self) -> None:
        self.modules: list[str] = []
        self._fn_depth = 0

    def visit_FunctionDef(self, node: ast.FunctionDef) -> None:
        self._fn_depth += 1
        self.generic_visit(node)
        self._fn_depth -= 1

    visit_AsyncFunctionDef = visit_FunctionDef  # type: ignore[assignment]

    def visit_Import(self, node: ast.Import) -> None:
        if self._fn_depth > 0:
            for alias in node.names:
                self.modules.append(alias.name)

    def visit_ImportFrom(self, node: ast.ImportFrom) -> None:
        if self._fn_depth > 0 and node.level == 0 and node.module:
            self.modules.append(node.module)

    def visit_If(self, node: ast.If) -> None:
        if _ImportTimeCollector._is_type_checking(node.test):
            return
        self.generic_visit(node)


class _AllImportsCollector(ast.NodeVisitor):
    """Collect every import, including function-local; skip TYPE_CHECKING."""

    def __init__(self) -> None:
        self.modules: list[str] = []

    def visit_Import(self, node: ast.Import) -> None:
        for alias in node.names:
            self.modules.append(alias.name)
        self.generic_visit(node)

    def visit_ImportFrom(self, node: ast.ImportFrom) -> None:
        if node.level == 0 and node.module:
            self.modules.append(node.module)
        self.generic_visit(node)

    def visit_If(self, node: ast.If) -> None:
        if _ImportTimeCollector._is_type_checking(node.test):
            return
        self.generic_visit(node)


def _iter_package_py(pkg: str):
    base = ROOT / pkg
    if not base.is_dir():
        return
    for path in base.rglob("*.py"):
        if EXCLUDE_PARTS & set(path.relative_to(ROOT).parts):
            continue
        yield path


def _plugin_memory_edges() -> list[str]:
    """Every plugins/ → memory/ import, including deferred (D-M)."""
    hits: list[str] = []
    for path in _iter_package_py("plugins"):
        try:
            tree = ast.parse(path.read_text(encoding="utf-8"))
        except (SyntaxError, UnicodeDecodeError):
            continue
        collector = _AllImportsCollector()
        collector.visit(tree)
        src_rel = path.relative_to(ROOT).as_posix()
        for mod in collector.modules:
            if _top_pkg(mod) == "memory":
                hits.append(f"{src_rel} -> {mod}")
    return sorted(set(hits))


def _collect_edges(collector_cls) -> set[str]:
    """Cross-package edges seen by `collector_cls` (import-time or deferred)."""
    edges: set[str] = set()
    for pkg in PACKAGES:
        for path in _iter_package_py(pkg):
            try:
                tree = ast.parse(path.read_text(encoding="utf-8"))
            except (SyntaxError, UnicodeDecodeError):
                continue
            collector = collector_cls()
            collector.visit(tree)
            src_rel = path.relative_to(ROOT).as_posix()
            for mod in collector.modules:
                tgt = _top_pkg(mod)
                if tgt in PACKAGES and tgt != pkg:
                    edges.add(f"{src_rel} -> {mod}")
    return edges


def _edges() -> set[str]:
    return _collect_edges(_ImportTimeCollector)


def _deferred_edges() -> set[str]:
    """#953: cross-package imports the freeze does NOT see."""
    return _collect_edges(_DeferredCollector)


def _load_baseline() -> set[str]:
    """Accepts both shapes: a bare list (historic) and the object form that
    carries the `reason` #956 requires for a growing baseline."""
    data = json.loads(BASELINE.read_text(encoding="utf-8"))
    if isinstance(data, dict):
        return set(data.get("edges", []))
    return set(data)


def _update_reason() -> str:
    """#956: the justification for growing the baseline, from `--reason <text>`
    or NEXE_LAYERING_REASON. Empty string when none was given."""
    argv = sys.argv
    if "--reason" in argv:
        i = argv.index("--reason")
        if i + 1 < len(argv):
            return argv[i + 1].strip()
    return os.environ.get("NEXE_LAYERING_REASON", "").strip()


def _write_baseline(current: set[str]) -> int:
    """The `--update` half of the gate (#956). Split out of `main()` so both stay
    under the complexity gate's threshold — which is the sibling gate, and which
    caught this function being inlined."""
    prior = _load_baseline() if BASELINE.exists() else set()
    added = sorted(current - prior)
    reason = _update_reason()
    # Shrinking is free (that is the good direction); GROWING must be a decision
    # someone signed, not a side effect of running --update.
    if added and not reason:
        print(f"REFUSED: --update would ADD {len(added)} edge(s) to the baseline:")
        for e in added:
            print(f"  + {e}")
        print("\nGrowing the frozen debt needs a stated reason. Re-run with:\n"
              '  python scripts/check_layering.py --update --reason "why this edge is right"\n'
              "(or set NEXE_LAYERING_REASON). Shrinking the baseline needs no reason.")
        return 2
    payload: dict[str, object] = {"edges": sorted(current)}
    if reason:
        payload["reason"] = reason
    BASELINE.write_text(json.dumps(payload, indent=1) + "\n", encoding="utf-8")
    verb = f"+{len(added)}" if added else f"-{len(prior - current)}" if prior else "new"
    print(f"baseline updated ({verb}): {len(current)} import-time cross-package "
          f"edges -> {BASELINE.name}")
    if reason:
        print(f"  reason: {reason}")
    return 0


def main() -> int:
    leaks = _plugin_memory_edges()
    if leaks:
        print("LAYERING GATE FAILED (D-M / #875): plugins/ must not import memory/ "
              "(including deferred imports). Go through core.memory_access:")
        for e in leaks:
            print(f"  + {e}")
        return 1

    current = _edges()
    deferred = _deferred_edges()

    if "--update" in sys.argv:
        return _write_baseline(current)

    if not BASELINE.exists():
        print("ERROR: baseline missing. Run: python scripts/check_layering.py --update")
        return 2
    baseline = _load_baseline()
    new = sorted(current - baseline)
    if new:
        print("LAYERING GATE FAILED (finding #471): new import-time cross-package import(s):")
        for e in new:
            print(f"  + {e}")
        # #953: the old hint sold the deferred import as the free way out. It is
        # the sanctioned escape hatch, but it is coupling too — and now counted.
        print("\nIf intentional, either move it inside a function (a deferred import is "
              "not frozen, but it IS still coupling and is reported below), or run "
              '`python scripts/check_layering.py --update --reason "..."`.')
        return 1
    removed = baseline - current
    if removed:
        print(f"OK (note: {len(removed)} baseline edge(s) removed — consider --update to tighten).")
    # #953: print both numbers side by side so the frozen one is never read as
    # the total coupling debt.
    print(f"layering gate OK: {len(current)} import-time cross-package edges, no new ones.")
    print(f"  (not frozen: {len(deferred)} deferred cross-package import(s) — "
          f"real coupling the freeze does not see)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
