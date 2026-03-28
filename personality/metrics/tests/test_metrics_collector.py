"""
────────────────────────────────────
Server Nexe
Author: Jordi Goy 
Location: personality/metrics/tests/test_metrics_collector.py
Description: Tests per MetricsCollector. Valida recol·lecció de mètriques,

www.jgoy.net · https://server-nexe.org
────────────────────────────────────
"""

import pytest
from pathlib import Path
from datetime import datetime, timezone
from unittest.mock import MagicMock, patch
import time

from personality.metrics.metrics_collector import MetricsCollector
from personality.data.models import ModuleInfo, ModuleState

class TestMetricsCollectorInit:
  """Tests for MetricsCollector initialization."""

  def test_init_default(self):
    """Should initialize with defaults."""
    collector = MetricsCollector()

    assert collector.i18n is None
    assert collector._max_history == 1000
    assert len(collector._metrics_history) == 0
    assert len(collector._custom_metrics) == 0

  def test_init_with_i18n(self):
    """Should store i18n manager."""
    mock_i18n = MagicMock()
    collector = MetricsCollector(i18n_manager=mock_i18n)

    assert collector.i18n == mock_i18n

  def test_init_sets_start_time(self):
    """Should set system start time."""
    before = datetime.now(timezone.utc)
    collector = MetricsCollector()
    after = datetime.now(timezone.utc)

    assert before <= collector._system_start_time <= after

class TestMetricsCollectorMessages:
  """Tests for message handling."""

  def test_get_message_with_i18n(self):
    """Should use i18n for translations."""
    mock_i18n = MagicMock()
    mock_i18n.t.return_value = "Translated"
    collector = MetricsCollector(i18n_manager=mock_i18n)

    result = collector._get_message('metrics.updated', module='test')

    assert result == "Translated"
    mock_i18n.t.assert_called_once()

  def test_get_message_fallback(self):
    """Should use fallback without i18n."""
    collector = MetricsCollector()

    result = collector._get_message('metrics.updated', module='test')

    assert "test" in result

class TestMetricsCollectorUpdateModule:
  """Tests for update_module_metrics."""

  @pytest.fixture
  def collector(self):
    return MetricsCollector()

  @pytest.fixture
  def mock_module(self):
    module = MagicMock(spec=ModuleInfo)
    module.name = "test_module"
    module.memory_usage_mb = 0
    module.cpu_usage = 0
    module.api_calls = 0
    return module

  def test_update_existing_module(self, collector, mock_module):
    """Should update metrics for existing module."""
    modules = {"test_module": mock_module}

    collector.update_module_metrics(modules, "test_module", cpu_usage=50.0)

    assert mock_module.cpu_usage == 50.0

  def test_update_nonexistent_module(self, collector):
    """Should handle non-existent module gracefully."""
    modules = {}

    collector.update_module_metrics(modules, "nonexistent", cpu_usage=50.0)

  def test_update_sets_last_activity(self, collector, mock_module):
    """Should update last_activity timestamp."""
    modules = {"test_module": mock_module}
    before = datetime.now(timezone.utc)

    collector.update_module_metrics(modules, "test_module")

    assert mock_module.last_activity >= before

class TestMetricsCollectorSystemMetrics:
  """Tests for get_system_metrics."""

  @pytest.fixture
  def collector(self):
    return MetricsCollector()

  def test_system_metrics_empty_modules(self, collector):
    """Should handle empty modules dict."""
    metrics = collector.get_system_metrics({})

    assert metrics.total_modules == 0
    assert metrics.running_modules == 0
    assert metrics.total_memory_mb == 0

  def test_system_metrics_with_modules(self, collector):
    """Should calculate metrics from modules."""
    module1 = MagicMock(spec=ModuleInfo)
    module1.state = ModuleState.RUNNING
    module1.memory_usage_mb = 100
    module1.cpu_usage = 25
    module1.api_calls = 50
    module1.error_count = 0
    module1.load_duration_ms = 100

    module2 = MagicMock(spec=ModuleInfo)
    module2.state = ModuleState.RUNNING
    module2.memory_usage_mb = 200
    module2.cpu_usage = 75
    module2.api_calls = 100
    module2.error_count = 1
    module2.load_duration_ms = 200

    modules = {"mod1": module1, "mod2": module2}

    metrics = collector.get_system_metrics(modules)

    assert metrics.total_modules == 2
    assert metrics.running_modules == 2
    assert metrics.total_memory_mb == 300
    assert metrics.average_cpu_usage == 50
    assert metrics.total_api_calls == 150
    assert metrics.modules_with_errors == 1

  def test_system_metrics_stores_history(self, collector):
    """Should store metrics in history."""
    collector.get_system_metrics({})
    collector.get_system_metrics({})

    assert len(collector._metrics_history) == 2

  def test_system_metrics_trims_history(self, collector):
    """Should trim history when exceeding max."""
    collector._max_history = 5

    for _ in range(10):
      collector.get_system_metrics({})

    assert len(collector._metrics_history) == 5

class TestMetricsCollectorModuleMetrics:
  """Tests for get_module_metrics."""

  def test_module_metrics(self):
    """Should return module metrics dict."""
    module = MagicMock(spec=ModuleInfo)
    module.name = "test"
    module.state = ModuleState.RUNNING
    module.memory_usage_mb = 100
    module.cpu_usage = 50
    module.api_calls = 10
    module.error_count = 1
    module.load_duration_ms = 100
    module.start_duration_ms = 50
    module.last_activity = datetime.now(timezone.utc)
    module.enabled = True
    module.priority = 10
    module.dependencies = []
    module.provides = {"feature1"}

    collector = MetricsCollector()

    with patch('personality.data.models.calculate_module_uptime', return_value=100):
      metrics = collector.get_module_metrics(module)

    assert metrics["name"] == "test"
    assert metrics["state"] == "running"
    assert metrics["memory_usage_mb"] == 100
    assert metrics["enabled"] is True

class TestMetricsCollectorHistory:
  """Tests for metrics history."""

  @pytest.fixture
  def collector(self):
    return MetricsCollector()

  def test_get_metrics_history_empty(self, collector):
    """Should return empty list initially."""
    history = collector.get_metrics_history()

    assert history == []

  def test_get_metrics_history_with_limit(self, collector):
    """Should respect limit parameter."""
    for _ in range(10):
      collector.get_system_metrics({})

    history = collector.get_metrics_history(limit=5)

    assert len(history) == 5

  def test_get_metrics_history_format(self, collector):
    """Should return dict format."""
    collector.get_system_metrics({})

    history = collector.get_metrics_history()

    assert len(history) == 1
    assert "timestamp" in history[0]
    assert "total_modules" in history[0]

  def test_clear_metrics_history(self, collector):
    """Should clear history."""
    for _ in range(5):
      collector.get_system_metrics({})

    count = collector.clear_metrics_history()

    assert count == 5
    assert len(collector._metrics_history) == 0

class TestMetricsCollectorPerformanceSummary:
  """Tests for get_performance_summary."""

  @pytest.fixture
  def collector(self):
    return MetricsCollector()

  def test_performance_summary_no_running(self, collector):
    """Should indicate no running modules."""
    module = MagicMock(spec=ModuleInfo)
    module.state = ModuleState.LOADED

    summary = collector.get_performance_summary({"mod": module})

    assert summary["status"] == "no_running_modules"

  def test_performance_summary_with_modules(self, collector):
    """Should calculate performance summary."""
    module1 = MagicMock(spec=ModuleInfo)
    module1.state = ModuleState.RUNNING
    module1.memory_usage_mb = 100
    module1.cpu_usage = 25
    module1.api_calls = 50
    module1.error_count = 0
    module1.load_duration_ms = 100
    module1.start_duration_ms = 50

    module2 = MagicMock(spec=ModuleInfo)
    module2.state = ModuleState.RUNNING
    module2.memory_usage_mb = 200
    module2.cpu_usage = 75
    module2.api_calls = 100
    module2.error_count = 1
    module2.load_duration_ms = 200
    module2.start_duration_ms = 100

    modules = {"mod1": module1, "mod2": module2}

    summary = collector.get_performance_summary(modules)

    assert summary["total_running"] == 2
    assert summary["load_performance"]["min_ms"] == 100
    assert summary["load_performance"]["max_ms"] == 200
    assert summary["resource_usage"]["total_memory_mb"] == 300
    assert summary["error_rate"] == 50.0

class TestMetricsCollectorCustomMetrics:
  """Tests for custom metrics."""

  @pytest.fixture
  def collector(self):
    return MetricsCollector()

  def test_set_custom_metric(self, collector):
    """Should set custom metric."""
    collector.set_custom_metric("test_key", "test_value")

    assert collector._custom_metrics["test_key"] == "test_value"

  def test_get_custom_metric(self, collector):
    """Should get custom metric."""
    collector._custom_metrics["test_key"] = "test_value"

    result = collector.get_custom_metric("test_key")

    assert result == "test_value"

  def test_get_custom_metric_default(self, collector):
    """Should return default for missing metric."""
    result = collector.get_custom_metric("missing", "default")

    assert result == "default"

  def test_get_all_custom_metrics(self, collector):
    """Should return copy of all metrics."""
    collector._custom_metrics = {"key1": "val1", "key2": "val2"}

    result = collector.get_all_custom_metrics()

    assert result == {"key1": "val1", "key2": "val2"}
    assert result is not collector._custom_metrics

  def test_remove_custom_metric_existing(self, collector):
    """Should remove existing metric."""
    collector._custom_metrics["test"] = "value"

    result = collector.remove_custom_metric("test")

    assert result is True
    assert "test" not in collector._custom_metrics

  def test_remove_custom_metric_missing(self, collector):
    """Should return False for missing metric."""
    result = collector.remove_custom_metric("missing")

    assert result is False

class TestMetricsCollectorHistoryConfig:
  """Tests for history configuration."""

  @pytest.fixture
  def collector(self):
    return MetricsCollector()

  def test_set_max_history(self, collector):
    """Should set max history size."""
    collector.set_max_history(500)

    assert collector._max_history == 500

  def test_set_max_history_trims(self, collector):
    """Should trim history when reducing max."""
    for _ in range(10):
      collector.get_system_metrics({})

    collector.set_max_history(5)

    assert len(collector._metrics_history) == 5

  def test_set_max_history_minimum(self, collector):
    """Should enforce minimum of 1."""
    collector.set_max_history(0)

    assert collector._max_history == 1

class TestMetricsCollectorUptime:
  """Tests for uptime tracking."""

  def test_get_system_uptime(self):
    """Should calculate uptime."""
    collector = MetricsCollector()
    time.sleep(0.01)

    uptime = collector.get_system_uptime()

    assert uptime > 0

  def test_reset_system_start_time(self):
    """Should reset start time."""
    collector = MetricsCollector()
    time.sleep(0.01)
    old_start = collector._system_start_time

    collector.reset_system_start_time()

    assert collector._system_start_time > old_start

class TestMetricsCollectorStats:
  """Tests for get_metrics_stats."""

  def test_get_metrics_stats(self):
    """Should return collector statistics."""
    collector = MetricsCollector()
    collector.get_system_metrics({})
    collector.set_custom_metric("test", "value")

    stats = collector.get_metrics_stats()

    assert stats["history_size"] == 1
    assert stats["max_history"] == 1000
    assert stats["custom_metrics_count"] == 1
    assert "system_uptime_seconds" in stats
    assert "system_start_time" in stats

class TestMetricsCollectorStatesBreakdown:
  """Tests for states breakdown."""

  def test_states_breakdown(self):
    """Should count modules by state."""
    collector = MetricsCollector()

    module1 = MagicMock(spec=ModuleInfo)
    module1.state = ModuleState.RUNNING
    module1.memory_usage_mb = 0
    module1.cpu_usage = 0
    module1.api_calls = 0
    module1.error_count = 0
    module1.load_duration_ms = None

    module2 = MagicMock(spec=ModuleInfo)
    module2.state = ModuleState.LOADED
    module2.memory_usage_mb = 0
    module2.cpu_usage = 0
    module2.api_calls = 0
    module2.error_count = 0
    module2.load_duration_ms = None

    modules = {"mod1": module1, "mod2": module2}

    metrics = collector.get_system_metrics(modules)

    assert metrics.states_breakdown["running"] == 1
    assert metrics.states_breakdown["loaded"] == 1