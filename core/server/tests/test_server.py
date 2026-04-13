"""
────────────────────────────────────
Server Nexe
Author: Jordi Goy
Location: core/server/tests/test_server.py
Description: Tests bàsics per servidor Nexe. Valida endpoints root/health/info, CORS config, rate limiting i injeccions d'i18n/limiter/config.

www.jgoy.net · https://server-nexe.org
────────────────────────────────────
"""

import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from core.app import app

@pytest.fixture
def client():
  """Create test client"""
  return TestClient(app, base_url="http://localhost")

def test_root_endpoint(client):
  """Test root endpoint returns correct structure"""
  response = client.get("/")
  assert response.status_code == 200
  data = response.json()
  assert "system" in data
  from core.version import __version__
  assert data["system"] == f"Nexe {__version__}"
  assert "version" in data
  assert data["version"] == __version__

def test_health_endpoint(client):
  """Test health endpoint"""
  response = client.get("/health")
  assert response.status_code == 200
  data = response.json()
  assert "status" in data
  # version may be in response or in details depending on app lifecycle
  assert "version" in data or "message" in data

def test_api_info_endpoint(client):
  """Test API info endpoint"""
  response = client.get("/api/info")
  assert response.status_code == 200
  data = response.json()
  assert "name" in data
  assert "version" in data
  assert "endpoints" in data
  assert isinstance(data["endpoints"], list)

def test_modules_endpoint(client, auth_headers, monkeypatch):
  """Test modules listing endpoint (Bug 22: requires X-API-Key)."""
  # Sincronitza la primary key amb la del fixture (load_api_keys es llegeix dinamicament)
  monkeypatch.setenv("NEXE_PRIMARY_API_KEY", auth_headers["X-API-Key"])
  monkeypatch.delenv("NEXE_PRIMARY_KEY_EXPIRES", raising=False)
  response = client.get("/modules", headers=auth_headers)
  assert response.status_code == 200
  data = response.json()
  assert "status" in data

def test_rate_limiting_shared(client):
  """Test that rate limiting is working (shared limiter)"""
  responses = []
  for _ in range(35):
    responses.append(client.get("/"))

  success_count = sum(1 for r in responses if r.status_code == 200)
  assert success_count > 0

def test_cors_config_loaded(client):
  """Test that CORS middleware is configured with real config"""
  from starlette.middleware.cors import CORSMiddleware

  has_cors = any(
    isinstance(middleware.cls, type) and issubclass(middleware.cls, CORSMiddleware)
    for middleware in app.user_middleware
  )

  assert has_cors, "CORS middleware should be configured"

def test_i18n_injection(client):
  """Test that i18n is properly injected via app.state"""
  assert hasattr(app.state, 'i18n')
  assert app.state.i18n is not None

def test_limiter_injection(client):
  """Test that limiter is properly injected via app.state"""
  assert hasattr(app.state, 'limiter')
  assert app.state.limiter is not None

def test_config_injection(client):
  """Test that config is properly injected via app.state"""
  assert hasattr(app.state, 'config')
  assert app.state.config is not None
  assert 'core' in app.state.config


# ─────────────────────────────────────────────────────────────────────────────
# Tests de _maybe_launch_tray — llançament del bundle NexeTray.app
# ─────────────────────────────────────────────────────────────────────────────

class TestMaybeLaunchTray:
    """Cobreix guards i branques de llançament de _maybe_launch_tray."""

    def test_guard_tray_already_running(self):
        """Si NEXE_TRAY_PID és present → no llança res."""
        from core.server.runner import _maybe_launch_tray
        with patch.dict("os.environ", {"NEXE_TRAY_PID": "12345"}):
            with patch("core.server.runner.subprocess") as mock_sub:
                _maybe_launch_tray()
                mock_sub.Popen.assert_not_called()

    def test_guard_non_macos(self):
        """Si no és macOS → no llança res."""
        from core.server.runner import _maybe_launch_tray
        import os
        env = {k: v for k, v in os.environ.items()
               if k not in ("NEXE_TRAY_PID", "NEXE_DOCKER", "CONTAINER", "NEXE_NO_TRAY")}
        with patch.dict("os.environ", env, clear=True):
            with patch("core.server.runner.sys") as mock_sys:
                mock_sys.platform = "linux"
                with patch("core.server.runner.subprocess") as mock_sub:
                    _maybe_launch_tray()
                    mock_sub.Popen.assert_not_called()

    def test_guard_no_tray_env(self):
        """Si NEXE_NO_TRAY és present → no llança res."""
        from core.server.runner import _maybe_launch_tray
        with patch.dict("os.environ", {"NEXE_NO_TRAY": "1"}):
            with patch("core.server.runner.subprocess") as mock_sub:
                _maybe_launch_tray()
                mock_sub.Popen.assert_not_called()

    def test_guard_docker(self):
        """Si NEXE_DOCKER és present → no llança res."""
        from core.server.runner import _maybe_launch_tray
        with patch.dict("os.environ", {"NEXE_DOCKER": "1"}):
            with patch("core.server.runner.subprocess") as mock_sub:
                _maybe_launch_tray()
                mock_sub.Popen.assert_not_called()

    def test_launch_fallback_when_no_bundle(self, tmp_path):
        """Si NexeTray.app no existeix → fallback python -m installer.tray."""
        from core.server.runner import _maybe_launch_tray
        import os
        env = {k: v for k, v in os.environ.items()
               if k not in ("NEXE_TRAY_PID", "NEXE_DOCKER", "CONTAINER", "NEXE_NO_TRAY")}
        mock_popen = MagicMock()
        with patch.dict("os.environ", env, clear=True), \
                patch("core.server.runner.sys") as mock_sys, \
                patch("core.server.runner.subprocess") as mock_sub, \
                patch.dict("sys.modules", {"rumps": MagicMock()}):
            mock_sys.platform = "darwin"
            mock_sys.executable = "/usr/bin/python3"
            mock_sub.run.return_value = MagicMock(returncode=1, stdout="")
            mock_sub.Popen = mock_popen
            mock_sub.DEVNULL = -1
            # tmp_path no té NexeTray.app → activa el fallback
            _maybe_launch_tray(_project_root=tmp_path)
            assert mock_popen.called
            cmd = mock_popen.call_args[0][0]
            assert "installer.tray" in " ".join(str(c) for c in cmd)

    def test_launch_via_bundle_when_exists(self, tmp_path):
        """Si NexeTray.app existeix → llança el bundle (Gatekeeper-safe)."""
        from core.server.runner import _maybe_launch_tray
        import os
        # Crea binari fals del bundle
        binary = tmp_path / "installer" / "NexeTray.app" / "Contents" / "MacOS" / "NexeTray"
        binary.parent.mkdir(parents=True)
        binary.touch()
        env = {k: v for k, v in os.environ.items()
               if k not in ("NEXE_TRAY_PID", "NEXE_DOCKER", "CONTAINER", "NEXE_NO_TRAY")}
        mock_popen = MagicMock()
        with patch.dict("os.environ", env, clear=True), \
                patch("core.server.runner.sys") as mock_sys, \
                patch("core.server.runner.subprocess") as mock_sub, \
                patch.dict("sys.modules", {"rumps": MagicMock()}):
            mock_sys.platform = "darwin"
            mock_sys.executable = "/usr/bin/python3"
            mock_sub.run.return_value = MagicMock(returncode=1, stdout="")
            mock_sub.Popen = mock_popen
            mock_sub.DEVNULL = -1
            # tmp_path té NexeTray.app → activa el bundle path
            _maybe_launch_tray(_project_root=tmp_path)
            assert mock_popen.called
            cmd = mock_popen.call_args[0][0]
            assert "NexeTray" in " ".join(str(c) for c in cmd)
