"""
────────────────────────────────────
Server Nexe
Version: 0.8
Author: Jordi Goy
Location: core/endpoints/tests/test_bootstrap_info.py
Description: Tests per /api/bootstrap/info (timezone + estat token).

www.jgoy.net · https://server-nexe.org
────────────────────────────────────
"""

from datetime import datetime, timezone

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from core.endpoints.bootstrap import router as bootstrap_router
import core.bootstrap_tokens as bootstrap_tokens


@pytest.fixture
def client():
  app = FastAPI()
  app.include_router(bootstrap_router)
  return TestClient(app)


def test_bootstrap_info_active_token(client, monkeypatch):
  now_ts = datetime.now(timezone.utc).timestamp()
  monkeypatch.setenv("NEXE_ENV", "development")
  monkeypatch.setattr(
    bootstrap_tokens,
    "get_bootstrap_token",
    lambda: {"token": "NEXE-TEST", "expires": now_ts + 600, "used": False},
  )

  response = client.get("/api/bootstrap/info")

  assert response.status_code == 200
  data = response.json()
  assert data["bootstrap_enabled"] is True
  assert data["token_active"] is True
  assert data["token_expires_in"] is not None
