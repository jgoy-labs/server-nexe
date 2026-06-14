"""
Tests for core/security_headers.py — SecurityHeadersMiddleware
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
        """Normal HTTP must not have HSTS"""
        app = make_app()
        client = TestClient(app)
        resp = client.get("/test")
        # TestClient uses HTTP by default → no HSTS
        assert "Strict-Transport-Security" not in resp.headers

    def test_non_static_path_has_cache_control_no_store(self):
        app = make_app()
        client = TestClient(app)
        resp = client.get("/test")
        cc = resp.headers.get("Cache-Control", "")
        assert "no-store" in cc

    def test_static_path_no_cache_control_no_store(self):
        """/static/ routes must not have Cache-Control: no-store"""
        app = make_app()
        client = TestClient(app)
        resp = client.get("/static/style.css")
        cc = resp.headers.get("Cache-Control", "")
        # Static routes must not have no-store
        assert "no-store" not in cc

    def test_x_permitted_cross_domain_policies(self):
        app = make_app()
        client = TestClient(app)
        resp = client.get("/test")
        assert resp.headers.get("X-Permitted-Cross-Domain-Policies") == "none"

    def test_csp_no_upgrade_insecure_on_http(self):
        """HTTP must not have upgrade-insecure-requests in CSP"""
        app = make_app()
        client = TestClient(app)
        resp = client.get("/test")
        csp = resp.headers.get("Content-Security-Policy", "")
        assert "upgrade-insecure-requests" not in csp


class TestSecurityHeadersSidecar:
    """B083: sidecar mode relaxes script-src to allow the Web UI's inline
    scripts, but must NOT enable 'unsafe-eval' (no eval()/new Function() exists
    in plugins/web_ui_module — verified by grep)."""

    @pytest.fixture
    def sidecar_env(self, monkeypatch):
        from core import sidecar_config

        # Set the required sidecar vars so get_sidecar_config() builds a real
        # is_sidecar=True config (otherwise fail-fast → middleware except branch
        # → strict CSP → false green that hides the bug).
        monkeypatch.setenv("NEXE_SIDECAR", "1")
        monkeypatch.setenv("NEXE_PRIMARY_API_KEY", "test-key")
        monkeypatch.setenv("NEXE_PORT", "9119")
        monkeypatch.delenv("NEXE_SERVER_PORT", raising=False)
        sidecar_config.reset_sidecar_config()
        assert sidecar_config.get_sidecar_config().is_sidecar is True
        yield
        sidecar_config.reset_sidecar_config()

    def test_sidecar_csp_no_unsafe_eval(self, sidecar_env):
        app = make_app()
        client = TestClient(app)
        resp = client.get("/test")
        csp = resp.headers.get("Content-Security-Policy", "")
        # Inline scripts are still allowed (the Web UI needs them)…
        assert "'unsafe-inline'" in csp
        # …but eval must never be enabled.
        assert "'unsafe-eval'" not in csp
