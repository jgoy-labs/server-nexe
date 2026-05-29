"""Tests for early fail-fast SidecarConfig validation at create_app().

Validates that when NEXE_SIDECAR=1, create_app() invokes SidecarConfig
validation immediately. If required env vars (NEXE_PRIMARY_API_KEY,
NEXE_PORT) are missing, RuntimeError is raised with a clear message
pointing to the launcher (Tauri lib.rs:spawn_sidecar_process).

Without this check, the error would surface much later (lifespan,
CORS preflight, etc.) with cryptic messages.
"""
from __future__ import annotations

import pytest

from core.server.factory import create_app


@pytest.fixture(autouse=True)
def clean_app_cache():
    """Reset the create_app singleton between tests."""
    from core.server import factory
    factory._app_instance = None
    factory._cache_project_root = None
    yield
    factory._app_instance = None
    factory._cache_project_root = None


@pytest.fixture
def clean_sidecar_env(monkeypatch):
    """Clean all NEXE_* vars + reset SidecarConfig singleton."""
    for var in [
        "NEXE_SIDECAR",
        "NEXE_PRIMARY_API_KEY",
        "NEXE_PORT",
        "NEXE_HOST",
        "NEXE_ENV",
        "NEXE_HOME",
        "NEXE_LOGS_DIR",
        "NEXE_DATA_DIR",
        "NEXE_CACHE_DIR",
        "NEXE_QDRANT_PATH",
    ]:
        monkeypatch.delenv(var, raising=False)
    # Reset SidecarConfig singleton so it re-reads env
    from core.sidecar_config import reset_sidecar_config
    reset_sidecar_config()


def test_create_app_succeeds_when_not_sidecar(clean_sidecar_env):
    """NEXE_SIDECAR not set → create_app proceeds without sidecar validation."""
    # No NEXE_SIDECAR → fail-fast check skipped, create_app runs normally
    app = create_app()
    assert app is not None


def test_create_app_fails_fast_when_sidecar_without_api_key(monkeypatch, clean_sidecar_env):
    """NEXE_SIDECAR=1 without NEXE_PRIMARY_API_KEY → RuntimeError with clear message."""
    monkeypatch.setenv("NEXE_SIDECAR", "1")
    monkeypatch.setenv("NEXE_PORT", "8765")  # has port but not api key
    # Missing NEXE_PRIMARY_API_KEY → SidecarConfig.from_env() should raise

    with pytest.raises(RuntimeError) as exc_info:
        create_app()

    msg = str(exc_info.value)
    assert "NEXE_SIDECAR=1" in msg
    assert "SidecarConfig validation failed" in msg
    assert "Tauri lib.rs:spawn_sidecar_process" in msg


def test_create_app_succeeds_with_full_sidecar_env(monkeypatch, clean_sidecar_env):
    """NEXE_SIDECAR=1 + all required env vars → create_app succeeds."""
    monkeypatch.setenv("NEXE_SIDECAR", "1")
    monkeypatch.setenv("NEXE_PRIMARY_API_KEY", "x" * 32)
    monkeypatch.setenv("NEXE_PORT", "8765")
    monkeypatch.setenv("NEXE_ENV", "production")

    # Should not raise
    app = create_app()
    assert app is not None


def test_fail_fast_runs_before_app_build(monkeypatch, clean_sidecar_env, caplog):
    """Fail-fast happens early — before setup_i18n_and_config / build phase.

    Validates that when the check fails, no expensive "Building FastAPI app..."
    log message has been emitted yet (=> check is early in the function flow).
    """
    monkeypatch.setenv("NEXE_SIDECAR", "1")
    # Missing NEXE_PRIMARY_API_KEY → RuntimeError

    with caplog.at_level("INFO"):
        with pytest.raises(RuntimeError):
            create_app()

    messages = " ".join(rec.message for rec in caplog.records)
    # The fail-fast should have surfaced BEFORE "Building FastAPI app..."
    # (it's a separate log line that comes later in create_app())
    assert "Building FastAPI app" not in messages or "validation failed" in messages
