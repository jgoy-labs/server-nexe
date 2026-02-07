#!/usr/bin/env python3
"""
Detect likely user-facing strings that are not wrapped in t()/t_modular().
Heuristic-based: produces findings for manual review.
"""
from __future__ import annotations

import ast
import re
import sys
from pathlib import Path
from typing import Iterable, List, Set, Tuple

ROOT = Path(__file__).resolve().parent.parent

EXCLUDE_DIRS = {
    ".git",
    ".venv",
    "venv",
    "node_modules",
    "storage",
    "snapshots",
    "__pycache__",
    ".pytest_cache",
    ".mypy_cache",
    "tests",
}

TRANSLATION_CALLS = {
    "t",
    "t_modular",
    "get_message",
    "_translate",
}


def _iter_py_files() -> Iterable[Path]:
    for path in ROOT.rglob("*.py"):
        if any(part in EXCLUDE_DIRS for part in path.parts):
            continue
        yield path


def _call_name(node: ast.AST) -> str:
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        base = _call_name(node.value)
        return f"{base}.{node.attr}" if base else node.attr
    if isinstance(node, ast.Call):
        return _call_name(node.func) + "()"
    return ""


def _is_translation_context(call_stack: List[str]) -> bool:
    for name in call_stack:
        if name in TRANSLATION_CALLS:
            return True
        if name.endswith(".t") or name.endswith(".t()"):
            if "i18n" in name or "get_i18n" in name:
                return True
    return False


def _looks_user_facing(value: str) -> bool:
    text = value.strip()
    if len(text) < 6:
        return False
    if "\n" in text and len(text) < 12:
        return False
    if re.fullmatch(r"[A-Z0-9_]+", text):
        return False
    if re.fullmatch(r"[a-z0-9_.:/@\-]+", text):
        return False
    if text.startswith(("http://", "https://")):
        return False
    if text.startswith("/") and " " not in text:
        return False
    if not re.search(r"[A-Za-zÀ-ÿ]", text):
        return False
    if " " in text:
        return True
    if re.search(r"[.!?:]", text):
        return True
    return False


class I18nStringVisitor(ast.NodeVisitor):
    def __init__(self, source: str):
        self.source = source
        self.call_stack: List[str] = []
        self.findings: List[Tuple[int, str]] = []

    def _visit_body(self, body: List[ast.stmt]) -> None:
        start = 0
        if body:
            first = body[0]
            if isinstance(first, ast.Expr) and isinstance(first.value, ast.Constant) and isinstance(first.value.value, str):
                start = 1
        for stmt in body[start:]:
            self.visit(stmt)

    def visit_Module(self, node: ast.Module) -> None:
        self._visit_body(node.body)

    def visit_FunctionDef(self, node: ast.FunctionDef) -> None:
        self._visit_body(node.body)

    def visit_AsyncFunctionDef(self, node: ast.AsyncFunctionDef) -> None:
        self._visit_body(node.body)

    def visit_ClassDef(self, node: ast.ClassDef) -> None:
        self._visit_body(node.body)

    def visit_Call(self, node: ast.Call) -> None:
        name = _call_name(node.func)
        self.call_stack.append(name)
        for arg in node.args:
            self.visit(arg)
        for kw in node.keywords:
            if kw.value is not None:
                self.visit(kw.value)
        self.call_stack.pop()

    def visit_Constant(self, node: ast.Constant) -> None:
        if not isinstance(node.value, str):
            return
        if _is_translation_context(self.call_stack):
            return
        if _looks_user_facing(node.value):
            self.findings.append((node.lineno or 0, node.value))



def main() -> int:
    findings_total = 0
    for path in _iter_py_files():
        try:
            source = path.read_text(encoding="utf-8")
        except Exception:
            continue

        try:
            tree = ast.parse(source)
        except SyntaxError:
            continue

        visitor = I18nStringVisitor(source)
        visitor.visit(tree)
        if visitor.findings:
            print(f"\n{path}")
            for lineno, text in visitor.findings:
                preview = text.replace("\n", " ")
                if len(preview) > 120:
                    preview = preview[:117] + "..."
                print(f"  L{lineno}: {preview}")
            findings_total += len(visitor.findings)

    if findings_total:
        print(f"\nFound {findings_total} potential user-facing strings.")
        print("Review and wrap with t()/t_modular() where appropriate.")
        return 1

    print("No potential user-facing strings found.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
