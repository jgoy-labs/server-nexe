"""
────────────────────────────────────
Server Nexe
Version: 0.8
Author: Jordi Goy 
Location: plugins/security/tests/test_api_key_rotation.py
Description: Tests per rotació d'API keys amb suport dual-key. Valida expiracions, prioritats, backward compatibility i zero-downtime rotation.

www.jgoy.net
────────────────────────────────────
"""

import os
import pytest
from datetime import datetime, timedelta, timezone
from fastapi.testclient import TestClient

from plugins.security.core.auth import (
  load_api_keys,
  parse_datetime_or_none,
  KeyStatus,
  ApiKeyData,
  ApiKeyConfig,
)
from core.app import app

@pytest.fixture(autouse=True)
def cleanup_api_key_env(monkeypatch):
  """Ensure API key environment is clean for each test.

  This prevents test pollution when running the full suite.
  """
  original_admin = os.getenv("NEXE_ADMIN_API_KEY")
  original_primary = os.getenv("NEXE_PRIMARY_API_KEY")
  original_secondary = os.getenv("NEXE_SECONDARY_API_KEY")

  yield

  def _restore(name: str, value: str | None) -> None:
    if value is None:
      os.environ.pop(name, None)
    else:
      os.environ[name] = value

  _restore("NEXE_ADMIN_API_KEY", original_admin)
  _restore("NEXE_PRIMARY_API_KEY", original_primary)
  _restore("NEXE_SECONDARY_API_KEY", original_secondary)

  os.environ.pop("NEXE_PRIMARY_KEY_EXPIRES", None)
  os.environ.pop("NEXE_SECONDARY_KEY_EXPIRES", None)

def test_parse_datetime_or_none_valid():
  """Test parsing valid ISO datetime strings."""
  result = parse_datetime_or_none("2026-01-10T00:00:00Z")

  assert result is not None
  assert isinstance(result, datetime)
  assert result.year == 2026
  assert result.month == 1
  assert result.day == 10

def test_parse_datetime_or_none_empty():
  """Test parsing empty/None values."""
  assert parse_datetime_or_none(None) is None
  assert parse_datetime_or_none("") is None

def test_parse_datetime_or_none_invalid():
  """Test parsing invalid datetime strings."""
  assert parse_datetime_or_none("not-a-date") is None
  assert parse_datetime_or_none("2026-13-32") is None

def test_api_key_data_status_active():
  """Test that key without expiry is always ACTIVE."""
  key = ApiKeyData(key="test-key-123")

  assert key.status == KeyStatus.ACTIVE
  assert key.is_valid is True

def test_api_key_data_status_expired():
  """Test that key past expiry is EXPIRED."""
  past = datetime.now(timezone.utc) - timedelta(days=1)
  key = ApiKeyData(key="test-key-123", expires_at=past)

  assert key.status == KeyStatus.EXPIRED
  assert key.is_valid is False

def test_api_key_data_status_active_with_future_expiry():
  """Test that key with future expiry is ACTIVE."""
  future = datetime.now(timezone.utc) + timedelta(days=90)
  key = ApiKeyData(key="test-key-123", expires_at=future)

  assert key.status == KeyStatus.ACTIVE
  assert key.is_valid is True

def test_api_key_data_status_not_configured():
  """Test that empty key is NOT_CONFIGURED."""
  key = ApiKeyData(key="")

  assert key.status == KeyStatus.NOT_CONFIGURED
  assert key.is_valid is False

def test_api_key_config_get_valid_keys_both():
  """Test get_valid_keys with both primary and secondary valid."""
  primary = ApiKeyData(key="primary-key")
  secondary = ApiKeyData(key="secondary-key")
  config = ApiKeyConfig(primary=primary, secondary=secondary)

  valid_keys = config.get_valid_keys()

  assert len(valid_keys) == 2
  assert valid_keys[0] == primary
  assert valid_keys[1] == secondary

def test_api_key_config_get_valid_keys_only_primary():
  """Test get_valid_keys with only primary valid."""
  primary = ApiKeyData(key="primary-key")
  config = ApiKeyConfig(primary=primary, secondary=None)

  valid_keys = config.get_valid_keys()

  assert len(valid_keys) == 1
  assert valid_keys[0] == primary

def test_api_key_config_get_valid_keys_expired_secondary():
  """Test get_valid_keys excludes expired secondary."""
  primary = ApiKeyData(key="primary-key")
  past = datetime.now(timezone.utc) - timedelta(days=1)
  secondary = ApiKeyData(key="secondary-key", expires_at=past)
  config = ApiKeyConfig(primary=primary, secondary=secondary)

  valid_keys = config.get_valid_keys()

  assert len(valid_keys) == 1
  assert valid_keys[0] == primary

def test_api_key_config_has_any_valid_key():
  """Test has_any_valid_key property."""
  config = ApiKeyConfig(primary=ApiKeyData(key="test"))
  assert config.has_any_valid_key is True

  config = ApiKeyConfig(primary=None, secondary=None)
  assert config.has_any_valid_key is False

  past = datetime.now(timezone.utc) - timedelta(days=1)
  config = ApiKeyConfig(primary=ApiKeyData(key="test", expires_at=past))
  assert config.has_any_valid_key is False

def test_load_api_keys_primary_only(monkeypatch):
  """Test loading primary key only (dual-key format)."""
  monkeypatch.setenv("NEXE_PRIMARY_API_KEY", "new-primary-key")
  monkeypatch.setenv("NEXE_PRIMARY_KEY_EXPIRES", "2026-01-10T00:00:00Z")
  monkeypatch.delenv("NEXE_ADMIN_API_KEY", raising=False)
  monkeypatch.delenv("NEXE_SECONDARY_API_KEY", raising=False)

  config = load_api_keys()

  assert config.primary is not None
  assert config.primary.key == "new-primary-key"
  assert config.primary.expires_at is not None
  assert config.primary.expires_at.year == 2026
  assert config.secondary is None

def test_load_api_keys_dual_key(monkeypatch):
  """Test loading both primary and secondary keys."""
  monkeypatch.setenv("NEXE_PRIMARY_API_KEY", "new-key")
  monkeypatch.setenv("NEXE_PRIMARY_KEY_EXPIRES", "2026-01-10T00:00:00Z")
  monkeypatch.setenv("NEXE_SECONDARY_API_KEY", "old-key")
  monkeypatch.setenv("NEXE_SECONDARY_KEY_EXPIRES", "2025-10-17T00:00:00Z")

  config = load_api_keys()

  assert config.primary is not None
  assert config.primary.key == "new-key"
  assert config.secondary is not None
  assert config.secondary.key == "old-key"

def test_load_api_keys_backward_compat(monkeypatch):
  """Test backward compatibility with NEXE_ADMIN_API_KEY."""
  monkeypatch.delenv("NEXE_PRIMARY_API_KEY", raising=False)
  monkeypatch.setenv("NEXE_ADMIN_API_KEY", "legacy-key")

  config = load_api_keys()

  assert config.primary is not None
  assert config.primary.key == "legacy-key"
  assert config.primary.expires_at is None
  assert config.secondary is None

def test_load_api_keys_priority_new_over_legacy(monkeypatch):
  """Test that NEXE_PRIMARY_API_KEY takes priority over NEXE_ADMIN_API_KEY."""
  monkeypatch.setenv("NEXE_PRIMARY_API_KEY", "new-key")
  monkeypatch.setenv("NEXE_ADMIN_API_KEY", "legacy-key")

  config = load_api_keys()

  assert config.primary.key == "new-key"

def test_load_api_keys_no_keys_configured(monkeypatch):
  """Test load_api_keys when no keys configured."""
  monkeypatch.delenv("NEXE_PRIMARY_API_KEY", raising=False)
  monkeypatch.delenv("NEXE_ADMIN_API_KEY", raising=False)
  monkeypatch.delenv("NEXE_SECONDARY_API_KEY", raising=False)

  config = load_api_keys()

  assert config.primary is None
  assert config.secondary is None
  assert config.has_any_valid_key is False

@pytest.fixture
def client():
  """Test client for FastAPI app."""
  return TestClient(app, base_url="http://localhost")

def test_require_api_key_with_valid_primary(client, monkeypatch):
  """Test authentication succeeds with valid primary key."""
  monkeypatch.setenv("NEXE_PRIMARY_API_KEY", "test-primary-key")
  monkeypatch.delenv("NEXE_ADMIN_API_KEY", raising=False)
  monkeypatch.delenv("NEXE_SECONDARY_API_KEY", raising=False)

  response = client.get(
    "/health",
    headers={"X-API-Key": "test-primary-key"}
  )

  assert response.status_code == 200

def test_require_api_key_with_valid_secondary(client, monkeypatch):
  """Test authentication succeeds with secondary key (grace period)."""
  future = (datetime.now(timezone.utc) + timedelta(days=7)).isoformat()

  monkeypatch.setenv("NEXE_PRIMARY_API_KEY", "new-key")
  monkeypatch.setenv("NEXE_SECONDARY_API_KEY", "old-key")
  monkeypatch.setenv("NEXE_SECONDARY_KEY_EXPIRES", future)

  response = client.get(
    "/health",
    headers={"X-API-Key": "old-key"}
  )

  assert response.status_code == 200

def test_require_api_key_primary_priority_over_secondary(client, monkeypatch):
  """Test that primary key is checked before secondary."""
  monkeypatch.setenv("NEXE_PRIMARY_API_KEY", "new-key")
  monkeypatch.setenv("NEXE_SECONDARY_API_KEY", "old-key")

  response = client.get(
    "/health",
    headers={"X-API-Key": "new-key"}
  )

  assert response.status_code == 200

def test_require_api_key_with_expired_key(client, monkeypatch):
  """Test that expired key is rejected."""
  past = (datetime.now(timezone.utc) - timedelta(days=1)).isoformat()

  monkeypatch.setenv("NEXE_PRIMARY_API_KEY", "expired-key")
  monkeypatch.setenv("NEXE_PRIMARY_KEY_EXPIRES", past)

  response = client.get(
    "/security/report",
    headers={"X-API-Key": "expired-key"}
  )

  assert response.status_code in [401, 500]

def test_require_api_key_backward_compat_phase1(client, monkeypatch):
  """Test backward compatibility with legacy NEXE_ADMIN_API_KEY."""
  monkeypatch.delenv("NEXE_PRIMARY_API_KEY", raising=False)
  monkeypatch.setenv("NEXE_ADMIN_API_KEY", "legacy-key")

  response = client.get(
    "/health",
    headers={"X-API-Key": "legacy-key"}
  )

  assert response.status_code == 200

def test_require_api_key_invalid_key(client, monkeypatch):
  """Test that invalid key is rejected."""
  monkeypatch.setenv("NEXE_PRIMARY_API_KEY", "correct-key")

  response = client.get(
    "/security/report",
    headers={"X-API-Key": "wrong-key"}
  )

  assert response.status_code == 401

def test_require_api_key_missing_header(client, monkeypatch):
  """Test that missing API key header is rejected."""
  monkeypatch.setenv("NEXE_PRIMARY_API_KEY", "test-key")

  response = client.get(
    "/security/report"
  )

  assert response.status_code in [401, 500]

def test_require_api_key_fail_closed_no_keys(client, monkeypatch):
  """Test fail-closed behavior when no keys configured (non-dev mode)."""
  monkeypatch.delenv("NEXE_PRIMARY_API_KEY", raising=False)
  monkeypatch.delenv("NEXE_ADMIN_API_KEY", raising=False)
  monkeypatch.setenv("NEXE_DEV_MODE", "false")

  response = client.get(
    "/security/report",
    headers={"X-API-Key": "any-key"}
  )

  assert response.status_code == 500

def test_require_api_key_dev_mode_bypass(client, monkeypatch):
  """Test that DEV_MODE allows bypass when no keys configured."""
  monkeypatch.delenv("NEXE_PRIMARY_API_KEY", raising=False)
  monkeypatch.delenv("NEXE_ADMIN_API_KEY", raising=False)
  monkeypatch.setenv("NEXE_DEV_MODE", "true")

  response = client.get(
    "/health"
  )

  assert response.status_code == 200

def test_zero_downtime_rotation_scenario(monkeypatch):
  """Test full rotation scenario with zero downtime.

  Scenario:
  1. Start with primary key only
  2. Add secondary key (start grace period)
  3. Both keys work
  4. Remove secondary key (end grace period)
  5. Only new primary works

  Testing at unit level using load_api_keys() directly.
  """
  future = (datetime.now(timezone.utc) + timedelta(days=7)).isoformat()

  monkeypatch.setenv("NEXE_PRIMARY_API_KEY", "original-key")
  monkeypatch.delenv("NEXE_SECONDARY_API_KEY", raising=False)

  config = load_api_keys()
  assert config.primary is not None
  assert config.primary.key == "original-key"
  assert config.secondary is None
  assert len(config.get_valid_keys()) == 1

  monkeypatch.setenv("NEXE_PRIMARY_API_KEY", "new-key")
  monkeypatch.setenv("NEXE_SECONDARY_API_KEY", "original-key")
  monkeypatch.setenv("NEXE_SECONDARY_KEY_EXPIRES", future)

  config = load_api_keys()
  assert config.primary.key == "new-key"
  assert config.secondary.key == "original-key"

  valid_keys = config.get_valid_keys()
  assert len(valid_keys) == 2
  assert valid_keys[0].key == "new-key"
  assert valid_keys[1].key == "original-key"

  monkeypatch.delenv("NEXE_SECONDARY_API_KEY", raising=False)
  monkeypatch.delenv("NEXE_SECONDARY_KEY_EXPIRES", raising=False)

  config = load_api_keys()

  assert config.primary.key == "new-key"
  assert config.secondary is None
  valid_keys = config.get_valid_keys()
  assert len(valid_keys) == 1
  assert valid_keys[0].key == "new-key"
