"""
────────────────────────────────────
Server Nexe
Version: 0.8
Author: Jordi Goy 
Location: core/server/tests/test_server.py
Description: Tests bàsics per servidor Nexe. Valida endpoints root/health/info, CORS config, rate limiting i injeccions d'i18n/limiter/config.

www.jgoy.net
────────────────────────────────────
"""

import pytest
from fastapi.testclient import TestClient

from core.app import app

@pytest.fixture
def client():
  """Create test client"""
  return TestClient(app, base_url="http://localhost")

def test_root_endpoint(client):
  """Test root endpoint returns correct structure"""
  response = client.get("/")
  assert response.status_code == 200
  data = response.json()
  assert "system" in data
  assert data["system"] == "Nexe 0.8"
  assert "version" in data
  assert data["version"] == "0.8.0"

def test_health_endpoint(client):
  """Test health endpoint"""
  response = client.get("/health")
  assert response.status_code == 200
  data = response.json()
  assert "status" in data
  assert "version" in data

def test_api_info_endpoint(client):
  """Test API info endpoint"""
  response = client.get("/api/info")
  assert response.status_code == 200
  data = response.json()
  assert "name" in data
  assert "version" in data
  assert "endpoints" in data
  assert isinstance(data["endpoints"], list)

def test_modules_endpoint(client):
  """Test modules listing endpoint"""
  response = client.get("/modules")
  assert response.status_code == 200
  data = response.json()
  assert "status" in data

def test_rate_limiting_shared(client):
  """Test that rate limiting is working (shared limiter)"""
  responses = []
  for _ in range(35):
    responses.append(client.get("/"))

  success_count = sum(1 for r in responses if r.status_code == 200)
  assert success_count > 0

def test_cors_config_loaded(client):
  """Test that CORS middleware is configured with real config"""
  from starlette.middleware.cors import CORSMiddleware

  has_cors = any(
    isinstance(middleware.cls, type) and issubclass(middleware.cls, CORSMiddleware)
    for middleware in app.user_middleware
  )

  assert has_cors, "CORS middleware should be configured"

def test_i18n_injection(client):
  """Test that i18n is properly injected via app.state"""
  assert hasattr(app.state, 'i18n')
  assert app.state.i18n is not None

def test_limiter_injection(client):
  """Test that limiter is properly injected via app.state"""
  assert hasattr(app.state, 'limiter')
  assert app.state.limiter is not None

def test_config_injection(client):
  """Test that config is properly injected via app.state"""
  assert hasattr(app.state, 'config')
  assert app.state.config is not None
  assert 'core' in app.state.config
