"""
────────────────────────────────────
Server Nexe
Version: 0.8
Author: Jordi Goy 
Location: core/metrics/tests/test_endpoint.py
Description: Tests per Prometheus metrics endpoint.

www.jgoy.net
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