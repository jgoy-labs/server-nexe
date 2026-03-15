"""
────────────────────────────────────
Server Nexe
Version: 0.8
Author: Jordi Goy
Location: memory/memory/api/tests/test_v1_endpoints.py
Description: Tests HTTP per memory/memory/api/v1.py (endpoints /memory).

www.jgoy.net
────────────────────────────────────
"""

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from unittest.mock import AsyncMock, MagicMock, patch

API_KEY = "test-memory-api-key"


def make_app():
    app = FastAPI()

    from slowapi import Limiter
    from slowapi.util import get_remote_address
    from slowapi.middleware import SlowAPIMiddleware
    from slowapi.errors import RateLimitExceeded
    from slowapi import _rate_limit_exceeded_handler

    limiter = Limiter(key_func=get_remote_address)
    app.state.limiter = limiter
    app.add_middleware(SlowAPIMiddleware)
    app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)

    from memory.memory.api.v1 import router
    app.include_router(router)
    return app


@pytest.fixture(autouse=True)
def set_api_key(monkeypatch):
    monkeypatch.setenv("NEXE_PRIMARY_API_KEY", API_KEY)
    # Reset global _memory_api between tests
    import memory.memory.api.v1 as v1_module
    v1_module._memory_api = None


def make_mock_memory():
    mem = AsyncMock()
    mem.collection_exists = AsyncMock(return_value=True)
    mem.create_collection = AsyncMock()
    mem.store = AsyncMock(return_value="doc-id-123")
    mem.search = AsyncMock(return_value=[])
    mem.list_collections = AsyncMock(return_value=["col1", "col2"])
    return mem


class TestGetMemoryApi:

    def test_initializes_on_first_use(self, monkeypatch):
        import memory.memory.api.v1 as v1_module
        v1_module._memory_api = None

        mock_mem = make_mock_memory()
        mock_mem.initialize = AsyncMock()

        import asyncio
        with patch("memory.memory.api.MemoryAPI", return_value=mock_mem):
            result = asyncio.run(v1_module.get_memory_api())

        assert result is mock_mem
        assert v1_module._memory_api is mock_mem

    def test_reuses_existing_instance(self, monkeypatch):
        import memory.memory.api.v1 as v1_module
        import asyncio

        existing = make_mock_memory()
        v1_module._memory_api = existing

        result = asyncio.run(v1_module.get_memory_api())

        assert result is existing  # Same instance


class TestMemoryStoreEndpoint:

    def test_store_success(self):
        client = TestClient(make_app())
        mock_mem = make_mock_memory()

        with patch("memory.memory.api.v1.get_memory_api", AsyncMock(return_value=mock_mem)):
            resp = client.post(
                "/memory/store",
                json={"content": "Test content", "collection": "nexe_chat_memory"},
                headers={"X-Api-Key": API_KEY}
            )

        assert resp.status_code == 200
        data = resp.json()
        assert data["success"] is True
        assert "document_id" in data

    def test_store_creates_collection_if_not_exists(self):
        client = TestClient(make_app())
        mock_mem = make_mock_memory()
        mock_mem.collection_exists = AsyncMock(return_value=False)

        with patch("memory.memory.api.v1.get_memory_api", AsyncMock(return_value=mock_mem)):
            resp = client.post(
                "/memory/store",
                json={"content": "Test", "collection": "new_collection"},
                headers={"X-Api-Key": API_KEY}
            )

        assert resp.status_code == 200
        mock_mem.create_collection.assert_called_once()

    def test_store_with_metadata(self):
        client = TestClient(make_app())
        mock_mem = make_mock_memory()

        with patch("memory.memory.api.v1.get_memory_api", AsyncMock(return_value=mock_mem)):
            resp = client.post(
                "/memory/store",
                json={
                    "content": "Content with meta",
                    "metadata": {"source": "cli", "user": "test"},
                    "collection": "nexe_chat_memory"
                },
                headers={"X-Api-Key": API_KEY}
            )

        assert resp.status_code == 200

    def test_store_error_returns_500(self):
        client = TestClient(make_app(), raise_server_exceptions=False)
        mock_mem = make_mock_memory()
        mock_mem.store = AsyncMock(side_effect=Exception("DB error"))

        with patch("memory.memory.api.v1.get_memory_api", AsyncMock(return_value=mock_mem)):
            resp = client.post(
                "/memory/store",
                json={"content": "Test"},
                headers={"X-Api-Key": API_KEY}
            )

        assert resp.status_code == 500

    def test_store_missing_api_key_returns_401(self):
        client = TestClient(make_app(), raise_server_exceptions=False)
        resp = client.post("/memory/store", json={"content": "Test"})
        assert resp.status_code == 401

    def test_store_default_collection(self):
        """Si no s'especifica collection, usa nexe_chat_memory."""
        client = TestClient(make_app())
        mock_mem = make_mock_memory()

        with patch("memory.memory.api.v1.get_memory_api", AsyncMock(return_value=mock_mem)):
            resp = client.post(
                "/memory/store",
                json={"content": "Test default collection"},
                headers={"X-Api-Key": API_KEY}
            )

        assert resp.status_code == 200
        # Check store was called with default collection
        call_kwargs = mock_mem.store.call_args[1]
        assert call_kwargs["collection"] == "nexe_chat_memory"

    def test_store_sets_default_source_metadata(self):
        """Metadata source = 'chat-cli' per defecte."""
        client = TestClient(make_app())
        mock_mem = make_mock_memory()

        with patch("memory.memory.api.v1.get_memory_api", AsyncMock(return_value=mock_mem)):
            resp = client.post(
                "/memory/store",
                json={"content": "Test", "metadata": {}},
                headers={"X-Api-Key": API_KEY}
            )

        assert resp.status_code == 200
        call_kwargs = mock_mem.store.call_args[1]
        assert call_kwargs["metadata"]["source"] == "chat-cli"


class TestMemorySearchEndpoint:

    def _make_result(self, text="Result text", score=0.85):
        r = MagicMock()
        r.text = text
        r.score = score
        r.metadata = {"source": "test.md"}
        return r

    def test_search_returns_results(self):
        client = TestClient(make_app())
        mock_mem = make_mock_memory()
        mock_mem.search = AsyncMock(return_value=[self._make_result()])

        with patch("memory.memory.api.v1.get_memory_api", AsyncMock(return_value=mock_mem)):
            resp = client.post(
                "/memory/search",
                json={"query": "test query", "collection": "nexe_chat_memory"},
                headers={"X-Api-Key": API_KEY}
            )

        assert resp.status_code == 200
        data = resp.json()
        assert data["total"] == 1
        assert data["results"][0]["content"] == "Result text"
        assert data["results"][0]["score"] == 0.85

    def test_search_collection_not_exists_returns_empty(self):
        client = TestClient(make_app())
        mock_mem = make_mock_memory()
        mock_mem.collection_exists = AsyncMock(return_value=False)

        with patch("memory.memory.api.v1.get_memory_api", AsyncMock(return_value=mock_mem)):
            resp = client.post(
                "/memory/search",
                json={"query": "test"},
                headers={"X-Api-Key": API_KEY}
            )

        assert resp.status_code == 200
        data = resp.json()
        assert data["total"] == 0
        assert data["results"] == []

    def test_search_error_returns_500(self):
        client = TestClient(make_app(), raise_server_exceptions=False)
        mock_mem = make_mock_memory()
        mock_mem.search = AsyncMock(side_effect=Exception("Search error"))

        with patch("memory.memory.api.v1.get_memory_api", AsyncMock(return_value=mock_mem)):
            resp = client.post(
                "/memory/search",
                json={"query": "test"},
                headers={"X-Api-Key": API_KEY}
            )

        assert resp.status_code == 500

    def test_search_missing_api_key(self):
        client = TestClient(make_app(), raise_server_exceptions=False)
        resp = client.post("/memory/search", json={"query": "test"})
        assert resp.status_code == 401

    def test_search_custom_limit(self):
        client = TestClient(make_app())
        mock_mem = make_mock_memory()
        mock_mem.search = AsyncMock(return_value=[])

        with patch("memory.memory.api.v1.get_memory_api", AsyncMock(return_value=mock_mem)):
            resp = client.post(
                "/memory/search",
                json={"query": "test", "limit": 10},
                headers={"X-Api-Key": API_KEY}
            )

        assert resp.status_code == 200
        call_kwargs = mock_mem.search.call_args[1]
        assert call_kwargs["top_k"] == 10

    def test_search_result_without_metadata(self):
        """Resultats sense metadata retornen dict buit."""
        client = TestClient(make_app())
        mock_mem = make_mock_memory()

        r = MagicMock()
        r.text = "Result"
        r.score = 0.7
        r.metadata = None

        mock_mem.search = AsyncMock(return_value=[r])

        with patch("memory.memory.api.v1.get_memory_api", AsyncMock(return_value=mock_mem)):
            resp = client.post(
                "/memory/search",
                json={"query": "test"},
                headers={"X-Api-Key": API_KEY}
            )

        assert resp.status_code == 200
        data = resp.json()
        assert data["results"][0]["metadata"] == {}


class TestMemoryHealthEndpoint:

    def test_health_healthy(self):
        client = TestClient(make_app())
        mock_mem = make_mock_memory()

        with patch("memory.memory.api.v1.get_memory_api", AsyncMock(return_value=mock_mem)):
            resp = client.get("/memory/health")

        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "healthy"
        assert data["collections"] == 2

    def test_health_unhealthy_on_error(self):
        client = TestClient(make_app(), raise_server_exceptions=False)

        with patch("memory.memory.api.v1.get_memory_api",
                   AsyncMock(side_effect=Exception("Qdrant not running"))):
            resp = client.get("/memory/health")

        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "unhealthy"
