"""
────────────────────────────────────
Server Nexe
Author: Jordi Goy
Location: tests/core/test_f24_pydantic_constraints.py
Description: Anti-DoS Pydantic constraints (max_length / ge / le).
             Verifies that oversized payloads are rejected at deserialization
             time (HTTP 422) before reaching the endpoint logic.
             Covers ChatCompletionRequest anti-DoS (max_length on messages) and MemoryStore/SearchRequest anti-DoS.
             store/search) from the F0 stoppers triage.

www.jgoy.net · https://server-nexe.org
────────────────────────────────────
"""

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from unittest.mock import AsyncMock, patch

API_KEY = "test-f24-pydantic-key"


# ─── Chat app builder ────────────────────────────────────────────────────────


def _build_chat_app():
    app = FastAPI()
    app.state.config = {}
    app.state.modules = {}

    from slowapi import Limiter, _rate_limit_exceeded_handler
    from slowapi.util import get_remote_address
    from slowapi.middleware import SlowAPIMiddleware
    from slowapi.errors import RateLimitExceeded

    limiter = Limiter(key_func=get_remote_address)
    app.state.limiter = limiter
    app.add_middleware(SlowAPIMiddleware)
    app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)

    from core.endpoints.v1 import router_v1
    app.include_router(router_v1)
    return app


# ─── Memory app builder ──────────────────────────────────────────────────────


def _build_memory_app():
    app = FastAPI()

    from slowapi import Limiter, _rate_limit_exceeded_handler
    from slowapi.util import get_remote_address
    from slowapi.middleware import SlowAPIMiddleware
    from slowapi.errors import RateLimitExceeded

    limiter = Limiter(key_func=get_remote_address)
    app.state.limiter = limiter
    app.add_middleware(SlowAPIMiddleware)
    app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)

    from memory.memory.api.v1 import router
    app.include_router(router)
    return app


# ─── Fixtures ────────────────────────────────────────────────────────────────


@pytest.fixture(autouse=True)
def _set_api_key(monkeypatch):
    monkeypatch.setenv("NEXE_PRIMARY_API_KEY", API_KEY)
    monkeypatch.delenv("NEXE_DEV_MODE", raising=False)
    # Reset memory global between tests so patches stick
    import memory.memory.api.v1 as v1_module
    v1_module._memory_api = None


@pytest.fixture
def chat_client():
    with TestClient(_build_chat_app()) as c:
        yield c


@pytest.fixture
def memory_client():
    with TestClient(_build_memory_app()) as c:
        yield c


_HEADERS = {"X-API-Key": API_KEY}


# ─── Chat anti-DoS ──────────────────────────────────────────────────────────


class TestChatPydanticConstraints:
    """ChatCompletionRequest anti-DoS."""

    def test_message_content_over_8000_chars_rejected(self, chat_client):
        """1 message with 8001 chars → 422 (Pydantic max_length on Message.content)."""
        payload = {
            "messages": [{"role": "user", "content": "A" * 8001}],
            "stream": False,
            "use_rag": False,
        }
        r = chat_client.post("/v1/chat/completions", json=payload, headers=_HEADERS)
        assert r.status_code == 422, f"Expected 422 (Pydantic), got {r.status_code}: {r.text}"

    def test_message_content_exactly_8000_chars_passes_validation(self, chat_client):
        """Exactly 8000 chars must pass Pydantic (boundary test). May fail later
        on engine availability, but not on validation."""
        payload = {
            "messages": [{"role": "user", "content": "A" * 8000}],
            "stream": False,
            "use_rag": False,
        }
        r = chat_client.post("/v1/chat/completions", json=payload, headers=_HEADERS)
        # Not 422: payload passed Pydantic. May be 400 (sanitizer), 404/503 (engine), etc.
        assert r.status_code != 422, f"Boundary 8000 chars must not 422: {r.text}"

    def test_more_than_100_messages_rejected(self, chat_client):
        """101 messages in conversation → 422 (Pydantic max_length on messages list)."""
        payload = {
            "messages": [{"role": "user", "content": "hi"}] * 101,
            "stream": False,
            "use_rag": False,
        }
        r = chat_client.post("/v1/chat/completions", json=payload, headers=_HEADERS)
        assert r.status_code == 422, f"Expected 422 for 101 messages, got {r.status_code}: {r.text}"


# ─── Memory anti-DoS ─────────────────────────────────────────────────────────


def _mock_memory():
    mem = AsyncMock()
    mem.collection_exists = AsyncMock(return_value=True)
    mem.create_collection = AsyncMock()
    mem.store = AsyncMock(return_value="doc-id-f24")
    mem.search = AsyncMock(return_value=[])
    return mem


class TestMemoryPydanticConstraints:
    """MemoryStoreRequest / MemorySearchRequest anti-DoS."""

    def test_store_content_over_100k_chars_rejected(self, memory_client):
        """100_001-char content → 422 (Pydantic max_length on content)."""
        payload = {
            "content": "B" * 100_001,
            "collection": "personal_memory",
        }
        r = memory_client.post("/memory/store", json=payload, headers=_HEADERS)
        assert r.status_code == 422, f"Expected 422 for huge content, got {r.status_code}: {r.text}"

    def test_store_content_exactly_100k_chars_passes_validation(self, memory_client):
        """Exactly 100_000 chars must pass Pydantic (boundary test)."""
        mock_mem = _mock_memory()
        payload = {
            "content": "B" * 100_000,
            "collection": "personal_memory",
        }
        with patch("memory.memory.api.v1.get_memory_api", AsyncMock(return_value=mock_mem)):
            r = memory_client.post("/memory/store", json=payload, headers=_HEADERS)
        # Not 422: payload passed Pydantic. With the mock, request should succeed (200).
        assert r.status_code != 422, f"Boundary 100_000 chars must not 422: {r.text}"

    def test_search_query_over_2000_chars_rejected(self, memory_client):
        """2001-char query → 422 (Pydantic max_length on query)."""
        payload = {"query": "Q" * 2001, "limit": 5}
        r = memory_client.post("/memory/search", json=payload, headers=_HEADERS)
        assert r.status_code == 422, f"Expected 422 for huge query, got {r.status_code}: {r.text}"

    def test_search_limit_above_100_rejected(self, memory_client):
        """limit=101 → 422 (Pydantic le=100 on limit)."""
        payload = {"query": "hola", "limit": 101}
        r = memory_client.post("/memory/search", json=payload, headers=_HEADERS)
        assert r.status_code == 422, f"Expected 422 for limit=101, got {r.status_code}: {r.text}"

    def test_search_limit_zero_rejected(self, memory_client):
        """limit=0 → 422 (Pydantic ge=1 on limit)."""
        payload = {"query": "hola", "limit": 0}
        r = memory_client.post("/memory/search", json=payload, headers=_HEADERS)
        assert r.status_code == 422, f"Expected 422 for limit=0, got {r.status_code}: {r.text}"


# ─── Installer (model-level test) ────────────────────────────────────────────
#
# The installer does NOT expose a Pydantic input model for API keys: the key
# is generated server-side via ``secrets.token_hex(32)`` which is fixed-length
# (64 hex chars) by construction. There is no untrusted input surface to
# constrain via Pydantic. The stopper (env file without model) was
# fixed independently by the existing ``model_config=None`` branch in
# ``generate_env_file``. No Pydantic schema applies — documented decision.
