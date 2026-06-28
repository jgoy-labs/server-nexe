"""
────────────────────────────────────
Server Nexe
Author: Jordi Goy
Location: memory/memory/api/tests/test_v1_endpoints.py
Description: HTTP tests for memory/memory/api/v1.py (endpoints /memory).

www.jgoy.net · https://server-nexe.org
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
                json={"content": "Test content", "collection": "personal_memory"},
                headers={"X-Api-Key": API_KEY}
            )

        assert resp.status_code == 200
        data = resp.json()
        assert data["success"] is True
        assert "document_id" in data

    def test_store_accepts_legacy_text_alias(self):
        """B066: docs historically taught {"text": ...}; the endpoint must still
        accept it (AliasChoices back-compat) so old curl recipes don't 422.

        The value sent via ``text`` must land in ``body.content`` and be passed
        to the memory store unchanged.
        """
        client = TestClient(make_app())
        mock_mem = make_mock_memory()

        with patch("memory.memory.api.v1.get_memory_api", AsyncMock(return_value=mock_mem)):
            resp = client.post(
                "/memory/store",
                json={"text": "Legacy alias payload", "collection": "personal_memory"},
                headers={"X-Api-Key": API_KEY}
            )

        assert resp.status_code == 200, resp.text
        data = resp.json()
        assert data["success"] is True
        # The aliased value must reach the store as the document text.
        call_kwargs = mock_mem.store.call_args[1]
        assert call_kwargs["text"] == "Legacy alias payload"

    def test_store_legacy_text_alias_not_exposed_in_openapi(self):
        """B066: the ``text`` alias is invisible back-compat — the OpenAPI schema
        must keep advertising the canonical ``content`` field only.
        """
        app = make_app()
        schema = app.openapi()
        model = schema["components"]["schemas"]["MemoryStoreRequest"]
        props = model["properties"]
        assert "content" in props
        assert "text" not in props

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
                    "collection": "personal_memory"
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

    def test_search_query_not_logged(self, caplog):
        # MC-113: the user search query is sensitive free text. It must not be
        # written to the server logs (which persist to disk next to encrypted
        # stores → RT-05). The debug log keeps only result/collection counts.
        import logging
        SENTINEL = "PII_what_is_my_bank_password"
        client = TestClient(make_app())
        mock_mem = make_mock_memory()  # search returns [] — log still fires

        with patch("memory.memory.api.v1.get_memory_api", AsyncMock(return_value=mock_mem)):
            with caplog.at_level(logging.DEBUG, logger="memory.memory.api.v1"):
                resp = client.post(
                    "/memory/search",
                    json={"query": SENTINEL, "limit": 5},
                    headers={"X-Api-Key": API_KEY},
                )

        assert resp.status_code == 200
        assert SENTINEL not in caplog.text
        assert "Memory search returned" in caplog.text  # counts still logged

    def test_store_default_collection(self):
        """If no collection is specified, uses personal_memory."""
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
        assert call_kwargs["collection"] == "personal_memory"

    def test_store_sets_default_source_metadata(self):
        """Metadata source = 'chat-cli' by default."""
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
                json={"query": "test query", "collection": "personal_memory"},
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
        """Results without metadata return empty dict."""
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
        assert data["results"][0]["metadata"]["source_collection"] == "nexe_documentation"

    def test_search_partial_degradation_is_flagged(self):
        """MC-125: when some collections fail but others succeed, the response
        must surface the degradation (partial=True + failed_collections) instead
        of returning a silent 200 that looks like a complete result.

        Mutation guard: revert memory_search to swallow per-collection errors
        without setting `partial`/`failed_collections` and this goes RED.
        """
        client = TestClient(make_app())
        mock_mem = make_mock_memory()
        mock_mem.collection_exists = AsyncMock(return_value=True)

        async def _search(query, collection, top_k, threshold):
            if collection == "user_knowledge":
                raise Exception("qdrant timeout on user_knowledge")
            return [self._make_result(text=f"hit from {collection}")]

        mock_mem.search = AsyncMock(side_effect=_search)

        with patch("memory.memory.api.v1.get_memory_api", AsyncMock(return_value=mock_mem)):
            # no `collection` → default fan-out over the 3 default collections
            resp = client.post(
                "/memory/search",
                json={"query": "test"},
                headers={"X-Api-Key": API_KEY},
            )

        assert resp.status_code == 200
        data = resp.json()
        assert data["partial"] is True, "partial degradation must be flagged (MC-125)"
        assert "user_knowledge" in data["failed_collections"]
        # the two surviving collections still contributed results
        assert data["total"] >= 1

    def test_search_all_ok_is_not_partial(self):
        """Sanity counterpart: when every collection succeeds, partial is False
        and failed_collections is empty (guards against partial=True false positives)."""
        client = TestClient(make_app())
        mock_mem = make_mock_memory()
        mock_mem.collection_exists = AsyncMock(return_value=True)
        mock_mem.search = AsyncMock(return_value=[self._make_result()])

        with patch("memory.memory.api.v1.get_memory_api", AsyncMock(return_value=mock_mem)):
            resp = client.post(
                "/memory/search",
                json={"query": "test"},
                headers={"X-Api-Key": API_KEY},
            )

        assert resp.status_code == 200
        data = resp.json()
        assert data["partial"] is False
        assert data["failed_collections"] == []


class TestMemorySearchRateLimit:
    """R6-08 v1.0.4: /v1/memory/search must carry @limiter.limit("60/minute").

    Without it, the endpoint can be abused for local DoS — an attacker who
    holds an API key can fire unbounded vector queries (each search hits the
    embedder + Qdrant). 60/min matches the chat-rate-limit family and is well
    above any honest interactive usage.

    The guard is static (source inspection) because the slowapi limiter in
    make_app() above is a fresh instance per test — it does not know about
    decorators bound to the global limiter from core.dependencies. A static
    grep is the most robust shape here: if a future maintainer removes the
    decorator, this test breaks loudly.
    """

    def test_search_endpoint_has_rate_limit_decorator(self):
        import inspect
        import memory.memory.api.v1 as v1_module
        src = inspect.getsource(v1_module)
        # Must precede the function definition (any whitespace tolerated).
        assert '@limiter.limit("60/minute")' in src, (
            "memory/memory/api/v1.py is missing @limiter.limit on memory_search. "
            "R6-08 requires rate limit on /v1/memory/search."
        )
        # And it must be on memory_search specifically, not some other handler.
        # Find the memory_search def and check the line above it carries the limit.
        lines = src.splitlines()
        for i, line in enumerate(lines):
            if line.startswith("async def memory_search"):
                # Walk upward over decorators until we hit the @router or non-decorator line.
                window = "\n".join(lines[max(0, i - 5): i])
                assert '@limiter.limit("60/minute")' in window, (
                    f"@limiter.limit decorator not adjacent to memory_search. "
                    f"Decorators above:\n{window}"
                )
                return
        pytest.fail("memory_search function not found in module source")

    def test_limiter_imported_from_core_dependencies(self):
        """Sanity: the limiter symbol is the project-wide one, not a local stub."""
        import memory.memory.api.v1 as v1_module
        from core.dependencies import limiter as core_limiter
        assert v1_module.limiter is core_limiter


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
