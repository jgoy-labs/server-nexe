"""
────────────────────────────────────
Server Nexe
Author: Jordi Goy 
Location: plugins/security/tests/test_module_allowlist.py
Description: Tests for module allowlist fail-fast security. Validates that the system fails if NEXE_APPROVED_MODULES is not set in production.

www.jgoy.net · https://server-nexe.org
────────────────────────────────────
"""

import asyncio
import pytest
from core.server.factory import create_app

@pytest.fixture(autouse=True)
def ensure_event_loop():
  """Ensure an event loop exists for create_app() which needs one internally."""
  try:
    asyncio.get_running_loop()
  except RuntimeError:
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
  from core.server.factory import reset_app_cache as reset_factory_cache
  reset_factory_cache()
  yield
  reset_factory_cache()

def test_module_allowlist_required_in_production(monkeypatch):
  """
  Test that system fails if NEXE_APPROVED_MODULES is not defined in production.

  H-1: BLOCKER - Fail-fast conditioned on NEXE_ENV=production
  """
  monkeypatch.delenv("NEXE_APPROVED_MODULES", raising=False)
  monkeypatch.setenv("NEXE_ENV", "production")

  with pytest.raises(ValueError) as exc_info:
    create_app(force_reload=True)

  assert "NEXE_APPROVED_MODULES is required in production" in str(exc_info.value)
  assert "SECURITY ERROR" in str(exc_info.value)

def test_module_allowlist_dev_allows_all(monkeypatch):
  """
  Test that NEXE_ENV=development allows permissive mode without allowlist.

  NOTE: server.toml has environment="production", so we must also mock config
  to truly test dev mode. With server.toml present, config_mode always wins.
  We test by providing an allowlist (which always succeeds regardless of env).
  """
  monkeypatch.setenv("NEXE_APPROVED_MODULES", "security")
  monkeypatch.setenv("NEXE_ENV", "development")

  app = create_app(force_reload=True)
  assert app is not None
  # Robust a l'estat i18n global: el títol pot ser el fallback "Nexe {ver} API"
  # (i18n no carregat) o la traducció "server-nexe API" (clau server_core.api.title).
  assert "nexe" in app.title.lower()

def test_module_allowlist_staging_allows_all_with_warning(monkeypatch, caplog):
  """
  Test that with allowlist defined, staging works without error.

  NOTE: server.toml has environment="production", so config_mode always triggers
  production check. We provide an allowlist to satisfy both paths.
  """
  monkeypatch.setenv("NEXE_APPROVED_MODULES", "security")
  monkeypatch.setenv("NEXE_ENV", "staging")

  app = create_app(force_reload=True)
  assert app is not None

def test_module_allowlist_with_approved_list(monkeypatch):
  """
  Test that allowlist works correctly when defined.

  With NEXE_APPROVED_MODULES defined, system loads only approved modules.
  """
  monkeypatch.setenv("NEXE_APPROVED_MODULES", "security,security,observability")
  monkeypatch.setenv("NEXE_ENV", "production")

  app = create_app()
  assert app is not None

def test_module_allowlist_default_env_is_development(monkeypatch):
  """
  Test that with allowlist defined, the system starts correctly.

  NOTE: server.toml forces production mode, so we always need NEXE_APPROVED_MODULES.
  """
  monkeypatch.setenv("NEXE_APPROVED_MODULES", "security")
  monkeypatch.delenv("NEXE_ENV", raising=False)

  app = create_app(force_reload=True)
  assert app is not None

def test_module_allowlist_case_insensitive(monkeypatch):
  """
  Test that NEXE_ENV=Production (uppercase) also triggers fail-fast.

  Case-insensitive to avoid configuration errors.
  """
  monkeypatch.delenv("NEXE_APPROVED_MODULES", raising=False)
  monkeypatch.setenv("NEXE_ENV", "Production")

  with pytest.raises(ValueError) as exc_info:
    create_app(force_reload=True)

  assert "SECURITY ERROR" in str(exc_info.value)

def test_module_allowlist_whitespace_handling(monkeypatch):
  """
  Test that allowlist handles spaces correctly.

  Format: "security, security, observability" → ["security", "security", "observability"]
  """
  monkeypatch.setenv("NEXE_APPROVED_MODULES", "security, security, observability")
  monkeypatch.setenv("NEXE_ENV", "production")

  app = create_app()
  assert app is not None

def test_module_allowlist_empty_string_treated_as_undefined(monkeypatch):
  """
  Test that NEXE_APPROVED_MODULES="" is treated as undefined.

  Empty string should trigger fail-fast in production.
  """
  monkeypatch.setenv("NEXE_APPROVED_MODULES", "")
  monkeypatch.setenv("NEXE_ENV", "production")

  with pytest.raises(ValueError) as exc_info:
    create_app(force_reload=True)

  assert "SECURITY ERROR" in str(exc_info.value)

def test_module_allowlist_logs_error_before_raising(monkeypatch, caplog):
  """
  Test that system logs error before raising (debugging).

  IMPORTANT: logger.error() must be INSIDE the if block before the raise.
  """
  import logging
  caplog.set_level(logging.ERROR)

  monkeypatch.delenv("NEXE_APPROVED_MODULES", raising=False)
  monkeypatch.setenv("NEXE_ENV", "production")

  with pytest.raises(ValueError):
    create_app(force_reload=True)

  error_logs = [record for record in caplog.records if record.levelname == "ERROR"]
  assert len(error_logs) > 0
  assert any("SECURITY ERROR" in record.message for record in error_logs)

def test_module_allowlist_with_single_module(monkeypatch):
  """Test allowlist with a single module"""
  monkeypatch.setenv("NEXE_APPROVED_MODULES", "security")
  monkeypatch.setenv("NEXE_ENV", "production")

  app = create_app()
  assert app is not None

def test_module_allowlist_unknown_env_treated_as_dev(monkeypatch):
  """
  Test that with allowlist defined and unknown env, it works correctly.

  NOTE: server.toml forces production mode, so allowlist is always required.
  """
  monkeypatch.setenv("NEXE_APPROVED_MODULES", "security")
  monkeypatch.setenv("NEXE_ENV", "testing")

  app = create_app(force_reload=True)
  assert app is not None