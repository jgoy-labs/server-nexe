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

             These tests assert the values MOVE, not that the metrics exist —
             existence was never the problem. Every assertion is a delta
             against the value read before the call, because the registry is
             process-global and the rest of the suite shares it.
────────────────────────────────────
"""

from __future__ import annotations

import asyncio
from concurrent.futures import ThreadPoolExecutor
from typing import Any
from unittest.mock import MagicMock

import pytest
from prometheus_client import REGISTRY

from memory.rag.module import RAGModule
from memory.rag_sources.base import AddDocumentRequest, SearchRequest

RAG_COUNT = "core_rag_searches_total"
RAG_DURATION_COUNT = "core_rag_search_duration_seconds_count"
RAG_DURATION_SUM = "core_rag_search_duration_seconds_sum"
STORE_SIZE = "core_memory_store_size"


def _sample(name: str, labels: dict[str, str]) -> float:
    """Current value of one series. A label pair never touched reads as 0."""
    value = REGISTRY.get_sample_value(name, labels)
    return 0.0 if value is None else float(value)


class _FakeSource:
    """A RAG source that answers however the test needs it to."""

    def __init__(self, *, raises: Exception | None = None, delay: float = 0.0):
        self._raises = raises
        self._delay = delay
        self.calls = 0

    async def search(self, request: Any) -> list:
        self.calls += 1
        if self._delay:
            await asyncio.sleep(self._delay)
        if self._raises is not None:
            raise self._raises
        return []


def _module_with(source_name: str, source: Any) -> RAGModule:
    """A RAGModule wired to one source, without touching the singleton.

    `__new__` skips `__init__`, which refuses to run while an instance exists —
    the real constructor is exercised by tests/memory/rag/test_module_integration.
    """
    module = RAGModule.__new__(RAGModule)
    module._initialized = True
    module._sources = {source_name: source}
    module._stats = {"searches_performed": 0, "documents_added": 0}
    return module


# ─── RAG_SEARCHES + RAG_SEARCH_DURATION ──────────────────────────────────────

@pytest.fixture
def clean_rag_module():
    """The real module, real PersonalityRAG. Same shape as the fixture in
    tests/memory/rag/test_module_integration.py."""
    RAGModule._instance = None
    RAGModule._initialized = False
    yield RAGModule.get_instance()
    RAGModule._instance = None
    RAGModule._initialized = False


class TestRagSearchMetrics:

    @pytest.mark.asyncio
    async def test_a_real_search_moves_both_series(self, clean_rag_module):
        """End to end through the real source, no doubles: one search in, one
        count and one observation out."""
        module = clean_rag_module
        await module.initialize()
        await module.add_document(AddDocumentRequest(
            text="Python is a high-level programming language with clear syntax.",
            metadata={},
        ))

        labels = {"source": "personality"}
        before_n = _sample(RAG_COUNT, labels)
        before_d = _sample(RAG_DURATION_COUNT, labels)
        before_s = _sample(RAG_DURATION_SUM, labels)

        await module.search(SearchRequest(query="programming language", top_k=3))

        assert _sample(RAG_COUNT, labels) - before_n == 1, (
            "RAG_SEARCHES did not move — the metric is frozen again"
        )
        assert _sample(RAG_DURATION_COUNT, labels) - before_d == 1
        assert _sample(RAG_DURATION_SUM, labels) - before_s > 0, (
            "a search that took no measurable time means the timer is not around it"
        )

    @pytest.mark.asyncio
    async def test_the_label_is_the_source_that_answered(self):
        """Both metrics take `source`; a search on one source must not land on
        another's series."""
        module = _module_with("test_1004_labelled", _FakeSource())
        other = {"source": "personality"}
        mine = {"source": "test_1004_labelled"}
        before_other = _sample(RAG_COUNT, other)

        await module.search(SearchRequest(query="q", top_k=1),
                            source="test_1004_labelled")

        assert _sample(RAG_COUNT, mine) == 1
        assert _sample(RAG_COUNT, other) == before_other

    @pytest.mark.asyncio
    async def test_a_failed_search_is_counted_too(self):
        """The argued semantics of this finding, pinned so it cannot drift back.

        Both series carry `source` and no `status`, so failures cannot be told
        apart inside them. Dropping them would under-report load exactly when
        the backend is breaking, and would lose the slow timeouts a latency
        histogram exists for. The failure still propagates.
        """
        source = _FakeSource(raises=RuntimeError("qdrant down"))
        module = _module_with("test_1004_failing", source)
        labels = {"source": "test_1004_failing"}

        with pytest.raises(RuntimeError, match="qdrant down"):
            await module.search(SearchRequest(query="q", top_k=1),
                                source="test_1004_failing")

        assert _sample(RAG_COUNT, labels) == 1, "a failed search vanished from the counter"
        assert _sample(RAG_DURATION_COUNT, labels) == 1
        assert module._stats["searches_performed"] == 0, (
            "the module's own stat counts successes only — that difference is "
            "deliberate and documented in _record_search_metrics"
        )

    @pytest.mark.asyncio
    async def test_the_counter_and_the_histogram_never_disagree(self):
        """`..._duration_seconds_count` == `..._searches_total` for the same
        label, whatever the mix of outcomes. A Prometheus reader assumes it."""
        ok = _FakeSource()
        bad = _FakeSource(raises=ValueError("boom"))
        labels = {"source": "test_1004_pair"}

        module_ok = _module_with("test_1004_pair", ok)
        module_bad = _module_with("test_1004_pair", bad)
        await module_ok.search(SearchRequest(query="a", top_k=1), source="test_1004_pair")
        with pytest.raises(ValueError):
            await module_bad.search(SearchRequest(query="b", top_k=1), source="test_1004_pair")
        await module_ok.search(SearchRequest(query="c", top_k=1), source="test_1004_pair")

        assert _sample(RAG_COUNT, labels) == 3
        assert _sample(RAG_DURATION_COUNT, labels) == 3

    @pytest.mark.asyncio
    async def test_the_histogram_times_the_search_and_not_the_guards(self):
        """A source that takes 50 ms must show up as ~50 ms, not as ~0."""
        module = _module_with("test_1004_slow", _FakeSource(delay=0.05))
        labels = {"source": "test_1004_slow"}

        await module.search(SearchRequest(query="q", top_k=1), source="test_1004_slow")

        observed = _sample(RAG_DURATION_SUM, labels)
        assert observed >= 0.04, (
            f"observed {observed:.4f}s for a 50 ms search — the timer is not "
            "wrapped around the call"
        )

    @pytest.mark.asyncio
    async def test_the_argument_guards_are_not_counted(self):
        """An unknown source raises before anything is searched; counting it
        would put a series on the board for a source that does not exist."""
        module = _module_with("test_1004_known", _FakeSource())

        with pytest.raises(ValueError, match="Unknown RAG source"):
            await module.search(SearchRequest(query="q", top_k=1),
                                source="test_1004_ghost")

        assert REGISTRY.get_sample_value(RAG_COUNT, {"source": "test_1004_ghost"}) is None

    @pytest.mark.asyncio
    async def test_search_survives_a_registry_that_is_not_there(self, monkeypatch):
        """The hard rule of this finding: instrumentation must never take the
        product path down with it."""
        monkeypatch.setattr("memory.rag.module.RAG_SEARCHES", None)
        monkeypatch.setattr("memory.rag.module.RAG_SEARCH_DURATION", None)
        source = _FakeSource()
        module = _module_with("test_1004_nometrics", source)

        results = await module.search(SearchRequest(query="q", top_k=1),
                                      source="test_1004_nometrics")

        assert results == []
        assert source.calls == 1, "the search itself must still have happened"
        assert REGISTRY.get_sample_value(
            RAG_COUNT, {"source": "test_1004_nometrics"}
        ) is None


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
    `_record_search_metrics` runs from the `finally` of `search()`, an
    exception there does not add noise, it REPLACES the search's outcome.

    Measured on the code as first merged: a search that had already run, with
    its results in hand, came back as `ValueError: registry exploded`; and when
    the backend was the thing that failed, the caller was told about the metric
    instead, with `ConnectionError: qdrant is down` surviving only in
    `__context__`, where no HTTP body ever looks.
    """

    @pytest.fixture(autouse=True)
    def _forget_the_one_shot(self):
        import memory.rag.module as rag
        rag._metrics_write_failed_reported = False
        yield
        rag._metrics_write_failed_reported = False

    def _exploding(self, monkeypatch):
        """A metric that is present and raises when written to."""
        from unittest.mock import MagicMock
        boom = MagicMock()
        boom.labels.side_effect = ValueError("registry exploded")
        monkeypatch.setattr("memory.rag.module.RAG_SEARCHES", boom)
        monkeypatch.setattr("memory.rag.module.RAG_SEARCH_DURATION", boom)

    @pytest.mark.asyncio
    async def test_a_search_that_ran_is_still_the_answer(self, monkeypatch):
        self._exploding(monkeypatch)
        source = _FakeSource()
        module = _module_with("test_1004_boom", source)

        results = await module.search(SearchRequest(query="q", top_k=1),
                                      source="test_1004_boom")

        assert results == []
        assert source.calls == 1
        assert module._stats["searches_performed"] == 1

    @pytest.mark.asyncio
    async def test_the_real_failure_is_the_one_that_reaches_the_caller(self, monkeypatch):
        """The masking half. Whoever is on the other end has to be told the
        backend went down, not that a counter misbehaved."""
        self._exploding(monkeypatch)
        module = _module_with(
            "test_1004_boom2", _FakeSource(raises=ConnectionError("qdrant is down")),
        )

        with pytest.raises(ConnectionError, match="qdrant is down"):
            await module.search(SearchRequest(query="q", top_k=1),
                                source="test_1004_boom2")

    @pytest.mark.asyncio
    async def test_a_label_set_change_alone_cannot_take_the_search_down(self):
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

        import memory.rag.module as rag
        rag._metrics_write_failed_reported = False
        _prev = (rag.RAG_SEARCHES, rag.RAG_SEARCH_DURATION)
        rag.RAG_SEARCHES, rag.RAG_SEARCH_DURATION = counter, histogram
        try:
            source = _FakeSource()
            module = _module_with("test_1004_relabelled", source)
            results = await module.search(SearchRequest(query="q", top_k=1),
                                          source="test_1004_relabelled")
        finally:
            rag.RAG_SEARCHES, rag.RAG_SEARCH_DURATION = _prev
            rag._metrics_write_failed_reported = False

        assert results == []
        assert source.calls == 1

    @pytest.mark.asyncio
    async def test_the_failure_is_reported_once_and_says_what_goes_flat(self, monkeypatch):
        """Silence here would be #1005 again. Repeating it on every search
        would be #1005b again — what is lost is a pair of counters, a uniform
        loss one line describes in full, and the failure is deterministic."""
        from structlog.testing import capture_logs

        self._exploding(monkeypatch)
        module = _module_with("test_1004_once", _FakeSource())

        with capture_logs() as logs:
            for _ in range(5):
                await module.search(SearchRequest(query="q", top_k=1),
                                    source="test_1004_once")

        failures = [e for e in logs if e.get("event") == "rag_metrics_write_failed"]
        assert len(failures) == 1, f"five failed writes, {len(failures)} lines: {failures}"
        assert "registry exploded" in failures[0]["error"]
        assert "stay flat" in failures[0]["impact"]

    @pytest.mark.asyncio
    async def test_a_healthy_registry_reports_nothing(self, monkeypatch):
        """Control: the whole mechanism lives inside the handler."""
        from structlog.testing import capture_logs

        module = _module_with("test_1004_quiet", _FakeSource())
        with capture_logs() as logs:
            await module.search(SearchRequest(query="q", top_k=1),
                                source="test_1004_quiet")

        assert [e for e in logs if e.get("event") == "rag_metrics_write_failed"] == []
        assert _sample(RAG_COUNT, {"source": "test_1004_quiet"}) == 1
