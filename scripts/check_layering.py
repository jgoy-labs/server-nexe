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

Usage:
    python scripts/check_layering.py            # check against baseline (CI)
    python scripts/check_layering.py --update    # regenerate the baseline
"""
from __future__ import annotations

import ast
import json
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


def _edges() -> set[str]:
    edges: set[str] = set()
    for pkg in PACKAGES:
        for path in _iter_package_py(pkg):
            try:
                tree = ast.parse(path.read_text(encoding="utf-8"))
            except (SyntaxError, UnicodeDecodeError):
                continue
            collector = _ImportTimeCollector()
            collector.visit(tree)
            src_rel = path.relative_to(ROOT).as_posix()
            for mod in collector.modules:
                tgt = _top_pkg(mod)
                if tgt in PACKAGES and tgt != pkg:
                    edges.add(f"{src_rel} -> {mod}")
    return edges


def main() -> int:
    leaks = _plugin_memory_edges()
    if leaks:
        print("LAYERING GATE FAILED (D-M / #875): plugins/ must not import memory/ "
              "(including deferred imports). Go through core.memory_access:")
        for e in leaks:
            print(f"  + {e}")
        return 1

    current = _edges()
    if "--update" in sys.argv:
        BASELINE.write_text(json.dumps(sorted(current), indent=1) + "\n", encoding="utf-8")
        print(f"baseline updated: {len(current)} import-time cross-package edges -> {BASELINE.name}")
        return 0

    if not BASELINE.exists():
        print("ERROR: baseline missing. Run: python scripts/check_layering.py --update")
        return 2
    baseline = set(json.loads(BASELINE.read_text(encoding="utf-8")))
    new = sorted(current - baseline)
    if new:
        print("LAYERING GATE FAILED (finding #471): new import-time cross-package import(s):")
        for e in new:
            print(f"  + {e}")
        print("\nIf intentional, use a deferred (function-local) import, or run "
              "`python scripts/check_layering.py --update` and justify the new edge in review.")
        return 1
    removed = baseline - current
    if removed:
        print(f"OK (note: {len(removed)} baseline edge(s) removed — consider --update to tighten).")
    print(f"layering gate OK: {len(current)} import-time cross-package edges, no new ones.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
