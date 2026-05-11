"""
────────────────────────────────────
Server Nexe
Author: Jordi Goy 
Location: core/metrics/tests/test_middleware.py
Description: Tests per Prometheus middleware.

www.jgoy.net · https://server-nexe.org
────────────────────────────────────
"""

import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from starlette.requests import Request
from starlette.responses import Response
from starlette.testclient import TestClient
from fastapi import FastAPI

from core.metrics.middleware import PrometheusMiddleware, setup_prometheus_middleware

class TestPrometheusMiddleware:
  """Tests for Prometheus middleware."""

  @pytest.fixture
  def app(self):
    """Create test app with middleware."""
    app = FastAPI()

    @app.get("/test")
    async def test_endpoint():
      return {"status": "ok"}

    @app.get("/error")
    async def error_endpoint():
      raise ValueError("Test error")

    @app.get("/slow")
    async def slow_endpoint():
      import asyncio
      await asyncio.sleep(0.1)
      return {"status": "slow"}

    app.add_middleware(PrometheusMiddleware)
    return app

  @pytest.fixture
  def client(self, app):
    """Create test client."""
    return TestClient(app, raise_server_exceptions=False)

  def test_successful_request_tracked(self, client):
    """Test successful request metrics."""
    response = client.get("/test")
    assert response.status_code == 200

  def test_error_request_tracked(self, client):
    """Test error request metrics."""
    response = client.get("/error")
    assert response.status_code == 500

  def test_excluded_paths_not_tracked(self, client, app):
    """Test excluded paths skip metrics."""
    @app.get("/metrics")
    async def metrics():
      return {"metrics": "data"}

    response = client.get("/metrics")
    assert response.status_code == 200

  def test_categorize_error_400(self):
    """Test error categorization for 400."""
    middleware = PrometheusMiddleware(app=MagicMock())
    assert middleware._categorize_error(400) == "bad_request"

  def test_categorize_error_401(self):
    """Test error categorization for 401."""
    middleware = PrometheusMiddleware(app=MagicMock())
    assert middleware._categorize_error(401) == "unauthorized"

  def test_categorize_error_403(self):
    """Test error categorization for 403."""
    middleware = PrometheusMiddleware(app=MagicMock())
    assert middleware._categorize_error(403) == "forbidden"

  def test_categorize_error_404(self):
    """Test error categorization for 404."""
    middleware = PrometheusMiddleware(app=MagicMock())
    assert middleware._categorize_error(404) == "not_found"

  def test_categorize_error_422(self):
    """Test error categorization for 422."""
    middleware = PrometheusMiddleware(app=MagicMock())
    assert middleware._categorize_error(422) == "validation_error"

  def test_categorize_error_429(self):
    """Test error categorization for 429."""
    middleware = PrometheusMiddleware(app=MagicMock())
    assert middleware._categorize_error(429) == "rate_limited"

  def test_categorize_error_500(self):
    """Test error categorization for 500."""
    middleware = PrometheusMiddleware(app=MagicMock())
    assert middleware._categorize_error(500) == "server_error"

  def test_categorize_error_other(self):
    """Test error categorization for other codes."""
    middleware = PrometheusMiddleware(app=MagicMock())
    assert middleware._categorize_error(418) == "client_error_418"

class TestSetupPrometheusMiddleware:
  """Tests for middleware setup function."""

  def test_setup_adds_middleware(self):
    """Test setup adds middleware to app."""
    app = FastAPI()
    setup_prometheus_middleware(app)
    assert len(app.user_middleware) > 0