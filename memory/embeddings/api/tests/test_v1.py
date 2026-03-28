"""
Tests per memory/embeddings/api/v1.py
Covers uncovered lines: 24, 39 (HTTPException raises for 501 endpoints).
"""

import os
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from memory.embeddings.api.v1 import router

API_KEY = "test-embeddings-key"


@pytest.fixture(autouse=True)
def set_api_key(monkeypatch):
    monkeypatch.setenv("NEXE_PRIMARY_API_KEY", API_KEY)


@pytest.fixture
def client():
    app = FastAPI()
    app.include_router(router, prefix="/v1")
    return TestClient(app)


class TestEncodeEndpoint:
    def test_encode_returns_501(self, client):
        """Line 24: POST /encode raises 501 Not Implemented."""
        resp = client.post("/v1/embeddings/encode", headers={"X-Api-Key": API_KEY})
        assert resp.status_code == 501
        data = resp.json()
        assert data["detail"]["error"] == "Not Implemented"

    def test_encode_no_auth_returns_401(self, client):
        """Endpoints require API key."""
        resp = client.post("/v1/embeddings/encode")
        assert resp.status_code == 401


class TestListModelsEndpoint:
    def test_models_returns_501(self, client):
        """Line 39: GET /models raises 501 Not Implemented."""
        resp = client.get("/v1/embeddings/models", headers={"X-Api-Key": API_KEY})
        assert resp.status_code == 501
        data = resp.json()
        assert data["detail"]["error"] == "Not Implemented"

    def test_models_no_auth_returns_401(self, client):
        """Endpoints require API key."""
        resp = client.get("/v1/embeddings/models")
        assert resp.status_code == 401
