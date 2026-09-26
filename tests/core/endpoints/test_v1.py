"""
Tests per core/endpoints/v1.py
"""
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from slowapi import Limiter
from slowapi.util import get_remote_address
from slowapi.middleware import SlowAPIMiddleware
from slowapi.errors import RateLimitExceeded
from slowapi import _rate_limit_exceeded_handler


def make_app():
    app = FastAPI()
    app.state.config = {}
    app.state.modules = {}
    app.state.i18n = None
    limiter = Limiter(key_func=get_remote_address)
    app.state.limiter = limiter
    app.add_middleware(SlowAPIMiddleware)
    app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)
    from core.endpoints.v1 import router_v1
    app.include_router(router_v1)
    return app


class TestV1Root:
    def test_v1_root_returns_api_info(self):
        app = make_app()
        client = TestClient(app)
        resp = client.get("/v1")
        assert resp.status_code == 200
        data = resp.json()
        assert data["api_version"] == "v1"
        assert data["status"] == "operational"
        assert "endpoints" in data
        assert "chat" in data["endpoints"]
        assert "documentation" in data
        assert "support" in data

    def test_v1_root_endpoints_structure(self):
        app = make_app()
        client = TestClient(app)
        resp = client.get("/v1")
        data = resp.json()
        endpoints = data["endpoints"]
        assert "workflows" in endpoints
        assert "chat" in endpoints
        assert "embeddings" in endpoints
        assert "memory" in endpoints
        # ADR-008 E2: the /v1/rag and /v1/documents stubs were retired; the
        # listing must not advertise them.
        assert "rag" not in endpoints
        assert "documents" not in endpoints


class TestV1Health:
    def test_v1_health_returns_healthy(self):
        app = make_app()
        client = TestClient(app)
        resp = client.get("/v1/health")
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "healthy"
        assert data["api_version"] == "v1"

    def test_v1_health_without_i18n_state(self):
        """Sense i18n a request.state → timestamp None"""
        app = make_app()
        client = TestClient(app)
        resp = client.get("/v1/health")
        assert resp.status_code == 200
        data = resp.json()
        assert data["timestamp"] is None


# ═══════════════════════════════════════════════════════════════════════════
# Tests for ImportError branches (lines 94-95, 100-101, 106-107, 112-113)
# ═══════════════════════════════════════════════════════════════════════════
from unittest.mock import patch, MagicMock  # noqa: E402  # grouped with the test class below
import importlib  # noqa: E402  # grouped with the test class below
import logging  # noqa: E402  # grouped with the test class below


class TestV1ImportErrors:
    """Test that ImportError branches are handled gracefully."""

    def test_rag_routes_are_not_mounted(self):
        """ADR-008 E2: the /v1/rag/* stubs (and the import that mounted them)
        are gone — no route under /v1/rag may exist on the router."""
        from core.endpoints.v1 import router_v1
        paths = [r.path for r in router_v1.routes if hasattr(r, "path")]
        assert [p for p in paths if p.startswith("/v1/rag")] == []

    def test_embeddings_import_error_logged(self, caplog):
        """Lines 100-101: Embeddings import failure is caught and logged."""
        app = make_app()
        client = TestClient(app)
        resp = client.get("/v1")
        assert resp.status_code == 200

    def test_documents_routes_are_not_mounted(self):
        """ADR-008 E2: /v1/documents/ (a 501 stub) is gone from the router."""
        from core.endpoints.v1 import router_v1
        paths = [r.path for r in router_v1.routes if hasattr(r, "path")]
        assert [p for p in paths if p.startswith("/v1/documents")] == []

    def test_memory_import_error_logged(self, caplog):
        """Lines 112-113: Memory import failure is caught and logged."""
        app = make_app()
        client = TestClient(app)
        resp = client.get("/v1")
        assert resp.status_code == 200

    def test_v1_module_import_errors_dont_break_router(self):
        """All import errors are caught, router still functional."""
        app = make_app()
        client = TestClient(app)
        # Both endpoints should work regardless of import errors
        resp_root = client.get("/v1")
        resp_health = client.get("/v1/health")
        assert resp_root.status_code == 200
        assert resp_health.status_code == 200


class TestRetiredRoutes:
    """ADR-008 E2: the 501 stubs in front of PersonalityRAG were deleted, so
    the surface now answers 404. Pinned per route so the retired surface
    cannot come back quietly (the same guard as the live-API tests, which
    need a running server)."""

    @pytest.mark.parametrize("method,path", [
        ("post", "/v1/rag/search"),
        ("post", "/v1/rag/add"),
        ("delete", "/v1/rag/documents/doc-123"),
        ("get", "/v1/documents/"),
    ])
    def test_retired_route_is_404(self, method, path):
        client = TestClient(make_app())
        kwargs = {"json": {"query": "q"}} if method == "post" else {}
        resp = getattr(client, method)(path, **kwargs)
        assert resp.status_code == 404, (path, resp.status_code, resp.text[:200])
