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


class TestModuleManagerHealth:
    def test_health_response_has_name(self, client):
        response = client.get("/modules/health")
        data = response.json()
        assert data["name"] == "module_manager"


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
