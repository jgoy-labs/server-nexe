"""
────────────────────────────────────
Server Nexe
Location: tests/test_1004_frozen_metrics_instrumented.py
Description: #1004 — three Prometheus metrics that were declared and never
             written, so they read zero forever.

             `RAG_SEARCHES` and `RAG_SEARCH_DURATION` were defined in
             `core/metrics/registry.py`, exported in its `__all__` and imported
             by nobody. `MEMORY_STORE_SIZE` was imported by
             `memory/memory/api/documents.py` and then discarded at all four
             call sites (`ops, _ = _get_metrics()`). A dashboard reading any of
             the three saw a flat zero and could not tell "nothing happened"
             from "nobody is counting".

             Decision (Jordi): instrument them, do not delete them.

             ADR-008 E2: #1004 first wired the RAG pair into
             `RAGModule.search` — which the server never called, so they were
             STILL zero in production. They are now written where the chat
             retrieves: once per source per turn, in
             `core/endpoints/chat_rag.py::_search_source`. These tests drive
             that path (`build_rag_context`, the entry both doors use) and keep
             what #1004/#1005 pinned: counted and timed on both outcomes, a
             metric write that raises never changes what retrieval returns,
             and that failure is reported once.

             These tests assert the values MOVE, not that the metrics exist —
             existence was never the problem. Every assertion is a delta
             against the value read before the call, or a label no other test
             touches, because the registry is process-global.
────────────────────────────────────
"""

from __future__ import annotations

import asyncio
import logging
from concurrent.futures import ThreadPoolExecutor
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest
from prometheus_client import REGISTRY

import core.endpoints.chat_rag as chat_rag
from core.endpoints.chat_rag import _search_source, build_rag_context
from core.memory_access import DOCS_COLLECTION, KNOWLEDGE_COLLECTION, MEMORY_COLLECTION
from core.rag.registry import clear_registered_sources, register_source
from core.rag.source import RAGQuery

RAG_COUNT = "core_rag_searches_total"
RAG_DURATION_COUNT = "core_rag_search_duration_seconds_count"
RAG_DURATION_SUM = "core_rag_search_duration_seconds_sum"
STORE_SIZE = "core_memory_store_size"


def _sample(name: str, labels: dict[str, str]) -> float:
    """Current value of one series. A label pair never touched reads as 0."""
    value = REGISTRY.get_sample_value(name, labels)
    return 0.0 if value is None else float(value)


class _Hit:
    def __init__(self, text: str, collection: str | None = None):
        self.text = text
        self.score = 0.9
        self.metadata = {}
        if collection is not None:
            self.collection = collection


class _FakeSource:
    """A registered source that answers however the test needs it to."""

    def __init__(self, name: str, *, raises: Exception | None = None,
                 delay: float = 0.0, hits: list | None = None):
        self._name = name
        self._raises = raises
        self._delay = delay
        self._hits = hits if hits is not None else []
        self.calls = 0

    def name(self) -> str:
        return self._name

    async def search(self, memory: Any, query: RAGQuery) -> list:
        self.calls += 1
        if self._delay:
            await asyncio.sleep(self._delay)
        if self._raises is not None:
            raise self._raises
        return self._hits


def _memory(search_results: list | None = None):
    """A MemoryAPI double: the store is faked, the sources are real."""
    api = MagicMock()
    api.list_collections = AsyncMock(return_value=[])  # -> system defaults
    api.embed_query = AsyncMock(return_value=[0.1, 0.2])
    api.collection_exists = AsyncMock(return_value=True)
    api.search = AsyncMock(return_value=search_results or [])
    return api


@pytest.fixture(autouse=True)
def _clean_registry_and_one_shot():
    """The registry and the report-once flag are process-global."""
    clear_registered_sources()
    chat_rag._metrics_write_failed_reported = False
    yield
    clear_registered_sources()
    chat_rag._metrics_write_failed_reported = False


async def _turn(monkeypatch, api=None, **kwargs):
    monkeypatch.setattr("memory.memory.api.v1.get_memory_api",
                        AsyncMock(return_value=api or _memory()))
    return await build_rag_context("anything", app_state=None, server_lang="en", **kwargs)


# ─── RAG_SEARCHES + RAG_SEARCH_DURATION ──────────────────────────────────────

class TestRagSearchMetrics:

    @pytest.mark.asyncio
    async def test_a_chat_turn_moves_both_series_for_every_system_source(self, monkeypatch):
        """The turn, through the three REAL system sources over a faked store:
        one search per source, one count and one observation per source."""
        from memory.memory.api.models import SearchResult

        api = _memory([SearchResult(id="1", score=0.9, collection=DOCS_COLLECTION,
                                    text="the manual says so")])
        names = (DOCS_COLLECTION, KNOWLEDGE_COLLECTION, MEMORY_COLLECTION)
        before = {n: (_sample(RAG_COUNT, {"source": n}),
                      _sample(RAG_DURATION_COUNT, {"source": n}),
                      _sample(RAG_DURATION_SUM, {"source": n})) for n in names}

        context, _ = await _turn(monkeypatch, api)

        assert "the manual says so" in context
        for n in names:
            labels = {"source": n}
            assert _sample(RAG_COUNT, labels) - before[n][0] == 1, (
                f"RAG_SEARCHES did not move for {n} — the metric is frozen again"
            )
            assert _sample(RAG_DURATION_COUNT, labels) - before[n][1] == 1
            assert _sample(RAG_DURATION_SUM, labels) - before[n][2] > 0, (
                "a search that took no measurable time means the timer is not around it"
            )

    @pytest.mark.asyncio
    async def test_the_label_is_the_source_that_answered(self, monkeypatch):
        """Both metrics take `source`; a search on one source must not land on
        another's series."""
        register_source(_FakeSource("test_1004_labelled"))
        other = {"source": MEMORY_COLLECTION}
        mine = {"source": "test_1004_labelled"}
        before_other = _sample(RAG_COUNT, other)

        await _turn(monkeypatch, collections=["test_1004_labelled"])

        assert _sample(RAG_COUNT, mine) == 1
        assert _sample(RAG_COUNT, other) == before_other

    @pytest.mark.asyncio
    async def test_a_failed_search_is_counted_too(self, monkeypatch):
        """The argued semantics of this finding, pinned so it cannot drift back.

        Both series carry `source` and no `status`, so failures cannot be told
        apart inside them. Dropping them would under-report load exactly when
        the backend is breaking, and would lose the slow timeouts a latency
        histogram exists for. The turn itself degrades to no context (#899).
        """
        source = _FakeSource("test_1004_failing", raises=RuntimeError("qdrant down"))
        register_source(source)
        labels = {"source": "test_1004_failing"}

        context, rag_items = await _turn(monkeypatch, collections=["test_1004_failing"])

        assert source.calls == 1
        assert (context, rag_items) == ("", [])
        assert _sample(RAG_COUNT, labels) == 1, "a failed search vanished from the counter"
        assert _sample(RAG_DURATION_COUNT, labels) == 1

    @pytest.mark.asyncio
    async def test_the_counter_and_the_histogram_never_disagree(self, monkeypatch):
        """`..._duration_seconds_count` == `..._searches_total` for the same
        label, whatever the mix of outcomes. A Prometheus reader assumes it."""
        labels = {"source": "test_1004_pair"}
        ok = _FakeSource("test_1004_pair")
        bad = _FakeSource("test_1004_pair", raises=ValueError("boom"))

        await _search_source(ok, _memory(), RAGQuery(text="a"))
        with pytest.raises(ValueError):
            await _search_source(bad, _memory(), RAGQuery(text="b"))
        await _search_source(ok, _memory(), RAGQuery(text="c"))

        assert _sample(RAG_COUNT, labels) == 3
        assert _sample(RAG_DURATION_COUNT, labels) == 3

    @pytest.mark.asyncio
    async def test_the_histogram_times_the_search(self, monkeypatch):
        """A source that takes 50 ms must show up as ~50 ms, not as ~0."""
        register_source(_FakeSource("test_1004_slow", delay=0.05))
        labels = {"source": "test_1004_slow"}

        await _turn(monkeypatch, collections=["test_1004_slow"])

        observed = _sample(RAG_DURATION_SUM, labels)
        assert observed >= 0.04, (
            f"observed {observed:.4f}s for a 50 ms search — the timer is not "
            "wrapped around the call"
        )

    @pytest.mark.asyncio
    async def test_a_source_the_turn_does_not_ask_is_not_counted(self, monkeypatch):
        """Counting is per source ASKED. A registered source the toggle left
        out must not get a series — it would put a search on the board that
        never happened."""
        asked = _FakeSource("test_1004_known")
        ghost = _FakeSource("test_1004_ghost")
        register_source(asked)
        register_source(ghost)

        await _turn(monkeypatch, collections=["test_1004_known"])

        assert ghost.calls == 0
        assert REGISTRY.get_sample_value(RAG_COUNT, {"source": "test_1004_ghost"}) is None
        assert _sample(RAG_COUNT, {"source": "test_1004_known"}) == 1

    @pytest.mark.asyncio
    async def test_search_survives_a_registry_that_is_not_there(self, monkeypatch):
        """The hard rule of this finding: instrumentation must never take the
        product path down with it."""
        monkeypatch.setattr(chat_rag, "RAG_SEARCHES", None)
        monkeypatch.setattr(chat_rag, "RAG_SEARCH_DURATION", None)
        source = _FakeSource("test_1004_nometrics", hits=[_Hit("still here")])
        register_source(source)

        context, _ = await _turn(monkeypatch, collections=["test_1004_nometrics"])

        assert "still here" in context
        assert source.calls == 1, "the search itself must still have happened"
        assert REGISTRY.get_sample_value(
            RAG_COUNT, {"source": "test_1004_nometrics"}
        ) is None

    @pytest.mark.asyncio
    async def test_the_cli_door_does_not_write_the_server_metrics(self, monkeypatch):
        """`RAGModule.search` (the CLI) asks the same source but runs in a
        process with no /metrics: the series are the SERVER's retrieval, and a
        write there would be the pre-E2 bug in reverse — a number moving for
        searches the chat never made. Guarded by a source that exists nowhere
        else, so any series under its name can only have come from this call."""
        from memory.rag.module import RAGModule

        source = _FakeSource("test_1004_cli", hits=[_Hit("from the cli")])
        register_source(source)
        monkeypatch.setattr("memory.memory.api.v1.get_memory_api",
                            AsyncMock(return_value=_memory()))
        module = RAGModule.__new__(RAGModule)
        module._initialized = True
        module._stats = {"searches_performed": 0}

        results = await module.search("q", source="test_1004_cli")

        assert [r.text for r in results] == ["from the cli"]
        assert REGISTRY.get_sample_value(RAG_COUNT, {"source": "test_1004_cli"}) is None


# ─── MEMORY_STORE_SIZE ───────────────────────────────────────────────────────

class TestMemoryStoreSizeGauge:
    """`count_documents` is the one place holding a real point count, so it is
    the one place that publishes the gauge."""

    def _qdrant(self, points_count):
        qdrant = MagicMock()
        info = MagicMock()
        info.points_count = points_count
        qdrant.get_collection = MagicMock(return_value=info)
        return qdrant

    async def _count(self, qdrant, collection: str):
        from memory.memory.api.documents import count_documents
        executor = ThreadPoolExecutor(max_workers=1)
        try:
            return await count_documents(qdrant, executor, collection)
        finally:
            executor.shutdown(wait=True)

    @pytest.mark.asyncio
    async def test_the_gauge_carries_the_real_point_count(self):
        result = await self._count(self._qdrant(7), "test_1004_store")
        assert result == 7
        assert _sample(STORE_SIZE, {"store_type": "test_1004_store"}) == 7

    @pytest.mark.asyncio
    async def test_the_gauge_follows_the_count_down(self):
        """A gauge, not a counter: it has to be able to fall. A size kept by
        deltas at the write sites could not do this — TTL expiry and bulk
        deletes never pass through them."""
        collection = "test_1004_shrink"
        await self._count(self._qdrant(10), collection)
        assert _sample(STORE_SIZE, {"store_type": collection}) == 10

        await self._count(self._qdrant(4), collection)
        assert _sample(STORE_SIZE, {"store_type": collection}) == 4

    @pytest.mark.asyncio
    async def test_each_collection_gets_its_own_series(self):
        await self._count(self._qdrant(3), "test_1004_col_a")
        await self._count(self._qdrant(9), "test_1004_col_b")
        assert _sample(STORE_SIZE, {"store_type": "test_1004_col_a"}) == 3
        assert _sample(STORE_SIZE, {"store_type": "test_1004_col_b"}) == 9

    @pytest.mark.asyncio
    async def test_a_null_point_count_is_not_published(self):
        """qdrant-client types `points_count` as Optional; `.set(None)` raises,
        and a raise here would turn a metric into a broken count call."""
        result = await self._count(self._qdrant(None), "test_1004_null")
        assert result is None
        assert REGISTRY.get_sample_value(
            STORE_SIZE, {"store_type": "test_1004_null"}
        ) is None


# ─── The write itself, not only the import (CRITICAL-1 of the phase-2 audit) ──

class TestInstrumentationCannotBreakASearch:
    """The `None` guard covers "the registry could not be imported". It does
    NOT cover "the registry is there and the write raises" — and because
    `_record_search_metrics` runs from a `finally`, an exception there does
    not add noise, it REPLACES the search's outcome.

    Measured on the code as first merged (then in `RAGModule.search`): a
    search that had already run, with its results in hand, came back as
    `ValueError: registry exploded`; and when the backend was the thing that
    failed, the caller was told about the metric instead, with
    `ConnectionError: qdrant is down` surviving only in `__context__`. In the
    chat that would mean a turn silently losing ALL its context because a
    counter misbehaved.
    """

    def _exploding(self, monkeypatch):
        """A metric that is present and raises when written to."""
        boom = MagicMock()
        boom.labels.side_effect = ValueError("registry exploded")
        monkeypatch.setattr(chat_rag, "RAG_SEARCHES", boom)
        monkeypatch.setattr(chat_rag, "RAG_SEARCH_DURATION", boom)

    @pytest.mark.asyncio
    async def test_a_search_that_ran_is_still_the_answer(self, monkeypatch):
        """End to end: the turn keeps its context although every write fails."""
        self._exploding(monkeypatch)
        source = _FakeSource("test_1004_boom", hits=[_Hit("the context survives")])
        register_source(source)

        context, rag_items = await _turn(monkeypatch, collections=["test_1004_boom"])

        assert source.calls == 1
        assert "the context survives" in context
        assert rag_items == [("test_1004_boom", 0.9)]

    @pytest.mark.asyncio
    async def test_the_real_failure_is_the_one_that_reaches_the_caller(self, monkeypatch):
        """The masking half. Whoever is on the other end has to be told the
        backend went down, not that a counter misbehaved."""
        self._exploding(monkeypatch)
        source = _FakeSource("test_1004_boom2", raises=ConnectionError("qdrant is down"))

        with pytest.raises(ConnectionError, match="qdrant is down"):
            await _search_source(source, _memory(), RAGQuery(text="q"))

    @pytest.mark.asyncio
    async def test_a_label_set_change_alone_cannot_take_the_search_down(self, monkeypatch):
        """The realistic trigger, with a REAL Counter rather than a double.

        Adding a `status` label to `RAG_SEARCHES` is this finding's own filed
        follow-up. It touches the registry and no search code, and it makes
        every `labels(source=...)` call raise `Incorrect label names`.
        """
        from prometheus_client import CollectorRegistry, Counter, Histogram

        registry = CollectorRegistry()
        counter = Counter("probe_searches_total", "probe", ["source", "status"],
                          registry=registry)
        histogram = Histogram("probe_duration_seconds", "probe", ["source"],
                              registry=registry)

        with pytest.raises(ValueError, match="[Ii]ncorrect label names"):
            counter.labels(source="x")     # the bug this test exists for

        monkeypatch.setattr(chat_rag, "RAG_SEARCHES", counter)
        monkeypatch.setattr(chat_rag, "RAG_SEARCH_DURATION", histogram)
        source = _FakeSource("test_1004_relabelled", hits=[_Hit("relabelled")])
        register_source(source)

        context, _ = await _turn(monkeypatch, collections=["test_1004_relabelled"])

        assert "relabelled" in context
        assert source.calls == 1

    @pytest.mark.asyncio
    async def test_the_failure_is_reported_once_and_says_what_goes_flat(self, monkeypatch, caplog):
        """Silence here would be #1005 again. Repeating it on every search
        would be #1005b again — what is lost is a pair of counters, a uniform
        loss one line describes in full, and the failure is deterministic."""
        self._exploding(monkeypatch)
        register_source(_FakeSource("test_1004_once"))

        with caplog.at_level(logging.WARNING, logger="core.endpoints.chat_rag"):
            for _ in range(5):
                await _turn(monkeypatch, collections=["test_1004_once"])

        failures = [r for r in caplog.records if "RAG metrics write failed" in r.getMessage()]
        assert len(failures) == 1, f"five failed writes, {len(failures)} lines"
        assert "registry exploded" in failures[0].getMessage()
        assert "stay flat" in failures[0].getMessage()

    @pytest.mark.asyncio
    async def test_a_healthy_registry_reports_nothing(self, monkeypatch, caplog):
        """Control: the whole mechanism lives inside the handler."""
        register_source(_FakeSource("test_1004_quiet"))
        with caplog.at_level(logging.WARNING, logger="core.endpoints.chat_rag"):
            await _turn(monkeypatch, collections=["test_1004_quiet"])

        assert [r for r in caplog.records if "RAG metrics write failed" in r.getMessage()] == []
        assert _sample(RAG_COUNT, {"source": "test_1004_quiet"}) == 1
