"""Tests for memory/memory/metrics.py — coverage gaps."""
import time
from unittest.mock import MagicMock


class TestMemoryMetrics:
    def test_inc_counter(self):
        from memory.memory.metrics import MemoryMetrics
        m = MemoryMetrics()
        m.inc_counter("memory_ingested_total", 5)
        metrics = m.get_metrics()
        assert metrics["counters"]["memory_ingested_total"] == 5

    def test_inc_counter_unknown(self):
        from memory.memory.metrics import MemoryMetrics
        m = MemoryMetrics()
        m.inc_counter("nonexistent_counter")

    def test_set_gauge(self):
        from memory.memory.metrics import MemoryMetrics
        m = MemoryMetrics()
        m.set_gauge("memory_flash_size", 42)
        metrics = m.get_metrics()
        assert metrics["gauges"]["memory_flash_size"] == 42

    def test_set_gauge_unknown(self):
        from memory.memory.metrics import MemoryMetrics
        m = MemoryMetrics()
        m.set_gauge("nonexistent_gauge", 1)

    def test_observe_histogram(self):
        from memory.memory.metrics import MemoryMetrics
        m = MemoryMetrics()
        m.observe_histogram("memory_ingestion_duration_seconds", 0.5)
        metrics = m.get_metrics()
        assert metrics["histograms"]["memory_ingestion_duration_seconds"]["count"] == 1
        assert metrics["histograms"]["memory_ingestion_duration_seconds"]["avg"] == 0.5

    def test_observe_histogram_unknown(self):
        from memory.memory.metrics import MemoryMetrics
        m = MemoryMetrics()
        m.observe_histogram("nonexistent", 1.0)

    def test_get_metrics_empty_histogram(self):
        from memory.memory.metrics import MemoryMetrics
        m = MemoryMetrics()
        metrics = m.get_metrics()
        hist = metrics["histograms"]["memory_ingestion_duration_seconds"]
        assert hist["count"] == 0
        assert hist["avg"] == 0.0

    def test_record_ingestion_duration(self):
        from memory.memory.metrics import MemoryMetrics
        m = MemoryMetrics()
        m.record_ingestion_duration(1.5)
        metrics = m.get_metrics()
        assert metrics["histograms"]["memory_ingestion_duration_seconds"]["max"] == 1.5

    def test_reset(self):
        from memory.memory.metrics import MemoryMetrics
        m = MemoryMetrics()
        m.inc_counter("memory_ingested_total", 10)
        m.set_gauge("memory_flash_size", 50)
        m.observe_histogram("memory_ingestion_duration_seconds", 2.0)
        m.reset()
        metrics = m.get_metrics()
        assert metrics["counters"]["memory_ingested_total"] == 0
        assert metrics["gauges"]["memory_flash_size"] == 0
        assert metrics["histograms"]["memory_ingestion_duration_seconds"]["count"] == 0

    def test_update_from_module_not_initialized(self):
        from memory.memory.metrics import MemoryMetrics
        m = MemoryMetrics()
        mock_module = MagicMock()
        mock_module._initialized = False
        m.update_from_module(mock_module)

    def test_update_from_module_with_flash(self):
        from memory.memory.metrics import MemoryMetrics
        m = MemoryMetrics()
        mock_module = MagicMock()
        mock_module._initialized = True
        mock_module._flash_memory._store = [1, 2, 3]
        mock_module._ram_context = None
        mock_module._pipeline = None
        mock_module._persistence = None
        m.update_from_module(mock_module)
        metrics = m.get_metrics()
        assert metrics["gauges"]["memory_flash_size"] == 3


class TestMetricsTimer:
    def test_context_manager(self):
        from memory.memory.metrics import MemoryMetrics, MetricsTimer
        m = MemoryMetrics()
        with MetricsTimer(m, "memory_ingestion_duration_seconds"):
            time.sleep(0.001)
        metrics = m.get_metrics()
        assert metrics["histograms"]["memory_ingestion_duration_seconds"]["count"] == 1


class TestGetMetricsSingleton:
    def test_returns_instance(self):
        from memory.memory.metrics import get_metrics, MemoryMetrics
        m = get_metrics()
        assert isinstance(m, MemoryMetrics)

    def test_returns_same_instance(self):
        from memory.memory.metrics import get_metrics
        m1 = get_metrics()
        m2 = get_metrics()
        assert m1 is m2
