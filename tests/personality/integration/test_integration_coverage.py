"""
Tests for uncovered lines in personality/integration/api_integrator.py and route_manager.py.
"""
import pytest
from unittest.mock import MagicMock, patch
from fastapi import FastAPI, APIRouter
from fastapi.routing import APIRoute
from personality.data.models import ModuleInfo, ModuleState
from pathlib import Path


class TestAPIIntegrator:

    @pytest.fixture
    def integrator(self):
        from personality.integration.api_integrator import APIIntegrator
        app = FastAPI()
        return APIIntegrator(app)

    def test_integrate_no_api_components(self, integrator):
        """Module with no API components returns False."""
        module = MagicMock(spec=[])  # No router, api_router, etc.
        result = integrator.integrate_module_api("test", module)
        assert result is False

    def test_integrate_with_router(self, integrator):
        """Module with router attribute."""
        router = APIRouter()

        @router.get("/test")
        async def test_endpoint():
            return {}

        module = MagicMock()
        module.router = router
        result = integrator.integrate_module_api("test", module)
        assert result is True
        assert integrator.is_module_integrated("test")

    def test_integrate_with_app(self, integrator):
        """Module with FastAPI app attribute."""
        sub_app = FastAPI()
        module = MagicMock()
        module.router = None
        module.api_router = None
        module.routes = None
        module.app = sub_app
        result = integrator.integrate_module_api("test_app", module)
        assert result is True

    def test_remove_module_api_not_integrated(self, integrator):
        """Remove non-integrated module returns True."""
        result = integrator.remove_module_api("nonexistent")
        assert result is True

    def test_remove_module_api_success(self, integrator):
        """Remove integrated module."""
        router = APIRouter()
        module = MagicMock()
        module.router = router
        integrator.integrate_module_api("test", module)

        result = integrator.remove_module_api("test")
        assert result is True
        assert not integrator.is_module_integrated("test")

    def test_get_integration_stats(self, integrator):
        result = integrator.get_integration_stats()
        assert "total_modules_integrated" in result
        assert "total_routes_registered" in result

    def test_get_module_routes_empty(self, integrator):
        result = integrator.get_module_routes("nonexistent")
        assert result == []

    def test_determine_api_prefix_from_manifest(self, integrator):
        module_info = MagicMock()
        module_info.manifest = {"api": {"prefix": "/custom"}}
        result = integrator._determine_api_prefix("test", module_info)
        assert result == "/custom"

    def test_determine_api_prefix_from_instance(self, integrator):
        module_info = MagicMock()
        module_info.manifest = {}
        module_info.instance = MagicMock()
        module_info.instance.api_prefix = "/inst"
        result = integrator._determine_api_prefix("test", module_info)
        assert result == "/inst"

    def test_determine_api_prefix_default(self, integrator):
        result = integrator._determine_api_prefix("test_mod", None)
        assert result == "/api/test_mod"

    def test_handle_integration_error(self, integrator):
        result = integrator._handle_integration_error("test", Exception("error"))
        assert result is False


class TestRouteManager:

    @pytest.fixture
    def rm(self):
        from personality.integration.route_manager import RouteManager
        app = FastAPI()
        return RouteManager(app)

    def test_register_router_routes(self, rm):
        router = APIRouter()

        @router.get("/hello")
        async def hello():
            return {}

        routes = rm.register_module_routes("test", router, "/api/test", "router")
        assert len(routes) > 0

    def test_register_app_routes(self, rm):
        sub_app = FastAPI()

        @sub_app.get("/status")
        async def status():
            return {}

        routes = rm.register_module_routes("test", sub_app, "/mounted", "app")
        assert isinstance(routes, list)

    def test_register_endpoint_routes(self, rm):
        """Empty endpoints list."""
        routes = rm.register_module_routes("test", [], "/api", "endpoints")
        assert routes == []

    def test_route_conflict_detection(self, rm):
        router = APIRouter()

        @router.get("/hello")
        async def hello():
            return {}

        rm.register_module_routes("mod1", router, "/api", "router")
        # Register same path from different module
        conflicted = rm._check_route_conflict("/api/hello", "mod2")
        assert conflicted is True

    def test_remove_module_routes(self, rm):
        router = APIRouter()

        @router.get("/hello")
        async def hello():
            return {}

        rm.register_module_routes("test", router, "/api", "router")
        count = rm.remove_module_routes("test")
        assert count > 0

    def test_remove_nonexistent_module(self, rm):
        count = rm.remove_module_routes("nonexistent")
        assert count == 0

    def test_get_all_registered_routes(self, rm):
        result = rm.get_all_registered_routes()
        assert isinstance(result, dict)

    def test_get_route_conflicts(self, rm):
        result = rm.get_route_conflicts()
        assert isinstance(result, dict)
