"""
────────────────────────────────────
Server Nexe
Version: 0.8
Author: Jordi Goy 
Location: memory/memory/metrics.py
Description: Prometheus metrics for Memory Module (PHASE 13).

www.jgoy.net
────────────────────────────────────
"""

from typing import Dict, Any, Optional
import threading
import time
import structlog
from personality.i18n.resolve import t_modular

logger = structlog.get_logger()

def _t(key: str, fallback: str, **kwargs) -> str:
  return t_modular(f"memory.metrics.{key}", fallback, **kwargs)

class MemoryMetrics:
  """
  Prometheus-style metrics for Memory Module.

  PHASE 13: Simple implementation with dicts
  PHASE 14: Real integration with prometheus_client
  """

  def __init__(self):
    """Initialize metrics storage"""
    self._counters = {
      "memory_ingested_total": 0,
      "memory_duplicates_total": 0,
      "memory_failures_total": 0,
      "memory_cleanups_total": 0,
    }

    self._gauges = {
      "memory_flash_size": 0,
      "memory_ram_context_size": 0,
      "memory_persistence_entries": 0,
    }

    self._histogram_buckets = [0.001, 0.005, 0.01, 0.05, 0.1, 0.5, 1.0, 5.0]
    self._histograms = {
      "memory_ingestion_duration_seconds": []
    }

    logger.info(
      "memory_metrics_initialized",
      message=_t("initialized", "Memory metrics initialized")
    )

  def inc_counter(self, name: str, value: int = 1):
    """Increment counter metric"""
    if name in self._counters:
      self._counters[name] += value
      logger.debug(
        "metric_counter_incremented",
        message=_t(
          "counter_incremented",
          "Counter '{name}' incremented by {value} (total={total})",
          name=name,
          value=value,
          total=self._counters[name],
        ),
        name=name,
        value=value,
        total=self._counters[name]
      )
    else:
      logger.warning(
        "unknown_counter_metric",
        message=_t(
          "counter_unknown",
          "Unknown counter metric: {name}",
          name=name,
        ),
        name=name
      )

  def set_gauge(self, name: str, value: float):
    """Set gauge metric value"""
    if name in self._gauges:
      self._gauges[name] = value
      logger.debug(
        "metric_gauge_set",
        message=_t(
          "gauge_set",
          "Gauge '{name}' set to {value}",
          name=name,
          value=value,
        ),
        name=name,
        value=value
      )
    else:
      logger.warning(
        "unknown_gauge_metric",
        message=_t(
          "gauge_unknown",
          "Unknown gauge metric: {name}",
          name=name,
        ),
        name=name
      )

  def observe_histogram(self, name: str, value: float):
    """Observe histogram metric"""
    if name in self._histograms:
      self._histograms[name].append(value)
      logger.debug(
        "metric_histogram_observed",
        message=_t(
          "histogram_observed",
          "Histogram '{name}' observed value {value}",
          name=name,
          value=value,
        ),
        name=name,
        value=value
      )
    else:
      logger.warning(
        "unknown_histogram_metric",
        message=_t(
          "histogram_unknown",
          "Unknown histogram metric: {name}",
          name=name,
        ),
        name=name
      )

  def get_metrics(self) -> Dict[str, Any]:
    """
    Get all metrics as dict.

    Returns:
      Dict with counters, gauges, histograms
    """
    histogram_stats = {}
    for name, values in self._histograms.items():
      if values:
        histogram_stats[name] = {
          "count": len(values),
          "sum": sum(values),
          "avg": sum(values) / len(values),
          "min": min(values),
          "max": max(values),
        }
      else:
        histogram_stats[name] = {
          "count": 0,
          "sum": 0.0,
          "avg": 0.0,
          "min": 0.0,
          "max": 0.0,
        }

    return {
      "counters": dict(self._counters),
      "gauges": dict(self._gauges),
      "histograms": histogram_stats
    }

  def update_from_module(self, module):
    """
    Update metrics from MemoryModule state.

    Args:
      module: MemoryModule instance
    """
    try:
      if not module._initialized:
        logger.debug(
          "metrics_update_skipped_not_initialized",
          message=_t(
            "update_skipped_not_initialized",
            "Metrics update skipped: module not initialized"
          )
        )
        return

      if module._flash_memory:
        flash_size = len(module._flash_memory._store)
        self.set_gauge("memory_flash_size", flash_size)

      if module._ram_context:
        self.set_gauge("memory_ram_context_size", flash_size)

      if module._pipeline:
        pipeline_stats = module._pipeline.get_stats()

        self._counters["memory_ingested_total"] = pipeline_stats.get("total_ingested", 0)
        self._counters["memory_duplicates_total"] = pipeline_stats.get("duplicates_skipped", 0)
        self._counters["memory_failures_total"] = pipeline_stats.get("failures", 0)

      if module._persistence:
        pass

      logger.debug(
        "metrics_updated_from_module",
        message=_t("updated_from_module", "Metrics updated from module state")
      )

    except Exception as e:
      logger.error(
        "metrics_update_failed",
        message=_t(
          "update_failed",
          "Metrics update failed: {error}",
          error=str(e),
        ),
        error=str(e),
        exc_info=True
      )

  def record_ingestion_duration(self, duration: float):
    """
    Record ingestion duration in seconds.

    Args:
      duration: Duration in seconds
    """
    self.observe_histogram("memory_ingestion_duration_seconds", duration)

  def reset(self):
    """Reset all metrics (for testing)"""
    for key in self._counters:
      self._counters[key] = 0
    for key in self._gauges:
      self._gauges[key] = 0
    for key in self._histograms:
      self._histograms[key] = []
    logger.info(
      "metrics_reset",
      message=_t("reset", "Metrics reset")
    )

class MetricsTimer:
  """Context manager to measure operation duration"""

  def __init__(self, metrics: MemoryMetrics, metric_name: str):
    """
    Initialize timer.

    Args:
      metrics: MemoryMetrics instance
      metric_name: Name of the histogram metric
    """
    self.metrics = metrics
    self.metric_name = metric_name
    self.start_time = None

  def __enter__(self):
    """Start timer"""
    self.start_time = time.time()
    return self

  def __exit__(self, exc_type, exc_val, exc_tb):
    """Stop timer and record duration"""
    duration = time.time() - self.start_time
    self.metrics.observe_histogram(self.metric_name, duration)
    return False

_metrics_instance: Optional[MemoryMetrics] = None
_metrics_lock = threading.Lock()

def get_metrics() -> MemoryMetrics:
  """
  Get global MemoryMetrics instance (thread-safe).

  Returns:
    MemoryMetrics singleton
  """
  global _metrics_instance
  with _metrics_lock:
    if _metrics_instance is None:
      _metrics_instance = MemoryMetrics()
  return _metrics_instance

__all__ = [
  "MemoryMetrics",
  "MetricsTimer",
  "get_metrics",
]
