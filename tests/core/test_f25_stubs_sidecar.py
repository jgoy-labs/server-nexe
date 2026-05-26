"""F2.5 — Tests TDD per a stub endpoints sidecar-aware + restart 501.

Cobertura:
- 3 stubs (/sessions, /info, /backends) retornen 200 amb body declaratiu quan
  is_sidecar=True.
- En mode no-sidecar retornen 501.
- POST /admin/system/restart retorna 501 quan is_sidecar=True (BUG-NX-4).
- manifest `disabled_in_sidecar=true` + sidecar actiu → `initialize()` retorna
  False.

Run: pytest tests/core/test_f25_stubs_sidecar.py --no-cov -q -p no:randomly
"""
from __future__ import annotations

import asyncio

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient


# ─────────────────────────────────────────────────────────────────────
# Fixtures — entorn aïllat (patró extret de test_factory_fail_fast_sidecar.py)
# ─────────────────────────────────────────────────────────────────────


@pytest.fixture
def clean_sidecar_env(monkeypatch):
    """Neteja NEXE_* + reseteja singleton SidecarConfig."""
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
    from core.sidecar_config import reset_sidecar_config
    reset_sidecar_config()
    yield
    reset_sidecar_config()


@pytest.fixture
def sidecar_env(monkeypatch, clean_sidecar_env, tmp_path):
    """Construeix un entorn vàlid sidecar=1 amb totes les env vars necessàries."""
    monkeypatch.setenv("NEXE_SIDECAR", "1")
    monkeypatch.setenv("NEXE_PRIMARY_API_KEY", "x" * 32)
    monkeypatch.setenv("NEXE_PORT", "8765")
    monkeypatch.setenv("NEXE_ENV", "production")
    monkeypatch.setenv("NEXE_HOME", str(tmp_path / "home"))
    monkeypatch.setenv("NEXE_LOGS_DIR", str(tmp_path / "logs"))
    monkeypatch.setenv("NEXE_DATA_DIR", str(tmp_path / "data"))
    monkeypatch.setenv("NEXE_CACHE_DIR", str(tmp_path / "cache"))
    monkeypatch.setenv("NEXE_QDRANT_PATH", str(tmp_path / "qdrant"))
    from core.sidecar_config import reset_sidecar_config
    reset_sidecar_config()
    yield
    reset_sidecar_config()


def _make_stubs_app() -> FastAPI:
    """Construeix una FastAPI mínima només amb el router de sidecar_stubs.

    Evita arrencar tota la factory (lifespan, modules, etc.) — els stubs són
    pure routers, no depenen de cap state.
    """
    from core.endpoints.sidecar_stubs import router as stubs_router
    app = FastAPI()
    app.include_router(stubs_router)
    return app


# ─────────────────────────────────────────────────────────────────────
# Stubs — comportament SIDECAR (200 amb body declaratiu)
# ─────────────────────────────────────────────────────────────────────


def test_sessions_stub_returns_200_in_sidecar(sidecar_env):
    client = TestClient(_make_stubs_app())
    resp = client.get("/sessions")
    assert resp.status_code == 200
    body = resp.json()
    assert body["sidecar_mode"] is True
    assert body["available"] is False
    assert body["items"] == []
    assert "disabled in sidecar" in body["message"].lower()


def test_info_stub_returns_200_with_version_in_sidecar(sidecar_env):
    client = TestClient(_make_stubs_app())
    resp = client.get("/info")
    assert resp.status_code == 200
    body = resp.json()
    assert body["sidecar_mode"] is True
    assert body["available"] is False
    assert body["build"] == "sidecar"
    assert isinstance(body["version"], str) and body["version"]


def test_backends_stub_returns_200_in_sidecar(sidecar_env):
    client = TestClient(_make_stubs_app())
    resp = client.get("/backends")
    assert resp.status_code == 200
    body = resp.json()
    assert body["sidecar_mode"] is True
    assert body["available"] is False
    assert body["items"] == []
    assert "disabled in sidecar" in body["message"].lower()


# ─────────────────────────────────────────────────────────────────────
# Stubs — comportament NO-SIDECAR (501 not implemented)
# ─────────────────────────────────────────────────────────────────────


def test_sessions_stub_returns_501_when_not_sidecar(clean_sidecar_env):
    client = TestClient(_make_stubs_app())
    resp = client.get("/sessions")
    assert resp.status_code == 501
    assert "web_ui_module" in resp.json()["detail"]["message"]


def test_info_stub_returns_501_when_not_sidecar(clean_sidecar_env):
    client = TestClient(_make_stubs_app())
    resp = client.get("/info")
    assert resp.status_code == 501


def test_backends_stub_returns_501_when_not_sidecar(clean_sidecar_env):
    client = TestClient(_make_stubs_app())
    resp = client.get("/backends")
    assert resp.status_code == 501


# ─────────────────────────────────────────────────────────────────────
# BUG-NX-4 — restart 501 sidecar
# ─────────────────────────────────────────────────────────────────────


def test_restart_returns_501_in_sidecar_mode(sidecar_env):
    """POST /admin/system/restart retorna 501 quan sidecar (Tauri host gestiona)."""
    from core.endpoints.system import restart_server
    from fastapi import BackgroundTasks, HTTPException

    bg = BackgroundTasks()
    with pytest.raises(HTTPException) as exc:
        asyncio.get_event_loop().run_until_complete(restart_server(bg, _="dummy"))  # type: ignore[arg-type]
    assert exc.value.status_code == 501
    assert "host application" in str(exc.value.detail).lower() or "sidecar mode" in str(exc.value.detail).lower()


# ─────────────────────────────────────────────────────────────────────
# manifest disabled_in_sidecar
# ─────────────────────────────────────────────────────────────────────


def test_manifest_has_disabled_in_sidecar_key():
    """Sanity: la clau existeix al manifest del web_ui_module."""
    try:
        import tomllib
    except ModuleNotFoundError:  # pragma: no cover
        import tomli as tomllib  # type: ignore[no-redef]
    from pathlib import Path
    repo_root = Path(__file__).resolve().parents[2]
    manifest = repo_root / "plugins" / "web_ui_module" / "manifest.toml"
    with open(manifest, "rb") as fh:
        data = tomllib.load(fh)
    assert data["module"].get("disabled_in_sidecar") is True


def test_web_ui_module_initialize_returns_false_in_sidecar(sidecar_env):
    """initialize() retorna False quan disabled_in_sidecar + is_sidecar=True."""
    from plugins.web_ui_module.module import WebUIModule

    module = WebUIModule()
    result = asyncio.get_event_loop().run_until_complete(module.initialize({}))
    assert result is False
    assert module._initialized is False
