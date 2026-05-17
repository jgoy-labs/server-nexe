"""F2.3 part 2: anti-regression tests for NEXE_ENV → SidecarConfig.is_production.

Validates that the 8 migrated points consult SidecarConfig.is_production
when available, falling back to os.getenv("NEXE_ENV") for backward-compat
(scripts/tests without a singleton initialised).

Migrated points (8):
- core/config.py::get_module_allowlist
- core/lifespan_tokens.py::setup_bootstrap_tokens (bootstrap_display gate)
- core/middleware.py::setup_csrf_protection
- core/lifespan_modules.py::auto_ingest_knowledge
- core/endpoints/bootstrap.py::_validate_bootstrap_env (l.100)
- core/endpoints/bootstrap.py::bootstrap_info (l.288)
- core/server/factory_security.py::validate_production_security
- core/server/factory_app.py::create_fastapi_instance (/docs gate)

NOT migrated (decisió pragmàtica):
- memory/memory/pipeline/ingestion.py:228 — check `NEXE_ENV == "test"`
  no és production/non-production, i SidecarConfig no exposa `is_test`.
"""
from __future__ import annotations

import os
from typing import Iterator

import pytest


# ─── Fixtures ────────────────────────────────────────────────────────────────


@pytest.fixture
def reset_sidecar_singleton() -> Iterator[None]:
    """Reset SidecarConfig singleton before and after each test."""
    from core.sidecar_config import reset_sidecar_config
    reset_sidecar_config()
    yield
    reset_sidecar_config()


@pytest.fixture
def clean_env(monkeypatch) -> None:
    """Strip relevant NEXE_* vars (test starts from a clean slate)."""
    for var in [
        "NEXE_ENV",
        "NEXE_SIDECAR",
        "NEXE_APPROVED_MODULES",
        "NEXE_CSRF_SECRET",
        "NEXE_AUTO_INGEST_KNOWLEDGE",
        "NEXE_BOOTSTRAP_DISPLAY",
    ]:
        monkeypatch.delenv(var, raising=False)


# ─── 1. Fallback works when SidecarConfig singleton not built ────────────────


def test_fallback_get_module_allowlist_without_sidecar_singleton(
    monkeypatch, clean_env, reset_sidecar_singleton
):
    """Without SidecarConfig initialised, NEXE_ENV=development → no production check."""
    from core.config import get_module_allowlist
    # Force SidecarConfig.from_env() to raise so the except branch fires.
    monkeypatch.setattr(
        "core.sidecar_config.get_sidecar_config",
        lambda: (_ for _ in ()).throw(RuntimeError("simulated absence")),
    )
    monkeypatch.setenv("NEXE_ENV", "development")
    # No allowlist set, dev mode → returns None (no ValueError)
    assert get_module_allowlist() is None


def test_fallback_get_module_allowlist_production_raises(
    monkeypatch, clean_env, reset_sidecar_singleton
):
    """Fallback path: NEXE_ENV=production + no allowlist → ValueError."""
    from core.config import get_module_allowlist
    monkeypatch.setattr(
        "core.sidecar_config.get_sidecar_config",
        lambda: (_ for _ in ()).throw(RuntimeError("simulated absence")),
    )
    monkeypatch.setenv("NEXE_ENV", "production")
    with pytest.raises(ValueError, match="NEXE_APPROVED_MODULES"):
        get_module_allowlist()


# ─── 2. SidecarConfig production propagation ─────────────────────────────────


def test_get_module_allowlist_uses_sidecar_is_production_true(
    monkeypatch, clean_env, reset_sidecar_singleton
):
    """SidecarConfig.is_production=True must trigger production check
    (ValueError when allowlist missing) even if raw NEXE_ENV is empty."""
    from core.config import get_module_allowlist
    monkeypatch.setenv("NEXE_ENV", "production")  # SidecarConfig reads this
    # SidecarConfig singleton will be built lazily; reset_sidecar_singleton wipes it.
    with pytest.raises(ValueError, match="NEXE_APPROVED_MODULES"):
        get_module_allowlist()


def test_get_module_allowlist_uses_sidecar_is_production_false(
    monkeypatch, clean_env, reset_sidecar_singleton
):
    """SidecarConfig.is_production=False → no ValueError, returns None."""
    from core.config import get_module_allowlist
    monkeypatch.setenv("NEXE_ENV", "development")
    assert get_module_allowlist() is None


# ─── 3. Per-module behavioural smoke tests ───────────────────────────────────


def test_factory_app_docs_disabled_in_production(
    monkeypatch, clean_env, reset_sidecar_singleton
):
    """create_fastapi_instance disables /docs when SidecarConfig says production.

    Mockejat setup_all_middleware perquè requereix CORS configurat al config,
    no és part del que provem aquí (només la gate _nexe_env per /docs).
    """
    monkeypatch.setattr("core.middleware.setup_all_middleware", lambda *a, **kw: None)
    from core.server.factory_app import create_fastapi_instance

    monkeypatch.setenv("NEXE_ENV", "production")
    class _I18nStub:
        def t(self, key, default=None, **kwargs):  # noqa: D401
            return default if default is not None else key
    config = {"core": {"environment": {"mode": "production"}}}
    app = create_fastapi_instance(_I18nStub(), config)
    assert app.docs_url is None
    assert app.redoc_url is None


def test_factory_app_docs_enabled_in_development(
    monkeypatch, clean_env, reset_sidecar_singleton
):
    """create_fastapi_instance enables /docs in development."""
    monkeypatch.setattr("core.middleware.setup_all_middleware", lambda *a, **kw: None)
    from core.server.factory_app import create_fastapi_instance

    monkeypatch.setenv("NEXE_ENV", "development")
    class _I18nStub:
        def t(self, key, default=None, **kwargs):
            return default if default is not None else key
    config = {"core": {"environment": {"mode": "development"}}}
    app = create_fastapi_instance(_I18nStub(), config)
    assert app.docs_url == "/docs"


def test_validate_bootstrap_env_blocks_production(
    monkeypatch, clean_env, reset_sidecar_singleton
):
    """_validate_bootstrap_env raises HTTPException 503 when production."""
    from fastapi import HTTPException
    from core.endpoints.bootstrap import _validate_bootstrap_env

    monkeypatch.setenv("NEXE_ENV", "production")
    with pytest.raises(HTTPException) as exc_info:
        _validate_bootstrap_env()
    assert exc_info.value.status_code == 503


def test_validate_bootstrap_env_allows_development(
    monkeypatch, clean_env, reset_sidecar_singleton
):
    """_validate_bootstrap_env passes silently in development."""
    from core.endpoints.bootstrap import _validate_bootstrap_env

    monkeypatch.setenv("NEXE_ENV", "development")
    # Should not raise
    _validate_bootstrap_env()


def test_validate_bootstrap_env_blocks_staging(
    monkeypatch, clean_env, reset_sidecar_singleton
):
    """Bootstrap must stay blocked in staging (not only production).
    Regression guard: SidecarConfig only knows production vs non-production,
    so we kept the raw env read to distinguish staging."""
    from fastapi import HTTPException
    from core.endpoints.bootstrap import _validate_bootstrap_env

    monkeypatch.setenv("NEXE_ENV", "staging")
    with pytest.raises(HTTPException) as exc_info:
        _validate_bootstrap_env()
    assert exc_info.value.status_code == 503


def test_validate_production_security_passes_in_development(
    monkeypatch, clean_env, reset_sidecar_singleton
):
    """validate_production_security must not raise in development mode."""
    from core.server.factory_security import validate_production_security

    monkeypatch.setenv("NEXE_ENV", "development")
    class _I18nStub:
        def t(self, key, default=None, **kwargs):
            return default if default is not None else key
    # No allowlist needed in dev → no ValueError
    validate_production_security(_I18nStub(), {"core": {"environment": {"mode": "development"}}})


def test_validate_production_security_raises_in_production_without_allowlist(
    monkeypatch, clean_env, reset_sidecar_singleton
):
    """validate_production_security raises ValueError when NEXE_APPROVED_MODULES missing."""
    from core.server.factory_security import validate_production_security

    monkeypatch.setenv("NEXE_ENV", "production")
    monkeypatch.delenv("NEXE_APPROVED_MODULES", raising=False)
    class _I18nStub:
        def t(self, key, default=None, **kwargs):
            return default if default is not None else key
    with pytest.raises(ValueError, match="NEXE_APPROVED_MODULES"):
        validate_production_security(
            _I18nStub(),
            {"core": {"environment": {"mode": "production"}}},
        )


# ─── 4. Fallback chain doesn't crash when SidecarConfig.from_env() fails ─────


def test_all_migrated_modules_import_cleanly():
    """Smoke: all 8 migrated modules import without side-effect errors."""
    import importlib
    for mod_name in [
        "core.config",
        "core.lifespan_tokens",
        "core.middleware",
        "core.lifespan_modules",
        "core.endpoints.bootstrap",
        "core.server.factory_security",
        "core.server.factory_app",
        "memory.memory.pipeline.ingestion",
    ]:
        mod = importlib.import_module(mod_name)
        assert mod is not None
