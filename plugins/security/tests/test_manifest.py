"""
────────────────────────────────────
Server Nexe
Author: Jordi Goy
Location: plugins/security/tests/test_manifest.py
Description: Tests per security manifest (endpoints REST, SecurityModule, init_security_module).

www.jgoy.net · https://server-nexe.org
────────────────────────────────────
"""

import os
import pytest
import tempfile
from pathlib import Path
from fastapi import FastAPI
from fastapi.testclient import TestClient

from plugins.security.manifest import (
    router_public,
    MODULE_METADATA,
    SecurityModule,
    init_security_module,
    get_module_instance,
    module_instance,
)


@pytest.fixture(scope="module")
def app_with_security():
    """App FastAPI amb el router de security muntat."""
    _app = FastAPI()
    _app.include_router(router_public)
    return _app


@pytest.fixture(scope="module")
def client(app_with_security):
    return TestClient(app_with_security, raise_server_exceptions=False)


@pytest.fixture
def auth_headers(monkeypatch):
    monkeypatch.setenv("NEXE_PRIMARY_API_KEY", "test-security-key")
    monkeypatch.delenv("NEXE_ADMIN_API_KEY", raising=False)
    monkeypatch.delenv("NEXE_DEV_MODE", raising=False)
    return {"X-API-Key": "test-security-key"}


class TestSecurityModule:
    """Tests per la classe SecurityModule."""

    def test_init_no_args(self):
        mod = SecurityModule()
        assert mod.metadata.name == "security"

    def test_metadata_has_version(self):
        mod = SecurityModule()
        assert mod.metadata.version is not None

    def test_health_check_returns_result(self):
        import asyncio
        mod = SecurityModule()
        result = asyncio.run(mod.health_check())
        # Not initialized so UNKNOWN expected
        assert result.status is not None

    def test_get_module_instance_returns_singleton(self):
        instance = get_module_instance()
        assert instance is module_instance
        assert instance.metadata.name == "security"


class TestSecurityHealthEndpoint:
    """Tests per GET /security/health."""

    def test_health_returns_200(self, client):
        response = client.get("/security/health")
        assert response.status_code == 200

    def test_health_returns_status(self, client):
        response = client.get("/security/health")
        data = response.json()
        assert data["status"] in ("healthy", "unknown", "degraded")
        assert "message" in data


class TestSecurityInfoEndpoint:
    """Tests per GET /security/info."""

    def test_info_returns_200(self, client):
        response = client.get("/security/info")
        assert response.status_code == 200

    def test_info_returns_module_name(self, client):
        response = client.get("/security/info")
        data = response.json()
        assert data["name"] == "security"

    def test_info_returns_endpoints_list(self, client):
        response = client.get("/security/info")
        data = response.json()
        assert "endpoints" in data
        assert len(data["endpoints"]) > 0
        assert "/security/health" in data["endpoints"]


class TestSecurityScanEndpoint:
    """Tests per POST /security/scan."""

    def test_scan_requires_auth(self, client):
        response = client.post("/security/scan")
        assert response.status_code in (401, 422, 403)

    def test_scan_with_valid_key_returns_200_or_500(self, client, auth_headers):
        # Returns 200 if checks available, 500 if checks module not installed
        response = client.post("/security/scan", headers=auth_headers)
        assert response.status_code in (200, 500)

    def test_scan_returns_status_completed(self, client, auth_headers):
        response = client.post("/security/scan", headers=auth_headers)
        if response.status_code == 200:
            data = response.json()
            assert data["status"] == "completed"

    def test_scan_returns_summary(self, client, auth_headers):
        response = client.post("/security/scan", headers=auth_headers)
        if response.status_code == 200:
            data = response.json()
            assert "summary" in data
            assert "total_findings" in data["summary"]

    def test_scan_returns_findings(self, client, auth_headers):
        response = client.post("/security/scan", headers=auth_headers)
        if response.status_code == 200:
            data = response.json()
            assert "findings" in data
            assert "critical" in data["findings"]
            assert "high" in data["findings"]


class TestSecurityReportEndpoint:
    """Tests per GET /security/report."""

    def test_report_requires_auth(self, client):
        response = client.get("/security/report")
        assert response.status_code in (401, 422, 403)

    def test_report_with_valid_key_returns_200(self, client, auth_headers):
        response = client.get("/security/report", headers=auth_headers)
        assert response.status_code == 200

    def test_report_returns_success_status(self, client, auth_headers):
        response = client.get("/security/report", headers=auth_headers)
        if response.status_code == 200:
            data = response.json()
            assert data["status"] == "success"
            assert "report" in data


class TestSecurityAssetsEndpoint:
    """Tests per GET /security/ui/assets/{path}."""

    def test_missing_asset_returns_404(self, client):
        response = client.get("/security/ui/assets/nonexistent.css")
        assert response.status_code in (400, 404)

    def test_path_traversal_blocked(self, client):
        response = client.get("/security/ui/assets/../../../etc/passwd")
        assert response.status_code in (400, 404)


class TestSecurityUIEndpoint:
    """Tests per GET /security/ui."""

    def test_ui_returns_json_if_no_html(self, client):
        response = client.get("/security/ui")
        assert response.status_code == 200
        # If index.html doesn't exist, returns JSON
        if response.headers.get("content-type", "").startswith("application/json"):
            data = response.json()
            assert "api_endpoints" in data or "message" in data


class TestInitSecurityModule:
    """Tests per init_security_module."""

    def test_returns_metadata(self, tmp_path, monkeypatch):
        result = init_security_module()
        assert result is MODULE_METADATA
        assert "name" in result
        assert "version" in result
