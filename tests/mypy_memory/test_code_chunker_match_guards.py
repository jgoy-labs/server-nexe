"""Anti-regression scenario — `code_chunker.py` regex match guards.

Covers the 2 mypy `union-attr` findings at
`memory/embeddings/chunkers/code_chunker.py:240` (`name = match_class.group(1)` in
an `else` branch preceded by `if match_func or match_class:`) and L309 (identical
structure but with 4 alternatives in JS: `is_func`, `is_export_func`, `is_class`,
`is_arrow`).

Mechanics: the disjunction guarantees at runtime that inside the final `else`,
the last alternative is truthy — but mypy does not narrow on multiple disjunctions
and flags `Item "None" of "Match[str] | None" has no attribute "group"`.

design decision: dev refactors to explicit `if/elif/else` or adds `assert`
post-else. Runtime does not change.

PINNED CONTRACT (compatible with any option):
1. Given a Python file with only one class (no function), `_chunk_python`
   correctly extracts the class name via the `else` branch at L240.
2. Given a Python file with only one function, `_chunk_python` extracts the name
   via the `if match_func` branch.
3. Given a JS file with only an arrow function, `_chunk_javascript` extracts
   the name via the `else` branch at L309.
4. Given a JS file with only a `class`, `_chunk_javascript` extracts the name
   via the `is_class` branch.

Pre-fix (HEAD `30eb2a6`): runtime contract is fulfilled. Post-fix: must continue
to be fulfilled. If dev simplifies/refactors the `if/elif/else` logic and breaks
a branch, this test detects the regression.
"""

from __future__ import annotations

import pytest


@pytest.fixture
def chunker():
    from memory.embeddings.chunkers.code_chunker import CodeChunker

    return CodeChunker()


def _python_class_only_source() -> str:
    """Python file with only one class (no top-level def)."""
    return (
        "class OnlyClass:\n"
        "    \"\"\"Docstring.\"\"\"\n"
        "    attr = 1\n"
    )


def _python_function_only_source() -> str:
    """Python file with only one function (no top-level class)."""
    return (
        "def only_function(x):\n"
        "    return x * 2\n"
    )


def test_chunk_python_class_only_extracts_name(chunker) -> None:
    """Covers the `else` branch at L240 (`name = match_class.group(1)`).

    Pre-fix: the branch executes with `match_func=None, match_class=truthy` because
    the disjunction `if match_func or match_class:` guarantees it. Post-fix:
    `if/elif` or `assert` maintain the same output."""
    raw = chunker._chunk_python(_python_class_only_source())
    assert len(raw) == 1, f"Expected 1 chunk, found {len(raw)}: {raw!r}"
    chunk_text, chunk_meta = raw[0]
    assert chunk_meta == {"name": "OnlyClass", "type": "class"}, (
        f"scenario metadata (class branch L240) broken: {chunk_meta!r}."
    )
    assert "OnlyClass" in chunk_text


def test_chunk_python_function_only_extracts_name(chunker) -> None:
    """Covers the `if match_func` branch at L236-238.

    This test makes sense together with the class one: ensures that BOTH branches
    work, not just the finding one. If dev refactors to `elif match_class`
    but leaves `match_func.group(2)` wrong, this test fails."""
    raw = chunker._chunk_python(_python_function_only_source())
    assert len(raw) == 1
    _chunk_text, chunk_meta = raw[0]
    assert chunk_meta == {"name": "only_function", "type": "function"}


def test_chunk_javascript_arrow_only_extracts_name(chunker) -> None:
    """Covers the `else` branch at L309 (`name = is_arrow.group(3)`).

    We build a file with only an arrow function — `is_func`,
    `is_export_func`, `is_class` are all None, and the `else` branch must extract
    the arrow variable name."""
    js_source = (
        "const computeSum = (a, b) => {\n"
        "  return a + b;\n"
        "};\n"
    )
    raw = chunker._chunk_javascript(js_source)
    assert len(raw) == 1, f"Expected 1 chunk, found {len(raw)}: {raw!r}"
    _chunk_text, chunk_meta = raw[0]
    assert chunk_meta == {"name": "computeSum", "type": "arrow_function"}, (
        f"scenario metadata (arrow branch L309) broken: {chunk_meta!r}."
    )


def test_chunk_javascript_class_only_extracts_name(chunker) -> None:
    """Covers the `elif is_class` branch at L305-307. Co-test of the JS cluster."""
    js_source = (
        "class Foo {\n"
        "  bar() { return 1; }\n"
        "}\n"
    )
    raw = chunker._chunk_javascript(js_source)
    assert len(raw) == 1
    _chunk_text, chunk_meta = raw[0]
    assert chunk_meta == {"name": "Foo", "type": "class"}


def test_chunk_javascript_function_only_extracts_name(chunker) -> None:
    """Covers the `if is_func` (first) branch at L299-301."""
    js_source = (
        "function helper(arg) {\n"
        "  return arg + 1;\n"
        "}\n"
    )
    raw = chunker._chunk_javascript(js_source)
    assert len(raw) == 1
    _chunk_text, chunk_meta = raw[0]
    assert chunk_meta == {"name": "helper", "type": "function"}
