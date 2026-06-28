"""
MC-073 / MC-074 — els endpoints del mòdul Ollama no han de filtrar `str(e)`
(detalls interns) al cos de la resposta, i `get_model_info`/`delete_model` han
de distingir l'status correcte (404 model no trobat, 503 infra, 5xx intern).

El client legítim rep un missatge genèric; `str(e)` només va al log.
"""
from __future__ import annotations

from unittest.mock import AsyncMock
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from plugins.ollama_module.api.routes import create_router
from plugins.ollama_module.core.errors import ModelNotFoundError, OllamaSemanticError
from plugins.security.core.auth import require_api_key

# Marker that a `str(e)` would leak into the body but that must NEVER appear.
LEAK = "LEAK_/Users/secret/internal_path_4242"


def _client(module) -> TestClient:
    app = FastAPI()
    app.include_router(create_router(module))
    app.dependency_overrides[require_api_key] = lambda: "test-key"
    return TestClient(app, raise_server_exceptions=False)


def _module():
    m = AsyncMock()
    return m


class TestListModels:
    def test_error_does_not_leak_str_e(self):
        m = _module()
        m.list_models = AsyncMock(side_effect=Exception(LEAK))
        r = _client(m).get("/ollama/api/models", headers={"X-API-Key": "k"})
        assert r.status_code == 503
        assert LEAK not in r.text


class TestGetModelInfo:
    def test_model_not_found_is_404_no_leak(self):
        m = _module()
        m.get_model_info = AsyncMock(side_effect=ModelNotFoundError("modelx"))
        r = _client(m).get("/ollama/api/models/modelx/info", headers={"X-API-Key": "k"})
        assert r.status_code == 404
        assert LEAK not in r.text

    def test_semantic_error_keeps_status_no_leak(self):
        m = _module()
        m.get_model_info = AsyncMock(side_effect=OllamaSemanticError(LEAK, 422))
        r = _client(m).get("/ollama/api/models/x/info", headers={"X-API-Key": "k"})
        assert r.status_code == 422
        assert LEAK not in r.text

    def test_internal_error_no_leak(self):
        m = _module()
        m.get_model_info = AsyncMock(side_effect=Exception(LEAK))
        r = _client(m).get("/ollama/api/models/x/info", headers={"X-API-Key": "k"})
        assert r.status_code == 500
        assert LEAK not in r.text


class TestDeleteModel:
    def test_internal_error_no_leak(self):
        m = _module()
        m.delete_model = AsyncMock(side_effect=Exception(LEAK))
        r = _client(m).delete("/ollama/api/models/x", headers={"X-API-Key": "k"})
        assert r.status_code == 500
        assert LEAK not in r.text

    def test_model_not_found_is_404_no_leak(self):
        m = _module()
        m.delete_model = AsyncMock(side_effect=ModelNotFoundError("modelx"))
        r = _client(m).delete("/ollama/api/models/modelx", headers={"X-API-Key": "k"})
        assert r.status_code == 404
        assert LEAK not in r.text


class TestPullModelSSE:
    def test_stream_error_does_not_leak(self):
        m = _module()

        async def _boom(name):
            raise Exception(LEAK)
            yield  # pragma: no cover — fa que sigui async generator

        m.pull_model = _boom
        r = _client(m).post(
            "/ollama/api/pull", json={"name": "qwen3:8b"}, headers={"X-API-Key": "k"}
        )
        assert r.status_code == 200  # SSE: l'stream sempre arrenca 200
        assert LEAK not in r.text
        assert "error" in r.text  # s'informa de l'error, però genèric
