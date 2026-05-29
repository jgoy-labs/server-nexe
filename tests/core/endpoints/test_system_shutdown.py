"""Tests for the graceful /admin/system/shutdown endpoint.

The Tauri host calls this endpoint from `graceful_quit` before falling back
to SIGKILL. The endpoint must:
  * return 200 immediately with a `shutdown_initiated` body,
  * schedule a delayed SIGINT to the current PID via BackgroundTasks,
  * require the API key dependency (covered by override here).
"""

import os
import signal
from unittest.mock import patch

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from core.endpoints.system import router_admin
from plugins.security.core.auth import require_api_key


def _make_app() -> FastAPI:
  """Minimal FastAPI app exposing the admin router with auth bypassed."""
  app = FastAPI()
  app.state.config = {}
  app.state.modules = {}
  app.dependency_overrides[require_api_key] = lambda: "test-key"
  app.include_router(router_admin)
  return app


def test_shutdown_endpoint_returns_initiated():
  app = _make_app()
  client = TestClient(app)

  with patch("core.endpoints.system.os.kill") as mock_kill:
    response = client.post("/admin/system/shutdown")

  assert response.status_code == 200
  body = response.json()
  assert body["status"] == "shutdown_initiated"
  assert body["expected_downtime_seconds"] == 1
  assert "shutting down" in body["message"].lower()

  # TestClient awaits background tasks before returning, so the SIGINT
  # delivery must have run by now.
  mock_kill.assert_called_once()
  pid_arg, sig_arg = mock_kill.call_args.args
  assert pid_arg == os.getpid()
  assert sig_arg == signal.SIGINT


def test_shutdown_endpoint_swallows_kill_failure():
  """If os.kill raises, the endpoint must still have returned 200 first."""
  app = _make_app()
  client = TestClient(app)

  with patch(
    "core.endpoints.system.os.kill",
    side_effect=PermissionError("not allowed in CI sandbox"),
  ):
    response = client.post("/admin/system/shutdown")

  # The HTTP 200 is what the Tauri host relies on; the actual signal failure
  # is logged but must not break the response.
  assert response.status_code == 200
  assert response.json()["status"] == "shutdown_initiated"


def test_shutdown_endpoint_requires_authentication():
  """Without the dependency override, the endpoint must reject anonymous calls."""
  app = FastAPI()
  app.state.config = {}
  app.state.modules = {}
  app.include_router(router_admin)  # no override → require_api_key active
  client = TestClient(app)

  response = client.post("/admin/system/shutdown")
  # Bare request misses the X-API-Key header → 4xx, never 200.
  assert response.status_code in (401, 403, 422), (
    f"shutdown endpoint must enforce auth, got {response.status_code}"
  )


def test_admin_paths_csrf_exempt():
  """/admin/* must be in the CSRF exempt list.

  The Tauri Rust client calls /admin/system/shutdown with an X-API-Key header
  but without a CSRF token or cookie. Previously the request hit starlette-csrf
  first and returned 403 Forbidden, so lifecycle.rs always fell back to SIGKILL.
  This test pins the exempt pattern so a future cleanup doesn't accidentally
  remove it.
  """
  from core.middleware import _CSRF_EXEMPT_PATTERNS

  matched = [p for p in _CSRF_EXEMPT_PATTERNS if p.match("/admin/system/shutdown")]
  assert matched, (
    "F5.6 BUG-NEW-1 regression: /admin/system/shutdown must be CSRF-exempt "
    "(authenticated by X-API-Key, called from cookie-less Rust client)."
  )
