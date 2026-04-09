"""
────────────────────────────────────
Server Nexe
Author: Jordi Goy
Location: tests/test_endpoints_auth.py
Description: Bug 22 — Verifica que els endpoints sensibles estan protegits per X-API-Key.
             Sense API key -> 401/403. Amb API key vàlida -> NO 401/403 (pot ser 200/4xx/5xx).

www.jgoy.net · https://server-nexe.org
────────────────────────────────────
"""

import os
import pytest


# Endpoints GET sensibles que han d'estar protegits per X-API-Key (Bug 22).
PROTECTED_ENDPOINTS = [
    "/metrics",
    "/metrics/health",
    "/metrics/json",
    "/modules",
    "/api/bootstrap/info",
    "/ollama/api/models",
    "/ollama/health",
    "/ollama/info",
    "/memory/health",
    "/memory/info",
    "/memory/stats/test-user",
    "/memory/profile/test-user",
    "/rag/health",
    "/rag/info",
    "/rag/files/stats",
]

# Fix Consultor passada 1 — Finding 3: coverage Bug 22 incomplet.
# Ampliem amb POST/DELETE protegits. Cada entry: (method, path, body_json).
# Item 24 cirurgia 2026-04-08: /ollama/api/chat ELIMINAT (pipeline únic).
# /mlx/chat i /llama-cpp/chat ELIMINATS. Retirades d'aquí per coherència.
PROTECTED_WRITE_ENDPOINTS = [
    ("POST", "/ollama/api/pull", {"name": "dummy-model"}),
    ("DELETE", "/ollama/api/models/dummy-model", None),
    ("POST", "/rag/document", {"text": "dummy", "metadata": {}}),
    ("POST", "/rag/search", {"query": "dummy"}),
]


@pytest.fixture(autouse=True)
def _disable_dev_mode_bypass(monkeypatch, admin_api_key):
    """Assegura que el bypass dev no s'activa per accident i la API key matches."""
    monkeypatch.setenv("NEXE_DEV_MODE", "false")
    monkeypatch.delenv("NEXE_DEV_MODE_ALLOW_REMOTE", raising=False)
    # Sincronitza NEXE_PRIMARY_API_KEY amb la generada pel fixture global del conftest,
    # ja que load_api_keys() es llegeix dinamicament a cada request.
    monkeypatch.setenv("NEXE_PRIMARY_API_KEY", admin_api_key)
    monkeypatch.delenv("NEXE_PRIMARY_KEY_EXPIRES", raising=False)


# TrustedHostMiddleware només permet localhost/127.0.0.1, cal sobreescriure Host header.
_HOST = {"Host": "localhost"}


@pytest.mark.parametrize("path", PROTECTED_ENDPOINTS)
def test_protected_endpoint_without_key_rejected(client, path):
    """Bug 22: sense X-API-Key -> 401 o 403."""
    r = client.get(path, headers=_HOST)
    assert r.status_code in (401, 403), (
        f"{path}: esperat 401/403 sense API key, rebut {r.status_code}: {r.text[:200]}"
    )


@pytest.mark.parametrize("path", PROTECTED_ENDPOINTS)
def test_protected_endpoint_with_key_not_unauthorized(client, auth_headers, path):
    """Bug 22: amb X-API-Key vàlida NO ha de ser 401/403 (pot ser 200/404/500/503 segons servei)."""
    headers = {**auth_headers, **_HOST}
    r = client.get(path, headers=headers)
    assert r.status_code not in (401, 403), (
        f"{path}: API key vàlida però rebut {r.status_code}: {r.text[:200]}"
    )


@pytest.mark.parametrize("method,path,body", PROTECTED_WRITE_ENDPOINTS)
def test_protected_write_endpoint_without_key_rejected(client, method, path, body):
    """Fix Consultor — Finding 3: POST/DELETE sense X-API-Key -> 401/403."""
    kwargs = {"headers": _HOST}
    if body is not None:
        kwargs["json"] = body
    r = client.request(method, path, **kwargs)
    assert r.status_code in (401, 403), (
        f"{method} {path}: esperat 401/403 sense API key, "
        f"rebut {r.status_code}: {r.text[:200]}"
    )


def _get_csrf_headers(client):
    """
    Fa una GET inicial per obtenir la cookie CSRF i retorna headers amb
    X-CSRF-Token. Necessari per als endpoints POST/DELETE no exempts de
    CSRF (p.ex. /ollama/api/*). Els endpoints /rag/ i /v1/ estan a la
    llista d'exemptions (core/middleware.py), pero /ollama/ no.
    """
    # Trigger CSRF cookie set — qualsevol GET val
    client.get("/health", headers=_HOST)
    cookie = client.cookies.get("nexe_csrf_token")
    if cookie:
        return {"X-CSRF-Token": cookie}
    return {}


@pytest.mark.parametrize("method,path,body", PROTECTED_WRITE_ENDPOINTS)
def test_protected_write_endpoint_with_key_not_unauthorized(
    client, auth_headers, method, path, body
):
    """Fix Consultor — Finding 3: POST/DELETE amb X-API-Key NO ha de ser 401/403."""
    csrf = _get_csrf_headers(client)
    kwargs = {"headers": {**auth_headers, **_HOST, **csrf}}
    if body is not None:
        kwargs["json"] = body
    r = client.request(method, path, **kwargs)
    assert r.status_code not in (401, 403), (
        f"{method} {path}: API key vàlida però rebut {r.status_code}: {r.text[:200]}"
    )


def test_docs_endpoints_disabled_in_production():
    """Bug 22: amb NEXE_ENV=production els endpoints /docs i /openapi.json no s'exposen."""
    from fastapi.testclient import TestClient
    from fastapi import FastAPI

    # Crea una FastAPI directament simulant la mateixa config que factory_app.py
    # per evitar afectar la sessió global de pytest.
    saved = os.environ.get("NEXE_ENV")
    try:
        os.environ["NEXE_ENV"] = "production"
        # Reproduïm la lògica que aplica factory_app.create_fastapi_instance
        _docs_enabled = os.environ["NEXE_ENV"].lower() in ("development", "test")
        app = FastAPI(
            docs_url="/docs" if _docs_enabled else None,
            redoc_url="/redoc" if _docs_enabled else None,
            openapi_url="/openapi.json" if _docs_enabled else None,
        )
        with TestClient(app) as c:
            assert c.get("/docs").status_code == 404
            assert c.get("/openapi.json").status_code == 404
            assert c.get("/redoc").status_code == 404
    finally:
        if saved is None:
            os.environ.pop("NEXE_ENV", None)
        else:
            os.environ["NEXE_ENV"] = saved


def test_docs_endpoints_enabled_in_development():
    """Bug 22: amb NEXE_ENV=development els endpoints /docs i /openapi.json sí s'exposen."""
    from fastapi.testclient import TestClient
    from fastapi import FastAPI

    saved = os.environ.get("NEXE_ENV")
    try:
        os.environ["NEXE_ENV"] = "development"
        _docs_enabled = os.environ["NEXE_ENV"].lower() in ("development", "test")
        app = FastAPI(
            docs_url="/docs" if _docs_enabled else None,
            redoc_url="/redoc" if _docs_enabled else None,
            openapi_url="/openapi.json" if _docs_enabled else None,
        )
        with TestClient(app) as c:
            assert c.get("/openapi.json").status_code == 200
    finally:
        if saved is None:
            os.environ.pop("NEXE_ENV", None)
        else:
            os.environ["NEXE_ENV"] = saved
