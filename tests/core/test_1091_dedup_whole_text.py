"""
────────────────────────────────────
Server Nexe
Author: Jordi Goy
Location: tests/core/test_1091_dedup_whole_text.py
Description: #1091 — both RAG dedups key on the whole text, so the chunks
             of a document with a long RAG header are not collapsed into one.

www.jgoy.net · https://server-nexe.org
────────────────────────────────────
"""

from unittest.mock import MagicMock

from core.endpoints.chat_rag import _deduplicate_results as chat_dedup
from core.memory_facts.helper import MemoryHelper

# The shape the knowledge ingest writes in front of every chunk
# (core/ingest/ingest_knowledge.py). An abstract of ~600 chars — the header
# parser's limit — fills both the old 500-char and 200-char keys.
_PREFIX = "[Document: RAG.md]\n[Abstract: " + "x" * 600 + "]\n\n"
_CHUNK_A = _PREFIX + "Qdrant stores the vectors."
_CHUNK_B = _PREFIX + "The threshold is tuned per collection."


def _hit(text: str):
    obj = MagicMock()
    obj.text = text
    return obj


def _row(text: str, score: float) -> dict:
    return {"content": text, "score": score, "metadata": {}, "_id": None}


class TestChatDedup:
    def test_two_chunks_of_one_document_both_survive(self):
        a, b = _hit(_CHUNK_A), _hit(_CHUNK_B)
        assert chat_dedup([a, b]) == [a, b]

    def test_an_exact_duplicate_still_collapses(self):
        a, a2 = _hit(_CHUNK_A), _hit(_CHUNK_A)
        assert chat_dedup([a, a2]) == [a]


class TestRecallDedup:
    def test_two_chunks_of_one_document_both_survive(self):
        rows = [_row(_CHUNK_A, 0.9), _row(_CHUNK_B, 0.8)]
        out = MemoryHelper._deduplicate_results(rows, limit=5)
        assert [r["content"] for r in out] == [_CHUNK_A, _CHUNK_B]

    def test_an_exact_duplicate_still_collapses(self):
        rows = [_row(_CHUNK_A, 0.9), _row(_CHUNK_A + "  ", 0.8)]
        out = MemoryHelper._deduplicate_results(rows, limit=5)
        assert len(out) == 1 and out[0]["score"] == 0.9
