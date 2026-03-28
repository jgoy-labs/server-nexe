"""
────────────────────────────────────
Server Nexe
Author: Jordi Goy 
Location: core/metrics/tests/test_registry.py
Description: Tests per Prometheus metrics registry.

www.jgoy.net · https://server-nexe.org
────────────────────────────────────
"""

import pytest
from prometheus_client import REGISTRY

from core.metrics.registry import (
  get_metrics_registry,
  normalize_path,
  set_module_health,
  increment_rate_limit,
  HTTP_REQUESTS_TOTAL,
  HTTP_REQUEST_DURATION,
  HTTP_ERRORS_TOTAL,
  ACTIVE_CONNECTIONS,
  MODULE_HEALTH_STATUS,
  RATE_LIMIT_HITS,
)

class TestMetricsRegistry:
  """Tests for metrics registry."""

  def test_get_metrics_registry(self):
    """Test registry retrieval."""
    registry = get_metrics_registry()
    assert registry is not None
    assert registry is REGISTRY

  def test_http_requests_counter_exists(self):
    """Test HTTP requests counter is registered."""
    assert HTTP_REQUESTS_TOTAL is not None
    HTTP_REQUESTS_TOTAL.labels(method="GET", path="/test", status="200").inc()

  def test_http_duration_histogram_exists(self):
    """Test HTTP duration histogram is registered."""
    assert HTTP_REQUEST_DURATION is not None
    HTTP_REQUEST_DURATION.labels(method="GET", path="/test").observe(0.5)

  def test_http_errors_counter_exists(self):
    """Test HTTP errors counter is registered."""
    assert HTTP_ERRORS_TOTAL is not None
    HTTP_ERRORS_TOTAL.labels(
      method="GET", path="/test", error_type="server_error"
    ).inc()

  def test_active_connections_gauge_exists(self):
    """Test active connections gauge is registered."""
    assert ACTIVE_CONNECTIONS is not None
    ACTIVE_CONNECTIONS.inc()
    ACTIVE_CONNECTIONS.dec()

  def test_module_health_gauge_exists(self):
    """Test module health gauge is registered."""
    assert MODULE_HEALTH_STATUS is not None

class TestNormalizePath:
  """Tests for path normalization."""

  def test_simple_path(self):
    """Test simple path unchanged."""
    assert normalize_path("/health") == "/health"
    assert normalize_path("/v1/workflows") == "/v1/workflows"

  def test_remove_query_params(self):
    """Test query params removed."""
    assert normalize_path("/api/search?q=test") == "/api/search"
    assert normalize_path("/v1/chat?model=Nexe") == "/v1/chat"

  def test_uuid_normalized(self):
    """Test UUID paths normalized."""
    path = "/memory/550e8400-e29b-41d4-a716-446655440000"
    assert normalize_path(path) == "/memory/{id}"

  def test_hash_normalized(self):
    """Test hash paths normalized."""
    path = "/documents/a1b2c3d4e5f6a1b2c3d4e5f6a1b2c3d4"
    assert normalize_path(path) == "/documents/{id}"

  def test_numeric_id_normalized(self):
    """Test numeric IDs normalized."""
    path = "/users/123456789"
    assert normalize_path(path) == "/users/{id}"

  def test_short_numeric_unchanged(self):
    """Test short numeric values unchanged."""
    path = "/v1/items"
    assert normalize_path(path) == "/v1/items"

  def test_empty_path(self):
    """Test empty path."""
    assert normalize_path("") == "/"
    assert normalize_path("/") == "/"

  def test_nested_paths(self):
    """Test nested paths."""
    path = "/api/v1/users/550e8400-e29b-41d4-a716-446655440000/documents"
    result = normalize_path(path)
    assert result == "/api/v1/users/{id}/documents"

class TestSetModuleHealth:
  """Tests for module health setting."""

  def test_set_healthy(self):
    """Test setting healthy status."""
    set_module_health("test_module", "healthy")
    assert MODULE_HEALTH_STATUS.labels(module="test_module")._value.get() == 1.0

  def test_set_degraded(self):
    """Test setting degraded status."""
    set_module_health("test_module2", "degraded")
    assert MODULE_HEALTH_STATUS.labels(module="test_module2")._value.get() == 0.5

  def test_set_unhealthy(self):
    """Test setting unhealthy status."""
    set_module_health("test_module3", "unhealthy")
    assert MODULE_HEALTH_STATUS.labels(module="test_module3")._value.get() == 0.0

  def test_unknown_status(self):
    """Test unknown status defaults to unhealthy."""
    set_module_health("test_module4", "unknown")
    assert MODULE_HEALTH_STATUS.labels(module="test_module4")._value.get() == 0.0

  def test_case_insensitive(self):
    """Test status is case insensitive."""
    set_module_health("test_module5", "HEALTHY")
    assert MODULE_HEALTH_STATUS.labels(module="test_module5")._value.get() == 1.0

class TestIncrementRateLimit:
  """Tests for rate limit increment."""

  def test_increment_rate_limit(self):
    """Test rate limit increment."""
    increment_rate_limit("ip", "/api/test")
    increment_rate_limit("api_key", "/v1/workflows")
    increment_rate_limit("composite", "/memory/store")

  def test_path_normalized(self):
    """Test path is normalized in rate limit."""
    increment_rate_limit("ip", "/users/550e8400-e29b-41d4-a716-446655440000")
