"""
────────────────────────────────────
Server Nexe
Author: Jordi Goy
Location: tests/fixos/test_silentpy_observability.py
Description: Regression guards for the 'silent-py' batch (MC-016, MC-017,
             MC-019, MC-021). Each finding hid a real backend failure behind a
             debug-level log or a no-log path, making the failure invisible in
             production (debug off). The fixes are ADDITIVE: they only raise the
             log level / distinguish error-vs-dedup, never changing the return
             value or control flow. These tests assert the failure is now
             OBSERVABLE at warning/error level.

  Verified independently by an AI audit (cross-model read-only review)
  before implementation — all four = REAL-BUG, fix safe.

www.jgoy.net · https://server-nexe.org
────────────────────────────────────
"""

import logging
from unittest.mock import AsyncMock, MagicMock

import pytest


# ─── MC-019 — DreamingCycle._count_pending swallows SQLite errors w/o log ─────

class _BadConn:
    def __init__(self):
        self.closed = False

    def execute(self, sql, params=()):
        raise RuntimeError("sqlite boom")

    def close(self):
        self.closed = True


class _Store:
    def __init__(self, conn):
        self._conn = conn

    def _connect(self):
        return self._conn

    def get_staging(self, **kwargs):
        return []


def test_mc019_count_pending_logs_warning_on_error(caplog):
    """A SQLite error inside _count_pending must surface as a WARNING, not be
    silently turned into 'queue empty' (return 0 with no log)."""
    from memory.memory.workers.dreaming_cycle import DreamingCycle

    cycle = DreamingCycle.__new__(DreamingCycle)
    cycle._store = _Store(_BadConn())

    with caplog.at_level(logging.WARNING, logger="memory.memory.workers.dreaming_cycle"):
        result = cycle._count_pending()

    assert result == 0  # control flow unchanged
    assert any(
        r.levelno >= logging.WARNING and "_count_pending" in r.getMessage()
        for r in caplog.records
    ), "expected a WARNING that _count_pending failed"


# ─── MC-021 — ingest_knowledge swallows init errors w/o log at capture site ───

@pytest.mark.asyncio
async def test_mc021_ingest_init_failure_logs_error(tmp_path, monkeypatch, caplog):
    """When memory/config init raises, ingest_knowledge must log the root cause
    (error level, with the exception) before returning False — not return an
    opaque False with no trace."""
    import core.ingest.ingest_knowledge as ik

    # A knowledge folder with one document so we reach the init try/except.
    (tmp_path / "doc.txt").write_text("hello", encoding="utf-8")
    monkeypatch.setattr(ik, "_discover_documents", lambda p: [tmp_path / "doc.txt"])
    monkeypatch.setattr(ik, "_print_ingestion_header", lambda files: None)

    async def _boom(log):
        raise RuntimeError("init exploded")

    monkeypatch.setattr(ik, "_ingest_initialize_memory_and_config", _boom)

    with caplog.at_level(logging.ERROR, logger="core.ingest.ingest_knowledge"):
        result = await ik.ingest_knowledge(folder=tmp_path, quiet=True)

    assert result is False  # control flow unchanged
    assert any(
        r.levelno >= logging.ERROR and "init exploded" in r.getMessage()
        for r in caplog.records
    ), "expected an ERROR log carrying the root-cause exception"


# ─── MC-017 — RAG search errors logged only at debug → invisible in prod ──────

@pytest.mark.asyncio
async def test_mc017_rag_search_error_logs_warning(caplog):
    """A failing Qdrant search must log at WARNING (distinct from the legitimate
    0-results case), so 'RAG looks empty' is distinguishable from 'RAG broken'."""
    from core.endpoints.chat_rag import _search_collection

    memory = MagicMock()
    memory.collection_exists = AsyncMock(return_value=True)
    memory.search = AsyncMock(side_effect=RuntimeError("Qdrant connection failed"))

    with caplog.at_level(logging.WARNING, logger="core.endpoints.chat_rag"):
        result = await _search_collection(memory, "nexe_documentation", "q", 0.5, 5)

    assert result == []  # control flow unchanged (graceful degradation kept)
    assert any(
        r.levelno >= logging.WARNING and "nexe_documentation" in r.getMessage()
        for r in caplog.records
    ), "expected a WARNING when the RAG search raises"


# ─── MC-016 — MEM_SAVE storage error mislabelled as dedup skip ────────────────

@pytest.mark.asyncio
async def test_mc016_persist_facts_storage_error_logs_warning(caplog):
    """A storage error (success=False, no duplicate flag) must log at WARNING,
    not be silently logged as a dedup skip at debug."""
    from plugins.web_ui_module.api import routes_chat

    helper = MagicMock()
    helper.save_to_memory = AsyncMock(
        return_value={"success": False, "document_id": None, "message": "backend down"}
    )

    with caplog.at_level(logging.WARNING, logger=routes_chat.logger.name):
        saved = await routes_chat._persist_facts(["fact one"], helper, "sess-1")

    assert saved == 0
    assert any(
        r.levelno >= logging.WARNING for r in caplog.records
    ), "expected a WARNING when MEM_SAVE storage fails"


@pytest.mark.asyncio
async def test_mc016_persist_facts_dedup_stays_quiet(caplog):
    """A genuine dedup (duplicate=True) must NOT be logged as an error/warning —
    it's a legitimate no-op, kept at debug."""
    from plugins.web_ui_module.api import routes_chat

    helper = MagicMock()
    helper.save_to_memory = AsyncMock(
        return_value={"success": False, "document_id": None, "duplicate": True}
    )

    with caplog.at_level(logging.WARNING, logger=routes_chat.logger.name):
        saved = await routes_chat._persist_facts(["fact two"], helper, "sess-2")

    assert saved == 0
    assert not any(
        r.levelno >= logging.WARNING for r in caplog.records
    ), "dedup must stay quiet (no warning/error)"
