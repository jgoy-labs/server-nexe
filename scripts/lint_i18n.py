#!/usr/bin/env python3
"""
scripts/lint_i18n.py
--------------------
Scans python files for potential user-facing strings that are NOT wrapped in t().
Heuristic based: looks for string literals in print(), input(), or assigned to 'detail=' (FastAPI).
Ignores:
 - Comments
 - Docstrings
 - Strings inside logger.debug/info/warning/error
 - Strings inside t() calls
"""

import ast
import os
import sys
from pathlib import Path

# Directories to scan
SCAN_DIRS = ["."]
# Files to ignore
IGNORE_FILES = ["setup.py", "lint_i18n.py"]
# Directories to ignore
IGNORE_DIRS = {
    ".git",
    ".venv",
    "venv",
    "ENV",
    "__pycache__",
    ".pytest_cache",
    ".mypy_cache",
    ".tox",
    "node_modules",
    "dist",
    "build",
    "storage",
    "knowledge",
    "snapshots",
    "tmp",
}
# Substrings that indicate "internal logic" rather than user text
INTERNAL_STRINGS = [
    ".py", "/", "{", "http", "utf-8", "r", "w", "wb", "rb",
    "__main__", "__init__", "Core", "Plugins"
]

def is_user_facing(node):
    if not isinstance(node, ast.Constant) or not isinstance(node.value, str):
        return False
    s = node.value.strip()
    if not s or len(s) < 2:
        return False
    
    # Heuristics for non-user strings
    if s.startswith("_") or s.upper() == s: # Constants
        return False
    if any(x in s for x in INTERNAL_STRINGS):
        return False
    
    # Heuristics for user strings: Have spaces, capitalization
    if " " in s and s[0].isupper():
        return True
    
    return False

class I18nVisitor(ast.NodeVisitor):
    def __init__(self, filename):
        self.filename = filename
        self.issues = []

    def visit_Call(self, node):
        # Check for print("string") or input("string")
        if isinstance(node.func, ast.Name) and node.func.id in ('print', 'input'):
            for arg in node.args:
                if is_user_facing(arg):
                    self.issues.append((arg.lineno, f"Untranslated string in {node.func.id}(): '{arg.value}'"))
        
        # Check for HTTPException(detail="string")
        elif isinstance(node.func, ast.Name) and node.func.id == 'HTTPException':
            for kw in node.keywords:
                if kw.arg == 'detail' and is_user_facing(kw.value):
                    self.issues.append((kw.lineno, f"Untranslated detail in HTTPException: '{kw.value.value}'"))

        # Check for f-strings (JoinedStr) in print/input - hard to catch but let's try
        # Actually ast treats f-strings as JoinedStr. We need to check if they contain t().
        
        # If it IS a t() call, we skip checking its args (they are keys/defaults)
        if isinstance(node.func, ast.Name) and node.func.id in ('t', 't_modular', '_translate'):
            return

        self.generic_visit(node)

def scan_file(filepath):
    try:
        with open(filepath, "r", encoding="utf-8") as f:
            tree = ast.parse(f.read(), filename=filepath)
        visitor = I18nVisitor(filepath)
        visitor.visit(tree)
        return visitor.issues
    except Exception as e:
        return []

def main():
    print("🔎 I18n Linter: Scanning for untranslated strings...")
    all_issues = []
    root = Path(".")
    
    for item in SCAN_DIRS:
        path = root / item
        if path.is_file():
            files = [path]
        else:
            files = path.rglob("*.py")
            
        for f in files:
            if f.name in IGNORE_FILES:
                continue
            if any(part in IGNORE_DIRS for part in f.parts):
                continue
            issues = scan_file(f)
            for lineno, msg in issues:
                all_issues.append(f"{f}:{lineno} {msg}")

    if all_issues:
        print(f"\nFound {len(all_issues)} potential i18n issues:")
        for issue in all_issues:
            print(f"  - {issue}")
        sys.exit(1)
    else:
        print("✅ No obvious i18n issues found.")
        sys.exit(0)

if __name__ == "__main__":
    main()
