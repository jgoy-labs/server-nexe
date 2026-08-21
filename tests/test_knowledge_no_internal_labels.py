"""
────────────────────────────────────
Server Nexe
Author: Jordi Goy
Location: tests/test_knowledge_no_internal_labels.py
Description: Coherence guardrail. knowledge/ ships INSIDE the product and the
RAG serves it to the end user, so internal work-item labels of the form "D-<X>"
must never reach it: they name entries in the development backlog and mean
nothing to whoever reads the product documentation. Published references
(MC-xxx, ADR Bxxx) are a different matter and stay.

Two releases in a row shipped such a label in the plugin docs before this gate
existed; both were caught by hand.

SCOPE: reads ONLY the .md sources under knowledge/<lang>/. It does NOT grep the
whole tree — knowledge/.embeddings/*.jsonl carries the text baked in at the last
precompute, which lags the sources between a fix and its re-embed and would turn
this into permanent false-positive RED.

www.jgoy.net · https://server-nexe.org
────────────────────────────────────
"""

import re
from pathlib import Path

# Repo root = parent of tests/ (this file lives at <root>/tests/...).
ROOT = Path(__file__).resolve().parent.parent
KNOWLEDGE = ROOT / "knowledge"

# A lot letter: 'D-' plus a single capital, standing alone as a word.
# 'D-Bus' or 'D-Link' do not match (no word boundary after the capital).
LOT_LABEL = re.compile(r"\bD-[A-Z]\b")


def _language_docs() -> list[Path]:
    if not KNOWLEDGE.is_dir():
        return []
    return sorted(
        path
        for path in KNOWLEDGE.glob("*/*.md")
        if ".embeddings" not in path.parts
    )


def test_language_docs_are_found():
    """Guard the guard: an empty file list would make the check pass vacuously."""
    docs = _language_docs()
    assert len(docs) >= 3, f"expected the knowledge language folders, found {docs}"


def test_no_internal_lot_labels_in_shipped_knowledge():
    offenders: list[str] = []
    for path in _language_docs():
        for lineno, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
            for match in LOT_LABEL.finditer(line):
                rel = path.relative_to(ROOT).as_posix()
                offenders.append(f"{rel}:{lineno} -> {match.group(0)}")
    assert not offenders, (
        "internal lot labels reached the shipped knowledge (the RAG serves this "
        "text to the end user). Describe what the thing does, not which letter of "
        "the queue built it:\n  " + "\n  ".join(offenders)
    )
