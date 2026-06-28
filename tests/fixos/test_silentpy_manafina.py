"""
────────────────────────────────────
Server Nexe
Author: Jordi Goy
Location: tests/fixos/test_silentpy_manafina.py
Description: Regression guards for the 'mà fina' silent-py findings that touch
             contract/behaviour (MC-015, MC-018). Plans contrasted with an
             AI audit before implementation.

  MC-015 — memory_helper._search_delete_candidates swallowed per-collection
           errors at debug; if EVERY collection errored (Qdrant down), the
           caller reported "nothing found" (success=True) instead of an error.
           Fix: warning log + re-raise only when ALL collections errored (no
           collection responded), so partial resilience is preserved.

  MC-018 — MemoryService.initialize() returned True and logged "initialized"
           even when the VectorIndex failed to load. Fix is ADDITIVE: a new
           `vector_index_available` property + an honest log line. `initialized`
           is NOT flipped (recall works via SQLite without the vector index).

www.jgoy.net · https://server-nexe.org
────────────────────────────────────
"""

import asyncio
import logging
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


# ─── MC-015 — delete reports "not found" when the search actually failed ──────

def _helper_with_memory(memory):
    from plugins.web_ui_module.core.memory_helper import MemoryHelper
    helper = MemoryHelper()
    helper.get_memory_api = AsyncMock(return_value=memory)
    return helper


def test_mc015_delete_all_collections_error_returns_failure():
    """If every collection's search raises (e.g. Qdrant down), delete must
    surface success=False, not the misleading 'nothing found' (success=True)."""
    memory = MagicMock()
    memory.collection_exists = AsyncMock(return_value=True)
    memory.search = AsyncMock(side_effect=RuntimeError("Qdrant down"))

    helper = _helper_with_memory(memory)
    result = asyncio.run(helper.delete_from_memory("oblida això", collections=["c1", "c2"]))

    assert result["success"] is False, "all-collections-error must not look like 'not found'"
    assert result["deleted"] == 0


def test_mc015_partial_error_keeps_resilience():
    """If at least one collection responds (even with 0 results), a failure in
    another collection must NOT propagate — partial resilience is preserved and
    the legitimate 'nothing found' (success=True) stands."""
    memory = MagicMock()
    memory.collection_exists = AsyncMock(return_value=True)
    # c1 raises, c2 responds with no matches.
    memory.search = AsyncMock(side_effect=[RuntimeError("c1 down"), []])

    helper = _helper_with_memory(memory)
    result = asyncio.run(helper.delete_from_memory("oblida això", collections=["c1", "c2"]))

    assert result["success"] is True
    assert result["deleted"] == 0


def test_mc015_no_collection_exists_is_not_an_error():
    """Collections that simply don't exist (service alive, no data) stay the
    legitimate 'nothing found' — not an error."""
    memory = MagicMock()
    memory.collection_exists = AsyncMock(return_value=False)
    memory.search = AsyncMock(return_value=[])

    helper = _helper_with_memory(memory)
    result = asyncio.run(helper.delete_from_memory("oblida això", collections=["c1", "c2"]))

    assert result["success"] is True
    assert result["deleted"] == 0


# ─── MC-018 — initialize() health no longer lies about the vector index ───────

def _service(tmp_path):
    from memory.memory.memory_service import MemoryService
    return MemoryService(db_path=tmp_path / "mem.db", qdrant_path=str(tmp_path / "q"))


def test_mc018_vector_index_unavailable_is_honest(tmp_path, caplog):
    """When the VectorIndex fails to load, initialize() still returns True
    (recall via SQLite works) BUT vector_index_available is False and the log
    says so — the health signal stops lying."""
    svc = _service(tmp_path)

    with patch(
        "memory.memory.storage.vector_index.VectorIndex",
        side_effect=RuntimeError("qdrant boom"),
    ):
        with caplog.at_level(logging.WARNING, logger="memory.memory.memory_service"):
            ok = asyncio.run(svc.initialize())

    assert ok is True  # contract unchanged: SQLite-backed recall still works
    assert svc.initialized is True
    assert svc.vector_index_available is False
    assert any(
        r.levelno >= logging.WARNING and "vector" in r.getMessage().lower()
        for r in caplog.records
    ), "expected a warning that the vector index is unavailable"


def test_mc018_vector_index_available_when_ok(tmp_path):
    """When the VectorIndex loads, vector_index_available is True."""
    svc = _service(tmp_path)

    with patch(
        "memory.memory.storage.vector_index.VectorIndex",
        return_value=MagicMock(),
    ):
        ok = asyncio.run(svc.initialize())

    assert ok is True
    assert svc.vector_index_available is True
