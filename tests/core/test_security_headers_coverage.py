"""
Tests for uncovered lines in core/security_headers.py.
Targets: lines 61, 65 (HTTPS-specific headers)
"""
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from core.security_headers import SecurityHeadersMiddleware


def _make_app():
    app = FastAPI()
    app.add_middleware(SecurityHeadersMiddleware)

    @app.get("/test")
    async def test_endpoint():
        return {"ok": True}

    @app.get("/static/file.js")
    async def static_file():
        return {"ok": True}

    return app


class TestSecurityHeadersHttps:
    """Lines 61, 65: HTTPS-specific CSP and HSTS headers."""

    def test_https_upgrade_insecure_requests(self):
        """Line 61: upgrade-insecure-requests added for HTTPS."""
        app = _make_app()
        client = TestClient(app, base_url="https://testserver")
        resp = client.get("/test")
        csp = resp.headers.get("Content-Security-Policy", "")
        assert "upgrade-insecure-requests" in csp

    def test_https_hsts_header(self):
        """Line 65: HSTS header added for HTTPS."""
        app = _make_app()
        client = TestClient(app, base_url="https://testserver")
        resp = client.get("/test")
        hsts = resp.headers.get("Strict-Transport-Security", "")
        assert "max-age=31536000" in hsts

    def test_http_no_upgrade_insecure(self):
        """Line 60: no upgrade-insecure-requests for HTTP."""
        app = _make_app()
        client = TestClient(app)
        resp = client.get("/test")
        csp = resp.headers.get("Content-Security-Policy", "")
        assert "upgrade-insecure-requests" not in csp

    def test_http_no_hsts(self):
        """No HSTS for HTTP."""
        app = _make_app()
        client = TestClient(app)
        resp = client.get("/test")
        assert "Strict-Transport-Security" not in resp.headers


class TestSecurityHeadersStaticPath:
    """Line 90: static paths don't get no-cache headers."""

    def test_static_path_no_cache_control(self):
        app = _make_app()
        client = TestClient(app)
        resp = client.get("/static/file.js")
        # Static paths should NOT have no-cache
        assert "no-store" not in resp.headers.get("Cache-Control", "")
