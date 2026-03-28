"""
────────────────────────────────────
Server Nexe
Author: Jordi Goy
Location: plugins/security/tests/test_optional_api_key.py
Description: Tests per optional_api_key() amb clau primaria i secundaria.

www.jgoy.net · https://server-nexe.org
────────────────────────────────────
"""

import pytest
from fastapi import FastAPI, Depends
from fastapi.testclient import TestClient

from plugins.security.core.auth_dependencies import optional_api_key


@pytest.fixture
def app():
  app = FastAPI()

  @app.get("/optional")
  async def optional_endpoint(api_key=Depends(optional_api_key)):
    return {"api_key": api_key}

  return app


@pytest.fixture
def client(app):
  return TestClient(app)


def test_optional_api_key_accepts_primary(client, monkeypatch):
  monkeypatch.setenv("NEXE_PRIMARY_API_KEY", "primary-key")
  monkeypatch.delenv("NEXE_SECONDARY_API_KEY", raising=False)
  monkeypatch.delenv("NEXE_ADMIN_API_KEY", raising=False)

  response = client.get("/optional", headers={"X-API-Key": "primary-key"})

  assert response.status_code == 200
  assert response.json()["api_key"] == "primary-key"


def test_optional_api_key_accepts_secondary(client, monkeypatch):
  monkeypatch.delenv("NEXE_PRIMARY_API_KEY", raising=False)
  monkeypatch.delenv("NEXE_ADMIN_API_KEY", raising=False)
  monkeypatch.delenv("NEXE_DEV_MODE", raising=False)
  monkeypatch.setenv("NEXE_SECONDARY_API_KEY", "secondary-key")

  response = client.get("/optional", headers={"X-API-Key": "secondary-key"})

  assert response.status_code == 200
  assert response.json()["api_key"] == "secondary-key"


def test_optional_api_key_rejects_invalid(client, monkeypatch):
  monkeypatch.setenv("NEXE_PRIMARY_API_KEY", "primary-key")
  monkeypatch.delenv("NEXE_SECONDARY_API_KEY", raising=False)
  monkeypatch.delenv("NEXE_ADMIN_API_KEY", raising=False)

  response = client.get("/optional", headers={"X-API-Key": "wrong-key"})

  assert response.status_code == 200
  assert response.json()["api_key"] is None
