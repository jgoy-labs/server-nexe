"""#1085: every `today` pointer in TURN_STEPS points at something real.

The map's pointers were `file:line` citations verified once (2026-09-05) and
never again: by 2026-09-24 five pointed past the end of routes_chat.py and
others had drifted to unrelated lines. Nothing checked them, so nothing
noticed. This gate does, for every pointer in the map:

- the cited file exists (repo-relative; `{a,b}` brace groups are expanded);
- a cited line (``path:N``, ``path:N-M``, ``path:N,M``) is inside the file;
- a cited symbol — an identifier inside the ``(...)`` right after the path,
  before any ``:`` prose — appears as a whole word in that file.
"""
from __future__ import annotations

import re
from pathlib import Path

from core.turn.steps import TURN_STEPS

ROOT = Path(__file__).resolve().parents[3]

# A path token (anything ending in .py), an optional :line spec, and an
# optional parenthesised symbol list right after it.
_POINTER = re.compile(
    r"(?P<path>[\w{},./]+\.py)(?::(?P<lines>[\d,\-]+))?(?:\s*\((?P<syms>[^)]*)\))?"
)
_IDENT = re.compile(r"^[A-Za-z_][\w.]*$")


def _expand(path: str) -> list[str]:
    m = re.search(r"\{([^}]*)\}", path)
    if not m:
        return [path]
    return [
        p
        for alt in m.group(1).split(",")
        for p in _expand(path[: m.start()] + alt + path[m.end():])
    ]


def _symbols(syms: str | None) -> list[str]:
    if not syms:
        return []
    head = syms.split(":", 1)[0]
    parts = (t.strip() for chunk in head.split(",") for t in chunk.split("+"))
    return [t for t in parts if _IDENT.match(t)]


def pointer_problems(text: str) -> tuple[int, list[str]]:
    """(pointers found, problems) for one `today` string."""
    found = 0
    problems: list[str] = []
    for m in _POINTER.finditer(text):
        found += 1
        for rel in _expand(m.group("path")):
            f = ROOT / rel
            if not f.is_file():
                problems.append(f"{rel}: no such file")
                continue
            src = f.read_text(encoding="utf-8")
            n_lines = len(src.splitlines())
            for num in re.findall(r"\d+", m.group("lines") or ""):
                if not 1 <= int(num) <= n_lines:
                    problems.append(f"{rel}:{num}: past the end ({n_lines} lines)")
            for sym in _symbols(m.group("syms")):
                if not re.search(rf"\b{re.escape(sym)}\b", src):
                    problems.append(f"{rel}: symbol {sym!r} not found")
    return found, problems


def test_every_pointer_in_the_map_is_real():
    problems = []
    for step in TURN_STEPS:
        for door, text in step.today.items():
            found, probs = pointer_problems(text)
            assert found, f"{step.id}/{door}: no path in {text!r}"
            problems += [f"{step.id}/{door}: {p}" for p in probs]
    assert not problems, "\n".join(problems)


def test_the_checker_catches_each_kind_of_drift():
    # Not theatre: each failure mode the gate claims to catch, caught.
    assert pointer_problems("core/turn/nope.py (x)")[1] == ["core/turn/nope.py: no such file"]
    assert "past the end" in pointer_problems("core/turn/steps.py:99999")[1][0]
    assert "not found" in pointer_problems("core/turn/steps.py (no_such_symbol_zz)")[1][0]
    # A bare filename is not a repo path.
    assert pointer_problems("routes_chat.py:595")[1]
    # Braces expand, and prose after ':' inside the parens is not a symbol.
    assert pointer_problems(
        "core/endpoints/chat_engines/{mlx,ollama}.py (module.chat / HTTP)"
    ) == (1, [])
    assert pointer_problems("core/turn/steps.py (TURN_STEPS: any prose here)") == (1, [])
