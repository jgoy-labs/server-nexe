"""
────────────────────────────────────
Server Nexe
Author: Jordi Goy
Location: tests/core/ingest/test_1092_knowledge_headers_are_valid.py
Description: #1092 — every document the product ships in knowledge/ has a
             valid RAG header.

An invalid header does not fail the ingest: the document goes in as if it
had none — no abstract in the chunk prefix, default priority, no tags or
type, and the default chunk size instead of the declared one. Five documents
were ingested like that (abstracts over 600 chars, 22 tags) and nothing
said so. This is the gate that would have.

www.jgoy.net · https://server-nexe.org
────────────────────────────────────
"""
from pathlib import Path

import pytest

from memory.rag.header_parser import parse_rag_header

KNOWLEDGE = Path(__file__).resolve().parents[3] / "knowledge"
DOCS = sorted(KNOWLEDGE.glob("*/*.md"))


def test_the_knowledge_base_is_found():
    # An empty glob would make the parametrized test below pass by
    # collecting nothing.
    assert {p.parent.name for p in DOCS} >= {"ca", "es", "en"}
    assert len(DOCS) >= 45


@pytest.mark.parametrize("doc", DOCS, ids=lambda p: f"{p.parent.name}/{p.name}")
def test_the_rag_header_is_valid(doc):
    header, _ = parse_rag_header(doc.read_text(encoding="utf-8"))
    assert header.is_valid, header.validation_errors
