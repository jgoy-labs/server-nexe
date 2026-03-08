"""
────────────────────────────────────
Server Nexe
Version: 0.8
Author: Jordi Goy 
Location: plugins/security/tests/test_request_size_limits.py
Description: Tests per límits de mida de requests. Valida que RequestSizeLimiterMiddleware rebutja requests massa grans (protecció CWE-400).

www.jgoy.net
────────────────────────────────────
"""

import pytest
from fastapi.testclient import TestClient

from core.app import app

@pytest.fixture(scope="module")
def client() -> TestClient:
  """Shared test client for the Nexe FastAPI application."""
  with TestClient(app, base_url="http://localhost") as test_client:
    yield test_client

def test_request_within_size_limit_accepted(client: TestClient) -> None:
  """Test that requests within size limit are accepted."""
  small_payload = {"data": "x" * 1000}

  response = client.get("/health")
  assert response.status_code == 200, "Small GET request should succeed"

  response = client.post(
    "/health",
    json=small_payload
  )
  assert response.status_code != 413, "Small POST request should not be rejected for size"

def test_request_exceeds_size_limit_rejected(client: TestClient) -> None:
  """Test that requests exceeding size limit are rejected with 413."""
  large_size = 200 * 1024 * 1024

  response = client.post(
    "/health",
    headers={"Content-Length": str(large_size)},
    content=b""
  )

  assert response.status_code == 413, "Large request should be rejected with 413"
  assert "Request Entity Too Large" in response.text or "Request body size" in response.text

def test_request_size_limit_error_message(client: TestClient) -> None:
  """Test that 413 error includes helpful message."""
  large_size = 150 * 1024 * 1024

  response = client.post(
    "/health",
    headers={"Content-Length": str(large_size)},
    content=b""
  )

  assert response.status_code == 413
  json_response = response.json()

  assert "error" in json_response
  assert "detail" in json_response
  assert "max_size_mb" in json_response

  assert "Request Entity Too Large" in json_response["error"] or \
      "Request body size" in json_response["detail"]

def test_request_at_exactly_limit_accepted(client: TestClient) -> None:
  """Test that request at exactly the limit is accepted."""
  exact_limit = 104857600

  response = client.post(
    "/health",
    headers={"Content-Length": str(exact_limit)},
    content=b""
  )

  assert response.status_code != 413, "Request at exact limit should not be rejected"

def test_request_just_over_limit_rejected(client: TestClient) -> None:
  """Test that request just 1 byte over limit is rejected."""
  just_over = 104857600 + 1

  response = client.post(
    "/health",
    headers={"Content-Length": str(just_over)},
    content=b""
  )

  assert response.status_code == 413, "Request 1 byte over limit should be rejected"
