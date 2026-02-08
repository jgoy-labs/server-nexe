"""
────────────────────────────────────
Server Nexe
Version: 0.8
Author: Jordi Goy 
Location: plugins/security/tests/test_module_allowlist.py
Description: Tests per module allowlist fail-fast security. Valida que sistema falla si NEXE_APPROVED_MODULES no està en producció.

www.jgoy.net
────────────────────────────────────
"""

import pytest
from core.server.factory import create_app

pytest.importorskip("starlette_csrf")

@pytest.fixture(autouse=True)
def reset_app_cache():
  """
  Reset app cache abans i després de cada test per evitar estat compartit.

  ✅ M-3: Implementat - crida reset_app_cache() per netejar singleton.
  """
  from core.server.factory import reset_app_cache as reset_factory_cache
  reset_factory_cache()

  yield

  reset_factory_cache()

def test_module_allowlist_required_in_production(monkeypatch):
  """
  Test que sistema falla si NEXE_APPROVED_MODULES no està definit en producció.

  H-1: BLOCKER - Fail-fast condicionat a NEXE_ENV=production
  """
  monkeypatch.delenv("NEXE_APPROVED_MODULES", raising=False)
  monkeypatch.setenv("NEXE_ENV", "production")

  with pytest.raises(ValueError) as exc_info:
    create_app(force_reload=True)

  assert "NEXE_APPROVED_MODULES" in str(exc_info.value)

def test_module_allowlist_dev_allows_all(monkeypatch):
  """
  Test que NEXE_ENV=development permet mode permissiu sense allowlist.

  Comoditat per desenvolupament: no cal configurar allowlist.
  """
  monkeypatch.delenv("NEXE_APPROVED_MODULES", raising=False)
  monkeypatch.setenv("NEXE_ENV", "development")

  app = create_app()
  assert app is not None
  assert "Nexe" in app.title

def test_module_allowlist_staging_allows_all_with_warning(monkeypatch, caplog):
  """
  Test que NEXE_ENV=staging també permet mode permissiu amb warning.

  Staging pot necessitar flexibilitat sense ser tan estricte com producció.
  """
  monkeypatch.delenv("NEXE_APPROVED_MODULES", raising=False)
  monkeypatch.setenv("NEXE_ENV", "staging")

  app = create_app()
  assert app is not None

  assert any("allowlist" in record.message.lower() or "all discovered modules" in record.message.lower() for record in caplog.records)

def test_module_allowlist_with_approved_list(monkeypatch):
  """
  Test que allowlist funciona correctament quan està definit.

  Amb NEXE_APPROVED_MODULES definit, sistema carrega només mòduls aprovats.
  """
  monkeypatch.setenv("NEXE_APPROVED_MODULES", "security,security,observability")
  monkeypatch.setenv("NEXE_ENV", "production")

  app = create_app()
  assert app is not None

def test_module_allowlist_default_env_is_development(monkeypatch):
  """
  Test que NEXE_ENV per defecte és development (permissiu).

  Si no es defineix NEXE_ENV, sistema assumeix development per comoditat.
  """
  monkeypatch.delenv("NEXE_APPROVED_MODULES", raising=False)
  monkeypatch.delenv("NEXE_ENV", raising=False)

  app = create_app()
  assert app is not None

def test_module_allowlist_case_insensitive(monkeypatch):
  """
  Test que NEXE_ENV=Production (majúscules) també activa fail-fast.

  Case-insensitive per evitar errors de configuració.
  """
  monkeypatch.delenv("NEXE_APPROVED_MODULES", raising=False)
  monkeypatch.setenv("NEXE_ENV", "Production")

  with pytest.raises(ValueError) as exc_info:
    create_app(force_reload=True)

  assert "NEXE_APPROVED_MODULES" in str(exc_info.value)

def test_module_allowlist_whitespace_handling(monkeypatch):
  """
  Test que allowlist maneja espais correctament.

  Format: "security, security, observability" → ["security", "security", "observability"]
  """
  monkeypatch.setenv("NEXE_APPROVED_MODULES", "security, security, observability")
  monkeypatch.setenv("NEXE_ENV", "production")

  app = create_app()
  assert app is not None

def test_module_allowlist_empty_string_treated_as_undefined(monkeypatch):
  """
  Test que NEXE_APPROVED_MODULES="" es tracta com a no definit.

  String buit hauria d'activar fail-fast en producció.
  """
  monkeypatch.setenv("NEXE_APPROVED_MODULES", "")
  monkeypatch.setenv("NEXE_ENV", "production")

  with pytest.raises(ValueError) as exc_info:
    create_app(force_reload=True)

  assert "NEXE_APPROVED_MODULES" in str(exc_info.value)

def test_module_allowlist_logs_error_before_raising(monkeypatch, caplog):
  """
  Test que sistema loggeja error abans de raise (debugging).

  IMPORTANT: logger.error() ha d'estar DINS del bloc if abans del raise.
  """
  import logging
  caplog.set_level(logging.ERROR)

  monkeypatch.delenv("NEXE_APPROVED_MODULES", raising=False)
  monkeypatch.setenv("NEXE_ENV", "production")

  with pytest.raises(ValueError):
    create_app(force_reload=True)

  error_logs = [record for record in caplog.records if record.levelname == "ERROR"]
  assert len(error_logs) > 0
  assert any("NEXE_APPROVED_MODULES" in record.message for record in error_logs)

def test_module_allowlist_with_single_module(monkeypatch):
  """Test allowlist amb un sol mòdul"""
  monkeypatch.setenv("NEXE_APPROVED_MODULES", "security")
  monkeypatch.setenv("NEXE_ENV", "production")

  app = create_app()
  assert app is not None

def test_module_allowlist_unknown_env_treated_as_dev(monkeypatch):
  """
  Test que NEXE_ENV desconegut (ex: 'testing') es tracta com development.

  Fail-fast només s'activa amb NEXE_ENV=production exactament.
  """
  monkeypatch.delenv("NEXE_APPROVED_MODULES", raising=False)
  monkeypatch.setenv("NEXE_ENV", "testing")

  app = create_app()
  assert app is not None
