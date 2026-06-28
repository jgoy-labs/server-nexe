"""
────────────────────────────────────
Server Nexe
Location: tests/fixos/test_B214.py
Description: TDD fix for B214 — GET /modules/{name}/routes retorna 200 per moduls inexistents.
────────────────────────────────────
"""

from unittest.mock import MagicMock

import pytest


def _make_app_with_integrator(known_modules=None):
    """Crea una app FastAPI minima amb un api_integrator mock configurat."""
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    from core.endpoints.modules import router

    app = FastAPI()
    app.include_router(router)

    # Mock integrator que coneix 'memory' pero no 'no-existeix'
    integrator = MagicMock()
    known = known_modules or ["memory"]

    def mock_is_module_integrated(name):
        return name in known

    def mock_get_module_routes(name):
        if name in known:
            return ["/memory/store", "/memory/search"]
        return []

    integrator.is_module_integrated = mock_is_module_integrated
    integrator.get_module_routes = mock_get_module_routes

    # Injectar al app.state (que es com ho llegeix get_api_integrator)
    app.state.api_integrator = integrator

    # Override get_api_integrator per a que retorni el mock
    from core.endpoints.modules import get_api_integrator
    app.dependency_overrides[get_api_integrator] = lambda: integrator

    # Override require_api_key per no necesitar clau real als tests
    from plugins.security.core.auth_dependencies import require_api_key
    app.dependency_overrides[require_api_key] = lambda: None

    return TestClient(app)


def test_unknown_module_returns_404():
    """B214: GET /modules/no-existeix/routes ha de retornar 404, no 200."""
    client = _make_app_with_integrator(known_modules=["memory"])
    response = client.get("/modules/no-existeix/routes")
    assert response.status_code == 404, (
        f"B214: mòdul inexistent ha de donar 404, pero va retornar {response.status_code}"
    )


def test_known_module_returns_200():
    """Regressio: mòdul conegut segueix retornant 200 amb les rutes."""
    client = _make_app_with_integrator(known_modules=["memory"])
    response = client.get("/modules/memory/routes")
    assert response.status_code == 200, (
        f"Regressio: mòdul conegut ha de donar 200, pero va retornar {response.status_code}"
    )
    data = response.json()
    assert data.get("status") in ("ok", "success"), f"Estat inesperat: {data}"
    assert data.get("routes") is not None, "Ha de retornar la llista de rutes"
