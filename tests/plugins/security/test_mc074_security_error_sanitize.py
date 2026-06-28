"""
MC-074 — `POST /security/scan` i `GET /security/report` no han de filtrar
`str(e)` (detalls interns) al cos de la resposta. Missatge genèric al client;
`str(e)` només al log.
"""
from __future__ import annotations

import pytest
from unittest.mock import MagicMock, PropertyMock
from fastapi import FastAPI
from fastapi.testclient import TestClient
from slowapi.errors import RateLimitExceeded
from slowapi import _rate_limit_exceeded_handler

import plugins.security.api.routes as sec_routes
from plugins.security.api.routes import create_router
from plugins.security.core.auth import require_api_key
from core.dependencies import limiter as core_limiter

LEAK = "LEAK_/Users/secret/internal_path_4242"


@pytest.fixture(autouse=True)
def _no_rate_limit(monkeypatch):
    # /scan és 2/minute; el decorador usa el singleton core.dependencies.limiter
    # → comptes compartits a la suite. Desactivar-lo evita 429 espuris.
    monkeypatch.setattr(core_limiter, "enabled", False)


def _client(module) -> TestClient:
    app = FastAPI()
    app.state.limiter = core_limiter
    app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)
    app.include_router(create_router(module))
    app.dependency_overrides[require_api_key] = lambda: "test-key"
    return TestClient(app, raise_server_exceptions=False)


def _boom(*args, **kwargs):
    raise Exception(LEAK)


def test_scan_error_does_not_leak(monkeypatch):
    monkeypatch.setattr(sec_routes, "_build_security_checks", _boom)
    r = _client(MagicMock()).post("/security/scan", headers={"X-API-Key": "k"})
    assert r.status_code == 500
    assert LEAK not in r.text


def test_report_error_does_not_leak():
    m = MagicMock()
    type(m.metadata).version = PropertyMock(side_effect=RuntimeError(LEAK))
    r = _client(m).get("/security/report", headers={"X-API-Key": "k"})
    assert r.status_code == 500
    assert LEAK not in r.text
