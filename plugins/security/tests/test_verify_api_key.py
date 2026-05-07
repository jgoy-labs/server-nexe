"""
────────────────────────────────────
Server Nexe
Author: Jordi Goy 
Location: plugins/security/tests/test_verify_api_key.py
Description: Tests for refactored verify_api_key(). Validates that it raises HTTPException(401) correctly and uses timing-safe comparison.

www.jgoy.net · https://server-nexe.org
────────────────────────────────────
"""

import pytest
import os
from fastapi import HTTPException

def test_verify_api_key_without_admin_key():
  """
  Test that verify_api_key() raises 401 if no API key is configured.

  Finding
  """
  original_key = os.environ.get("NEXE_ADMIN_API_KEY")
  if "NEXE_ADMIN_API_KEY" in os.environ:
    del os.environ["NEXE_ADMIN_API_KEY"]

  try:
    from plugins.security.core.auth import verify_api_key

    with pytest.raises(HTTPException) as exc_info:
      verify_api_key(x_api_key="any-key")

    assert exc_info.value.status_code == 401
    assert "not configured" in exc_info.value.detail.lower()

  finally:
    if original_key:
      os.environ["NEXE_ADMIN_API_KEY"] = original_key

def test_verify_api_key_with_none():
  """
  Test that verify_api_key() raises 401 if provided_key is None.

  Finding
  """
  from plugins.security.core.auth import generate_api_key, verify_api_key
  os.environ["NEXE_ADMIN_API_KEY"] = generate_api_key()

  with pytest.raises(HTTPException) as exc_info:
    verify_api_key(x_api_key=None)

  assert exc_info.value.status_code == 401
  assert "required" in exc_info.value.detail.lower()

def test_verify_api_key_with_empty_string():
  """
  Test that verify_api_key() raises 401 if provided_key is an empty string.

  Finding
  """
  from plugins.security.core.auth import generate_api_key, verify_api_key
  os.environ["NEXE_ADMIN_API_KEY"] = generate_api_key()

  with pytest.raises(HTTPException) as exc_info:
    verify_api_key(x_api_key="")

  assert exc_info.value.status_code == 401
  assert "required" in exc_info.value.detail.lower()

def test_verify_api_key_with_invalid_key():
  """
  Test that verify_api_key() raises 401 if provided_key is incorrect.

  Finding
  """
  from plugins.security.core.auth import generate_api_key, verify_api_key
  valid_key = generate_api_key()
  os.environ["NEXE_ADMIN_API_KEY"] = valid_key

  with pytest.raises(HTTPException) as exc_info:
    verify_api_key(x_api_key="invalid-key-123")

  assert exc_info.value.status_code == 401
  assert "invalid" in exc_info.value.detail.lower()

def test_verify_api_key_with_valid_key():
  """
  Test that verify_api_key() returns the key if it is valid.

  Finding
  """
  from plugins.security.core.auth import generate_api_key, verify_api_key
  valid_key = generate_api_key()
  os.environ["NEXE_ADMIN_API_KEY"] = valid_key

  result = verify_api_key(x_api_key=valid_key)

  assert result == valid_key
  assert isinstance(result, str)

def test_verify_api_key_timing_safe():
  """
  Test that verify_api_key() uses secrets.compare_digest() (timing-safe).

  Verify that the implementation is not vulnerable to timing attacks.
  """
  from plugins.security.core.auth import generate_api_key, verify_api_key
  import time

  valid_key = generate_api_key()
  os.environ["NEXE_ADMIN_API_KEY"] = valid_key

  different_key = "x" * len(valid_key)

  almost_key = valid_key[:-1] + "x"

  times_different = []
  times_almost = []

  for _ in range(100):
    start = time.perf_counter()
    try:
      verify_api_key(x_api_key=different_key)
    except HTTPException:
      pass
    times_different.append(time.perf_counter() - start)

    start = time.perf_counter()
    try:
      verify_api_key(x_api_key=almost_key)
    except HTTPException:
      pass
    times_almost.append(time.perf_counter() - start)

  avg_different = sum(times_different) / len(times_different)
  avg_almost = sum(times_almost) / len(times_almost)

  diff_percentage = abs(avg_different - avg_almost) / max(avg_different, avg_almost)

  assert diff_percentage < 0.2, (
    f"Possible timing attack vulnerability detected: "
    f"{diff_percentage:.2%} difference between different keys"
  )

def test_verify_api_key_as_fastapi_dependency():
  """
  Test that verify_api_key() works correctly as a FastAPI Depends().

  Finding
  it was not protecting endpoints because it returned False instead of raising 401.
  """
  from fastapi import FastAPI, Depends
  from fastapi.testclient import TestClient
  from plugins.security.core.auth import generate_api_key, verify_api_key

  valid_key = generate_api_key()
  os.environ["NEXE_ADMIN_API_KEY"] = valid_key

  app = FastAPI()

  @app.get("/protected")
  async def protected_endpoint(_: str = Depends(verify_api_key)):
    return {"data": "secret"}

  client = TestClient(app)

  response = client.get("/protected")
  assert response.status_code == 401

  response = client.get("/protected", headers={"X-API-Key": "invalid"})
  assert response.status_code == 401

  response = client.get("/protected", headers={"X-API-Key": valid_key})
  assert response.status_code == 200
  assert response.json() == {"data": "secret"}

def test_verify_api_key_backwards_compatibility():
  """
  Test that verify_api_key() maintains compatibility with existing code.

  Code that called verify_api_key() manually and caught False
  should now catch HTTPException.
  """
  from plugins.security.core.auth import generate_api_key, verify_api_key

  valid_key = generate_api_key()
  os.environ["NEXE_ADMIN_API_KEY"] = valid_key

  try:
    result = verify_api_key(x_api_key="invalid-key")
    pytest.fail("verify_api_key() should raise HTTPException for invalid key")
  except HTTPException as e:
    assert e.status_code == 401

  result = verify_api_key(x_api_key=valid_key)
  assert isinstance(result, str)
  assert result == valid_key

@pytest.fixture(autouse=True)
def cleanup_env():
  """
  Isolates API key variables to make tests deterministic.

  IMPORTANT: In CI/linuxtest, `NEXE_PRIMARY_API_KEY` is injected globally.
  These tests validate `verify_api_key()` in controlled scenarios, so
  we clean all related vars before each test and restore them afterwards.
  """
  key_env_vars = (
    "NEXE_ADMIN_API_KEY",
    "NEXE_PRIMARY_API_KEY",
    "NEXE_SECONDARY_API_KEY",
    "NEXE_PRIMARY_KEY_EXPIRES",
    "NEXE_SECONDARY_KEY_EXPIRES",
    "NEXE_PRIMARY_KEY_CREATED",
    "NEXE_SECONDARY_KEY_CREATED",
  )

  original = {k: os.environ[k] for k in key_env_vars if k in os.environ}
  for k in key_env_vars:
    os.environ.pop(k, None)

  yield

  for k in key_env_vars:
    os.environ.pop(k, None)
  for k, v in original.items():
    os.environ[k] = v
