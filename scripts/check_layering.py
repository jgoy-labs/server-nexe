#!/usr/bin/env python3
"""Layering gate (finding #471) — freeze the inter-package coupling debt.

server-nexe's four top packages (core, memory, personality, plugins) form a
fully-connected import graph. The verification (2026-06-19) confirmed there are
NO real import-time cycles (deferred imports break them) — so this is a
maintainability concern (P3), not a runtime bug. This gate does NOT try to undo
the existing coupling; it FREEZES it: any NEW import-time (module-level) cross-
package import that is not already in the baseline fails CI, so the debt cannot
silently grow.

Only IMPORT-TIME imports are considered: imports at module scope (incl. top-level
try/if blocks), NOT imports nested inside functions/methods. Deferred (function-
local) imports are the legitimate escape hatch and are intentionally ignored.
`if TYPE_CHECKING:` blocks are also ignored — they never execute at runtime, so a
type-only import there is not runtime coupling (MC-102).

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


def _edges() -> set[str]:
    edges: set[str] = set()
    for pkg in PACKAGES:
        base = ROOT / pkg
        if not base.is_dir():
            continue
        for path in base.rglob("*.py"):
            if EXCLUDE_PARTS & set(path.relative_to(ROOT).parts):
                continue
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
