"""
────────────────────────────────────
Server Nexe
Author: Jordi Goy
Location: tests/test_use_cases_encryption_recipe.py
Description: Coherence guardrail for B068. The "Secure local AI (compliance)"
section of knowledge/{en,ca,es}/USE_CASES.md must recommend the STRICT
fail-closed recipe (NEXE_ENCRYPTION_ENABLED=true + sqlcipher3 install),
not sell NEXE_ENCRYPTION_ENABLED=auto as "fail-closed". `auto` is fail-OPEN:
with sqlcipher3 absent it falls back to plaintext (loud banner). A compliance
org following an `=auto, fail-closed` recipe would end up with data in clear.

SCOPE: this test reads ONLY the three USE_CASES.md files. It does NOT grep
over the whole knowledge/ tree (that would match the CORRECT text in
THREAT_MODEL.md / SECURITY.md and the stale text baked into
knowledge/.embeddings/*.jsonl, producing permanent false-positive RED).

www.jgoy.net · https://server-nexe.org
────────────────────────────────────
"""

import re
from pathlib import Path

import pytest

# Repo root = parent of tests/ (this file lives at <root>/tests/...).
ROOT = Path(__file__).resolve().parent.parent
USE_CASES = [ROOT / "knowledge" / lang / "USE_CASES.md" for lang in ("en", "ca", "es")]


def _compliance_section(text: str) -> str:
    """Return the body of the compliance / sensitive-data use case (section 6),
    i.e. the text from the section header up to the next '---' or '##' header.
    Falls back to the whole document if the marker is absent (so the test fails
    loudly rather than passing vacuously)."""
    # The header contains the word 'compliance' in all three languages.
    lines = text.splitlines()
    start = None
    for i, line in enumerate(lines):
        if line.lstrip().startswith("##") and "compliance" in line.lower():
            start = i
            break
    if start is None:
        return text
    body = []
    for line in lines[start + 1:]:
        stripped = line.lstrip()
        if stripped.startswith("---") or stripped.startswith("## "):
            break
        body.append(line)
    return "\n".join(body)


@pytest.mark.parametrize("path", USE_CASES, ids=lambda p: p.parent.name)
def test_use_cases_file_exists(path: Path):
    assert path.is_file(), f"missing knowledge file: {path}"


@pytest.mark.parametrize("path", USE_CASES, ids=lambda p: p.parent.name)
def test_compliance_does_not_sell_auto_as_failclosed(path: Path):
    """REGRESSION (B068): the compliance section must NOT pair
    `NEXE_ENCRYPTION_ENABLED=auto` with a 'fail-closed' claim. `auto` is
    fail-OPEN."""
    section = _compliance_section(path.read_text(encoding="utf-8"))

    # Does the compliance section mention =auto at all?
    mentions_auto = "NEXE_ENCRYPTION_ENABLED=auto" in section
    # Does it make a fail-closed claim?
    failclosed = re.search(r"fail[\s\-]?clos", section, re.IGNORECASE) is not None

    assert not (mentions_auto and failclosed), (
        f"{path}: compliance section sells `=auto` as fail-closed — `=auto` is "
        f"fail-OPEN (plaintext + banner when sqlcipher3 is absent). Recommend "
        f"`NEXE_ENCRYPTION_ENABLED=true` instead."
    )


@pytest.mark.parametrize("path", USE_CASES, ids=lambda p: p.parent.name)
def test_compliance_recommends_true(path: Path):
    """The compliance section must recommend the strict fail-closed value
    `NEXE_ENCRYPTION_ENABLED=true`."""
    section = _compliance_section(path.read_text(encoding="utf-8"))
    assert "NEXE_ENCRYPTION_ENABLED=true" in section, (
        f"{path}: compliance section must recommend "
        f"`NEXE_ENCRYPTION_ENABLED=true` (strict fail-closed) for sensitive data."
    )


@pytest.mark.parametrize("path", USE_CASES, ids=lambda p: p.parent.name)
def test_compliance_includes_sqlcipher_install(path: Path):
    """`=true` is strict fail-closed → the server refuses to start without
    sqlcipher3. The recipe MUST include installing it (same as SECURITY /
    the startup banner), otherwise a clean machine cannot boot the server."""
    section = _compliance_section(path.read_text(encoding="utf-8"))
    assert "sqlcipher3-binary" in section, (
        f"{path}: compliance recipe sets `=true` (fail-closed) but omits "
        f"`pip install sqlcipher3-binary`; on a clean machine the server "
        f"refuses to start. Include the install step."
    )
