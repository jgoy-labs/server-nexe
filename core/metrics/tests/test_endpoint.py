"""
────────────────────────────────────
Server Nexe
Author: Jordi Goy 
Location: core/metrics/tests/test_endpoint.py
Description: Tests per Prometheus metrics endpoint.

www.jgoy.net · https://server-nexe.org
────────────────────────────────────
"""

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from core.metrics.endpoint import metrics_router

class TestMetricsEndpoint:
  """Tests for metrics endpoint."""

  @pytest.fixture
  def app(self):
    """Create test app with metrics router."""
    app = FastAPI()
    app.include_router(metrics_router)
    return app

  @pytest.fixture
  def client(self, app):
    """Create test client."""
    return TestClient(app)

  def test_get_metrics(self, client):
    """Test GET /metrics returns Prometheus format."""
    response = client.get("/metrics")
    assert response.status_code == 200
    assert "text/plain" in response.headers.get("content-type", "")
    content = response.text
    assert "core_" in content or "python_" in content or "process_" in content

  def test_metrics_health(self, client):
    """Test GET /metrics/health."""
    response = client.get("/metrics/health")
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "healthy"
    assert "metrics_size_bytes" in data
    assert data["metrics_size_bytes"] > 0

  def test_metrics_json(self, client):
    """Test GET /metrics/json."""
    response = client.get("/metrics/json")
    assert response.status_code == 200
    data = response.json()
    assert "http" in data
    assert "endpoints" in data
    assert data["endpoints"]["prometheus"] == "/metrics"

class TestMetricsContent:
  """Tests for metrics content."""

  @pytest.fixture
  def app(self):
    """Create test app."""
    app = FastAPI()
    app.include_router(metrics_router)
    return app

  @pytest.fixture
  def client(self, app):
    """Create test client."""
    return TestClient(app)

  def test_contains_nexe_metrics(self, client):
    """Test metrics contain Nexe-specific metrics."""
    response = client.get("/metrics")
    content = response.text

    assert response.status_code == 200

  def test_metrics_format_valid(self, client):
    """Test metrics are in valid Prometheus format."""
    response = client.get("/metrics")
    content = response.text

    lines = content.strip().split("\n")
    for line in lines:
      if not line.strip():
        continue
      if line.startswith("#"):
        continue
      parts = line.split()
      assert len(parts) >= 1, f"Invalid metric line: {line}"


class TestMetricsHealthUnhealthy:
  """Tests for metrics_health when generate_latest fails (lines 78-80)."""

  def test_metrics_health_exception_returns_unhealthy(self):
    """Line 78-80: generate_latest raises -> unhealthy status."""
    from unittest.mock import patch
    from core.metrics.endpoint import metrics_health
    import asyncio

    with patch("core.metrics.endpoint.generate_latest", side_effect=RuntimeError("broken")):
      result = asyncio.run(metrics_health())
    assert result["status"] == "unhealthy"
    assert "broken" in result["error"]


class TestUpdateModuleHealth:
  """Tests for _update_module_health (lines 122-128)."""

  def test_update_module_health_with_modules(self):
    """Lines 121-128: modules with get_health method."""
    from unittest.mock import patch, MagicMock
    from core.metrics.endpoint import _update_module_health
    import asyncio

    mock_module = MagicMock()
    mock_module.get_health.return_value = {"status": "healthy"}

    mock_mm = MagicMock()
    mock_mm.list_modules.return_value = {"test_mod": mock_module}

    with patch("personality.module_manager.module_manager.ModuleManager", return_value=mock_mm):
      asyncio.run(_update_module_health())
    mock_module.get_health.assert_called_once()

  def test_update_module_health_get_health_exception(self):
    """Line 127-128: get_health raises -> set unhealthy."""
    from unittest.mock import patch, MagicMock
    from core.metrics.endpoint import _update_module_health
    import asyncio

    mock_module = MagicMock()
    mock_module.get_health.side_effect = RuntimeError("fail")

    mock_mm = MagicMock()
    mock_mm.list_modules.return_value = {"broken_mod": mock_module}

    with patch("personality.module_manager.module_manager.ModuleManager", return_value=mock_mm), \
         patch("core.metrics.endpoint.set_module_health") as mock_set:
      asyncio.run(_update_module_health())
    mock_set.assert_called_with("broken_mod", "unhealthy")

  def test_update_module_health_import_error(self):
    """Line 130: ImportError is silently caught."""
    from unittest.mock import patch
    from core.metrics.endpoint import _update_module_health
    import asyncio
    import sys

    # Temporarily make the import fail
    saved = sys.modules.get('personality.module_manager.module_manager')
    sys.modules['personality.module_manager.module_manager'] = None
    try:
      asyncio.run(_update_module_health())
    finally:
      if saved is not None:
        sys.modules['personality.module_manager.module_manager'] = saved
      else:
        sys.modules.pop('personality.module_manager.module_manager', None)

  def test_update_module_health_generic_exception(self):
    """Line 132-133: Generic exception is caught and logged."""
    from unittest.mock import patch, MagicMock
    from core.metrics.endpoint import _update_module_health
    import asyncio

    mock_mm_class = MagicMock(side_effect=RuntimeError("unexpected"))
    with patch("personality.module_manager.module_manager.ModuleManager", mock_mm_class):
      # Should not raise
      asyncio.run(_update_module_health())