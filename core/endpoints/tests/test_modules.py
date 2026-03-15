"""
Tests per core/endpoints/modules.py
"""
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from unittest.mock import MagicMock
from slowapi import Limiter
from slowapi.util import get_remote_address
from slowapi.middleware import SlowAPIMiddleware
from slowapi.errors import RateLimitExceeded
from slowapi import _rate_limit_exceeded_handler


def make_app(api_integrator=None, i18n=None):
    app = FastAPI()
    app.state.config = {}
    app.state.modules = {}
    app.state.i18n = i18n
    limiter = Limiter(key_func=get_remote_address)
    app.state.limiter = limiter
    app.add_middleware(SlowAPIMiddleware)
    app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)

    # Importar router i sobreescriure la dependència get_api_integrator
    from core.endpoints.modules import router, get_api_integrator, get_i18n
    app.include_router(router)

    # Override de la dependència
    app.dependency_overrides[get_api_integrator] = lambda: api_integrator

    return app


class TestConfigureDependencies:
    def test_configure_dependencies_noop(self):
        from core.endpoints.modules import configure_dependencies
        # No ha de llençar excepcions
        configure_dependencies(MagicMock(), MagicMock())


class TestListIntegratedModules:
    def test_with_api_integrator(self):
        mock_integrator = MagicMock()
        mock_integrator.get_integration_stats.return_value = {
            "total_modules": 2,
            "total_routes": 10
        }
        app = make_app(api_integrator=mock_integrator)
        client = TestClient(app)
        resp = client.get("/modules")
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "correcte"
        assert data["data"]["total_modules"] == 2

    def test_without_api_integrator(self):
        app = make_app(api_integrator=None)
        client = TestClient(app)
        resp = client.get("/modules")
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "error"
        assert "Integrador" in data.get("message", "")

    def test_with_i18n_and_integrator(self):
        mock_integrator = MagicMock()
        mock_integrator.get_integration_stats.return_value = {"total": 1}
        mock_i18n = MagicMock()
        mock_i18n.t.side_effect = lambda key: f"t:{key}"
        app = make_app(api_integrator=mock_integrator, i18n=mock_i18n)
        client = TestClient(app)
        resp = client.get("/modules")
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"].startswith("t:")

    def test_with_i18n_without_integrator(self):
        mock_i18n = MagicMock()
        mock_i18n.t.side_effect = lambda key: f"t:{key}"
        app = make_app(api_integrator=None, i18n=mock_i18n)
        client = TestClient(app)
        resp = client.get("/modules")
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"].startswith("t:")


class TestGetModuleRoutes:
    def test_with_api_integrator(self):
        mock_integrator = MagicMock()
        mock_integrator.get_module_routes.return_value = ["/module/route1", "/module/route2"]
        app = make_app(api_integrator=mock_integrator)
        client = TestClient(app)
        resp = client.get("/modules/security/routes")
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "correcte"
        assert data["module"] == "security"
        assert "/module/route1" in data["routes"]

    def test_without_api_integrator(self):
        app = make_app(api_integrator=None)
        client = TestClient(app)
        resp = client.get("/modules/security/routes")
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "error"
        assert "Integrador" in data.get("message", "")
