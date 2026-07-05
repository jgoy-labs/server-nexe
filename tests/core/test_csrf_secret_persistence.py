"""Persistent CSRF secret.

Verifies that the CSRF cookie-signing secret survives process restarts when
no NEXE_CSRF_SECRET / SidecarConfig.csrf_secret is configured. Without
persistence the previous implementation regenerated a token at each boot,
silently invalidating every signed CSRF cookie.
"""

import os
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import pytest

from core.middleware import _load_or_create_persistent_csrf_secret


@pytest.fixture
def fake_sidecar_data_dir(tmp_path, monkeypatch):
  """Force the loader to use tmp_path as the sidecar data_dir."""
  data_dir = tmp_path / "sidecar-data"
  data_dir.mkdir()
  cfg = SimpleNamespace(is_sidecar=True, data_dir=data_dir)
  monkeypatch.setattr("core.sidecar_config.get_sidecar_config", lambda: cfg)
  return data_dir


def test_generates_and_persists_secret_on_first_call(fake_sidecar_data_dir):
  """First call must create the secret file with 0600 permission."""
  secret = _load_or_create_persistent_csrf_secret()

  secret_path = fake_sidecar_data_dir / "csrf_secret"
  assert secret_path.exists(), "Secret file must be persisted on disk"
  assert len(secret) >= 32, "Secret must be at least 32 chars"

  on_disk = secret_path.read_text(encoding="ascii").strip()
  assert on_disk == secret, "On-disk content must match returned value"

  mode = secret_path.stat().st_mode & 0o777
  assert mode == 0o600, f"Expected 0600 permission, got {mode:o}"


def test_second_call_reuses_persisted_secret(fake_sidecar_data_dir):
  """Restart simulation: second invocation must return the same secret."""
  first = _load_or_create_persistent_csrf_secret()
  second = _load_or_create_persistent_csrf_secret()

  assert first == second, "Persistent secret must survive across calls (BUG-NB-3)"


def test_too_short_existing_file_is_regenerated(fake_sidecar_data_dir):
  """Corrupted/too-short secret on disk → regenerated, not reused."""
  bad_path = fake_sidecar_data_dir / "csrf_secret"
  bad_path.write_text("short", encoding="ascii")

  secret = _load_or_create_persistent_csrf_secret()

  assert len(secret) >= 32
  assert secret != "short"
  assert bad_path.read_text(encoding="ascii").strip() == secret


def test_fallback_to_home_nexe_when_no_sidecar(tmp_path, monkeypatch):
  """Without sidecar config, fall back to ~/.nexe/csrf_secret."""
  monkeypatch.setattr(Path, "home", lambda: tmp_path)
  monkeypatch.setattr(
    "core.sidecar_config.get_sidecar_config",
    lambda: SimpleNamespace(is_sidecar=False, data_dir=None),
  )

  secret = _load_or_create_persistent_csrf_secret()

  expected_path = tmp_path / ".nexe" / "csrf_secret"
  assert expected_path.exists()
  assert expected_path.read_text(encoding="ascii").strip() == secret


def test_sidecar_config_unavailable_falls_back(tmp_path, monkeypatch):
  """If SidecarConfig blows up, still persist to ~/.nexe (no crash)."""
  monkeypatch.setattr(Path, "home", lambda: tmp_path)
  monkeypatch.setattr(
    "core.sidecar_config.get_sidecar_config",
    lambda: (_ for _ in ()).throw(RuntimeError("not initialised")),
  )

  secret = _load_or_create_persistent_csrf_secret()
  assert len(secret) >= 32
  assert (tmp_path / ".nexe" / "csrf_secret").exists()
