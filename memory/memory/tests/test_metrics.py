"""
────────────────────────────────────
Server Nexe
Version: 0.8
Author: Jordi Goy
Location: memory/memory/tests/test_metrics.py
Description: Tests per memory/memory/metrics.py.

www.jgoy.net · https://server-nexe.org
────────────────────────────────────
"""

import time
import threading
import pytest
from unittest.mock import MagicMock


@pytest.fixture(autouse=True)
def reset_global_metrics():
    """Reset global metrics singleton between tests."""
    import memory.memory.metrics as m
    m._metrics_instance = None
    yield
    m._metrics_instance = None


class TestMemoryMetricsInit:

    def test_creates_counters(self):
        from memory.memory.metrics import MemoryMetrics
        m = MemoryMetrics()
        assert "memory_ingested_total" in m._counters
        assert "memory_duplicates_total" in m._counters
        assert "memory_failures_total" in m._counters
        assert "memory_cleanups_total" in m._counters

    def test_creates_gauges(self):
        from memory.memory.metrics import MemoryMetrics
        m = MemoryMetrics()
        assert "memory_flash_size" in m._gauges
        assert "memory_ram_context_size" in m._gauges
        assert "memory_persistence_entries" in m._gauges

    def test_creates_histograms(self):
        from memory.memory.metrics import MemoryMetrics
        m = MemoryMetrics()
        assert "memory_ingestion_duration_seconds" in m._histograms


class TestIncCounter:

    def test_increments_known_counter(self):
        from memory.memory.metrics import MemoryMetrics
        m = MemoryMetrics()
        m.inc_counter("memory_ingested_total")
        assert m._counters["memory_ingested_total"] == 1

    def test_increments_by_value(self):
        from memory.memory.metrics import MemoryMetrics
        m = MemoryMetrics()
        m.inc_counter("memory_ingested_total", 5)
        assert m._counters["memory_ingested_total"] == 5

    def test_ignores_unknown_counter(self):
        from memory.memory.metrics import MemoryMetrics
        m = MemoryMetrics()
        m.inc_counter("nonexistent_counter")  # Should not raise


class TestSetGauge:

    def test_sets_known_gauge(self):
        from memory.memory.metrics import MemoryMetrics
        m = MemoryMetrics()
        m.set_gauge("memory_flash_size", 42.0)
        assert m._gauges["memory_flash_size"] == 42.0

    def test_ignores_unknown_gauge(self):
        from memory.memory.metrics import MemoryMetrics
        m = MemoryMetrics()
        m.set_gauge("nonexistent_gauge", 1.0)  # Should not raise


class TestObserveHistogram:

    def test_appends_value(self):
        from memory.memory.metrics import MemoryMetrics
        m = MemoryMetrics()
        m.observe_histogram("memory_ingestion_duration_seconds", 0.5)
        assert 0.5 in m._histograms["memory_ingestion_duration_seconds"]

    def test_ignores_unknown_histogram(self):
        from memory.memory.metrics import MemoryMetrics
        m = MemoryMetrics()
        m.observe_histogram("nonexistent_histogram", 1.0)  # Should not raise


class TestGetMetrics:

    def test_returns_all_metric_types(self):
        from memory.memory.metrics import MemoryMetrics
        m = MemoryMetrics()
        result = m.get_metrics()
        assert "counters" in result
        assert "gauges" in result
        assert "histograms" in result

    def test_histogram_stats_when_empty(self):
        from memory.memory.metrics import MemoryMetrics
        m = MemoryMetrics()
        result = m.get_metrics()
        hist = result["histograms"]["memory_ingestion_duration_seconds"]
        assert hist["count"] == 0
        assert hist["sum"] == 0.0

    def test_histogram_stats_with_values(self):
        from memory.memory.metrics import MemoryMetrics
        m = MemoryMetrics()
        m.observe_histogram("memory_ingestion_duration_seconds", 0.1)
        m.observe_histogram("memory_ingestion_duration_seconds", 0.3)
        result = m.get_metrics()
        hist = result["histograms"]["memory_ingestion_duration_seconds"]
        assert hist["count"] == 2
        assert abs(hist["avg"] - 0.2) < 0.001
        assert hist["min"] == 0.1
        assert hist["max"] == 0.3


class TestUpdateFromModule:

    def test_skips_if_not_initialized(self):
        from memory.memory.metrics import MemoryMetrics
        m = MemoryMetrics()
        mock_module = MagicMock()
        mock_module._initialized = False
        m.update_from_module(mock_module)
        # Gauge should not be updated
        assert m._gauges["memory_flash_size"] == 0

    def test_updates_flash_size(self):
        from memory.memory.metrics import MemoryMetrics
        m = MemoryMetrics()

        mock_flash = MagicMock()
        mock_flash._store = {"a": 1, "b": 2, "c": 3}

        mock_module = MagicMock()
        mock_module._initialized = True
        mock_module._flash_memory = mock_flash
        mock_module._ram_context = None
        mock_module._pipeline = None
        mock_module._persistence = None

        m.update_from_module(mock_module)
        assert m._gauges["memory_flash_size"] == 3

    def test_updates_pipeline_stats(self):
        from memory.memory.metrics import MemoryMetrics
        m = MemoryMetrics()

        mock_flash = MagicMock()
        mock_flash._store = {}

        mock_pipeline = MagicMock()
        mock_pipeline.get_stats.return_value = {
            "total_ingested": 10,
            "duplicates_skipped": 2,
            "failures": 1
        }

        mock_module = MagicMock()
        mock_module._initialized = True
        mock_module._flash_memory = mock_flash
        mock_module._ram_context = None
        mock_module._pipeline = mock_pipeline
        mock_module._persistence = None

        m.update_from_module(mock_module)

        assert m._counters["memory_ingested_total"] == 10
        assert m._counters["memory_duplicates_total"] == 2
        assert m._counters["memory_failures_total"] == 1

    def test_handles_exception_gracefully(self):
        from memory.memory.metrics import MemoryMetrics
        m = MemoryMetrics()
        mock_module = MagicMock()
        mock_module._initialized = True
        mock_module._flash_memory = MagicMock(side_effect=Exception("boom"))
        # Should not raise
        m.update_from_module(mock_module)


class TestRecordIngestionDuration:

    def test_records_duration(self):
        from memory.memory.metrics import MemoryMetrics
        m = MemoryMetrics()
        m.record_ingestion_duration(0.42)
        assert 0.42 in m._histograms["memory_ingestion_duration_seconds"]


class TestReset:

    def test_resets_all_counters(self):
        from memory.memory.metrics import MemoryMetrics
        m = MemoryMetrics()
        m.inc_counter("memory_ingested_total", 10)
        m.reset()
        assert m._counters["memory_ingested_total"] == 0

    def test_resets_gauges(self):
        from memory.memory.metrics import MemoryMetrics
        m = MemoryMetrics()
        m.set_gauge("memory_flash_size", 99)
        m.reset()
        assert m._gauges["memory_flash_size"] == 0

    def test_resets_histograms(self):
        from memory.memory.metrics import MemoryMetrics
        m = MemoryMetrics()
        m.observe_histogram("memory_ingestion_duration_seconds", 1.0)
        m.reset()
        assert m._histograms["memory_ingestion_duration_seconds"] == []


class TestMetricsTimer:

    def test_records_duration_on_exit(self):
        from memory.memory.metrics import MemoryMetrics, MetricsTimer
        m = MemoryMetrics()
        with MetricsTimer(m, "memory_ingestion_duration_seconds"):
            time.sleep(0.01)

        values = m._histograms["memory_ingestion_duration_seconds"]
        assert len(values) == 1
        assert values[0] >= 0.01

    def test_returns_false_to_not_suppress_exceptions(self):
        from memory.memory.metrics import MemoryMetrics, MetricsTimer
        m = MemoryMetrics()
        timer = MetricsTimer(m, "memory_ingestion_duration_seconds")
        timer.__enter__()
        result = timer.__exit__(None, None, None)
        assert result is False


class TestGetMetricsSingleton:

    def test_returns_same_instance(self):
        from memory.memory.metrics import get_metrics
        m1 = get_metrics()
        m2 = get_metrics()
        assert m1 is m2

    def test_thread_safe(self):
        from memory.memory.metrics import get_metrics
        instances = []

        def get():
            instances.append(get_metrics())

        threads = [threading.Thread(target=get) for _ in range(10)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert all(i is instances[0] for i in instances)
