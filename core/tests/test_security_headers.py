"""
Tests per core/security_headers.py — SecurityHeadersMiddleware
"""
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from fastapi.responses import JSONResponse
from core.security_headers import SecurityHeadersMiddleware


def make_app():
    app = FastAPI()
    app.add_middleware(SecurityHeadersMiddleware)

    @app.get("/test")
    async def test_endpoint():
        return {"ok": True}

    @app.get("/static/style.css")
    async def static_endpoint():
        return JSONResponse({"ok": True})

    return app


class TestSecurityHeadersMiddleware:
    def test_x_frame_options_deny(self):
        app = make_app()
        client = TestClient(app)
        resp = client.get("/test")
        assert resp.headers.get("X-Frame-Options") == "DENY"

    def test_x_content_type_options_nosniff(self):
        app = make_app()
        client = TestClient(app)
        resp = client.get("/test")
        assert resp.headers.get("X-Content-Type-Options") == "nosniff"

    def test_content_security_policy_present(self):
        app = make_app()
        client = TestClient(app)
        resp = client.get("/test")
        csp = resp.headers.get("Content-Security-Policy", "")
        assert "default-src" in csp
        assert "script-src" in csp
        assert "frame-ancestors 'none'" in csp

    def test_x_xss_protection(self):
        app = make_app()
        client = TestClient(app)
        resp = client.get("/test")
        assert resp.headers.get("X-XSS-Protection") == "0"

    def test_referrer_policy(self):
        app = make_app()
        client = TestClient(app)
        resp = client.get("/test")
        assert resp.headers.get("Referrer-Policy") == "strict-origin-when-cross-origin"

    def test_permissions_policy(self):
        app = make_app()
        client = TestClient(app)
        resp = client.get("/test")
        perm = resp.headers.get("Permissions-Policy", "")
        assert "camera=()" in perm
        assert "microphone=()" in perm

    def test_http_request_no_hsts(self):
        """HTTP normal no ha de tenir HSTS"""
        app = make_app()
        client = TestClient(app)
        resp = client.get("/test")
        # TestClient usa HTTP per defecte → sense HSTS
        assert "Strict-Transport-Security" not in resp.headers

    def test_non_static_path_has_cache_control_no_store(self):
        app = make_app()
        client = TestClient(app)
        resp = client.get("/test")
        cc = resp.headers.get("Cache-Control", "")
        assert "no-store" in cc

    def test_static_path_no_cache_control_no_store(self):
        """Rutes /static/ no han de tenir Cache-Control: no-store"""
        app = make_app()
        client = TestClient(app)
        resp = client.get("/static/style.css")
        cc = resp.headers.get("Cache-Control", "")
        # Les rutes estàtiques no han de tenir no-store
        assert "no-store" not in cc

    def test_x_permitted_cross_domain_policies(self):
        app = make_app()
        client = TestClient(app)
        resp = client.get("/test")
        assert resp.headers.get("X-Permitted-Cross-Domain-Policies") == "none"

    def test_csp_no_upgrade_insecure_on_http(self):
        """HTTP no ha de tenir upgrade-insecure-requests al CSP"""
        app = make_app()
        client = TestClient(app)
        resp = client.get("/test")
        csp = resp.headers.get("Content-Security-Policy", "")
        assert "upgrade-insecure-requests" not in csp
