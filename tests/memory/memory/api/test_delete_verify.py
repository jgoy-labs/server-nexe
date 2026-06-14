"""
────────────────────────────────────
Server Nexe
Author: Jordi Goy
Location: tests/memory/memory/api/test_delete_verify.py
Description: Stage 1 (ADR-002) — delete must VERIFY the point is actually gone.
            A silent Qdrant delete (accepts the call but leaves the point) must
            not be reported as success. A TextStore failure must not crash and
            must be logged as an orphan, without flipping a successful vector
            delete to failure.

www.jgoy.net · https://server-nexe.org
────────────────────────────────────
"""
import asyncio
import logging
from concurrent.futures import ThreadPoolExecutor
from unittest.mock import MagicMock

from memory.memory.api.documents import delete_document

_DOC_ID = "abc123def456abcd"


def _executor():
    return ThreadPoolExecutor(max_workers=1)


def _point():
    p = MagicMock()
    p.id = "00000000-0000-0000-0000-000000000000"
    return p


def test_delete_returns_false_when_point_survives():
    """Silent Qdrant delete (point still present on re-read) → NOT success.

    Red before fix: delete_document ignores verification and returns True.
    Green after fix: it re-reads, sees the point, retries, and returns False.
    """
    q = MagicMock()
    q.delete = MagicMock()  # no-op: pretends the delete succeeded
    q.retrieve = MagicMock(return_value=[_point()])  # but the point is ALWAYS still there
    ex = _executor()
    try:
        result = asyncio.run(delete_document(q, ex, _DOC_ID, "col"))
    finally:
        ex.shutdown(wait=False)
    assert result is False


def test_delete_retries_then_succeeds():
    """First re-read still sees the point; after a retry it's gone → success."""
    q = MagicMock()
    q.delete = MagicMock()
    q.retrieve = MagicMock(side_effect=[[_point()], []])  # survives once, gone after retry
    ex = _executor()
    try:
        result = asyncio.run(delete_document(q, ex, _DOC_ID, "col"))
    finally:
        ex.shutdown(wait=False)
    assert result is True
    assert q.delete.call_count == 2  # it retried the delete


def test_textstore_failure_does_not_crash_and_keeps_success(caplog):
    """Qdrant point gone but TextStore.delete raises → still success, orphan logged."""
    q = MagicMock()
    q.delete = MagicMock()
    q.retrieve = MagicMock(return_value=[])  # point is gone
    text_store = MagicMock()
    text_store.delete = MagicMock(side_effect=RuntimeError("sqlite is locked"))
    ex = _executor()
    try:
        with caplog.at_level(logging.ERROR):
            result = asyncio.run(
                delete_document(q, ex, _DOC_ID, "col", text_store=text_store)
            )
    finally:
        ex.shutdown(wait=False)
    assert result is True  # the user-visible vector is gone
    assert any("orphan" in r.getMessage().lower() for r in caplog.records), (
        "a TextStore delete failure must be logged as an orphan, not swallowed"
    )
