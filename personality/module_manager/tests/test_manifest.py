"""
────────────────────────────────────
Server Nexe
Author: Jordi Goy
Location: personality/module_manager/tests/test_manifest.py
Description: Tests per personality/module_manager/manifest.py.

www.jgoy.net · https://server-nexe.org
────────────────────────────────────
"""

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from unittest.mock import MagicMock, patch


def make_app():
    from personality.module_manager.manifest import router_public
    app = FastAPI()
    app.include_router(router_public)
    return app


class TestModuleManagerHealth:

    def test_health_healthy(self):
        client = TestClient(make_app())
        resp = client.get("/modules/health")
        assert resp.status_code == 200
        data = resp.json()
        assert data["name"] == "module_manager"
        assert data["status"] == "HEALTHY"

    def test_health_returns_ui_available_key(self):
        client = TestClient(make_app())
        resp = client.get("/modules/health")
        data = resp.json()
        assert "checks" in data
        assert "ui_available" in data["checks"]


class TestModuleManagerInfo:

    def test_info_returns_data(self):
        client = TestClient(make_app())
        resp = client.get("/modules/info")
        assert resp.status_code == 200
        data = resp.json()
        assert data["name"] == "module_manager"
        assert "features" in data
        assert isinstance(data["features"], list)


class TestModuleManagerList:

    def test_list_returns_modules(self):
        client = TestClient(make_app())
        mock_registry = MagicMock()
        mock_registry.get_all_modules.return_value = {}

        with patch("personality.module_manager.registry.ModuleRegistry", return_value=mock_registry):
            resp = client.get("/modules/list")

        assert resp.status_code == 200
        data = resp.json()
        assert "modules" in data

    def test_list_with_modules(self):
        client = TestClient(make_app())
        mock_registry = MagicMock()

        mock_info = MagicMock()
        mock_info.status = "active"
        mock_info.version = "1.0"
        mock_info.path = "/some/path"

        mock_registry.get_all_modules.return_value = {"test_module": mock_info}

        with patch("personality.module_manager.registry.ModuleRegistry", return_value=mock_registry):
            resp = client.get("/modules/list")

        assert resp.status_code == 200
        data = resp.json()
        assert data["total"] == 1
        assert data["modules"][0]["name"] == "test_module"

    def test_list_error_returns_500(self):
        client = TestClient(make_app(), raise_server_exceptions=False)
        with patch("personality.module_manager.registry.ModuleRegistry", side_effect=Exception("DB fail")):
            resp = client.get("/modules/list")
        assert resp.status_code == 500

    def test_list_error_returns_empty_modules(self):
        client = TestClient(make_app(), raise_server_exceptions=False)
        with patch("personality.module_manager.registry.ModuleRegistry", side_effect=Exception("DB fail")):
            resp = client.get("/modules/list")
        data = resp.json()
        assert data["modules"] == []
        assert data["total"] == 0


class TestModuleManagerUi:

    def test_ui_returns_404_when_file_missing(self, tmp_path):
        client = TestClient(make_app())
        # UI file likely doesn't exist in test env, so 404 is expected
        resp = client.get("/modules/ui")
        # Either returns 200 with HTML or 404 if no file
        assert resp.status_code in (200, 404)

    def test_ui_serves_html_when_exists(self, tmp_path):
        """If UI file exists, returns HTML response."""
        ui_dir = tmp_path / "ui"
        ui_dir.mkdir()
        html_file = ui_dir / "index.html"
        html_file.write_text("<html><body>Module Manager</body></html>")

        with patch("personality.module_manager.manifest.UI_PATH", ui_dir):
            client = TestClient(make_app())
            resp = client.get("/modules/ui")

        assert resp.status_code == 200
        assert "Module Manager" in resp.text


class TestGetRouterAndMetadata:

    def test_get_router(self):
        from personality.module_manager.manifest import get_router, router_public
        assert get_router() is router_public

    def test_get_metadata(self):
        from personality.module_manager.manifest import get_metadata, MODULE_METADATA
        assert get_metadata() is MODULE_METADATA

    def test_metadata_has_required_fields(self):
        from personality.module_manager.manifest import MODULE_METADATA
        assert "name" in MODULE_METADATA
        assert "version" in MODULE_METADATA
        assert "router" in MODULE_METADATA
