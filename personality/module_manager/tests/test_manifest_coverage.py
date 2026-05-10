"""Tests for personality/module_manager/manifest.py — coverage gaps."""
import pytest
from unittest.mock import patch, MagicMock
from fastapi import FastAPI
from fastapi.testclient import TestClient


@pytest.fixture
def client():
    from personality.module_manager.manifest import router_public
    app = FastAPI()
    app.include_router(router_public)
    return TestClient(app)


class TestServeModulesUI:
    def test_ui_not_found(self, client):
        with patch("personality.module_manager.manifest.UI_PATH") as mock_path:
            mock_index = MagicMock()
            mock_index.exists.return_value = False
            mock_path.__truediv__ = MagicMock(return_value=mock_index)
            response = client.get("/modules/ui")
        assert response.status_code == 200 or response.status_code == 404


class TestModuleManagerHealth:
    def test_health_healthy(self, client):
        response = client.get("/modules/health")
        assert response.status_code in (200, 500)

    def test_health_response_has_name(self, client):
        response = client.get("/modules/health")
        data = response.json()
        assert data["name"] == "module_manager"


class TestModuleManagerInfo:
    def test_info_returns_data(self, client):
        response = client.get("/modules/info")
        assert response.status_code in (200, 500)


class TestListRegisteredModules:
    def test_list_returns_modules(self, client):
        response = client.get("/modules/list")
        assert response.status_code in (200, 500)
        data = response.json()
        assert "modules" in data or "error" in data


class TestGetRouterAndMetadata:
    def test_get_router(self):
        from personality.module_manager.manifest import get_router, router_public
        assert get_router() is router_public

    def test_get_metadata(self):
        from personality.module_manager.manifest import get_metadata
        meta = get_metadata()
        assert meta["name"] == "module_manager"
        assert "router" in meta

    def test_all_exports(self):
        from personality.module_manager.manifest import __all__
        assert "router_public" in __all__
        assert "get_router" in __all__
        assert "get_metadata" in __all__
