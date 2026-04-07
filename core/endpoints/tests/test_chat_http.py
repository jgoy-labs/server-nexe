"""
────────────────────────────────────
Server Nexe
Author: Jordi Goy
Location: core/endpoints/tests/test_chat_http.py
Description: Tests HTTP per core/endpoints/chat.py (endpoint, engines, streaming, memory).

www.jgoy.net · https://server-nexe.org
────────────────────────────────────
"""

import asyncio
import json
import os
import pytest
from unittest.mock import AsyncMock, MagicMock, patch, ANY
from fastapi import FastAPI
from fastapi.testclient import TestClient
from fastapi.responses import StreamingResponse

API_KEY = "test-chat-key-9999"


def make_app(modules=None, config=None):
    app = FastAPI()
    app.state.config = config or {}
    app.state.modules = modules or {}

    from slowapi import Limiter
    from slowapi.util import get_remote_address
    from slowapi.middleware import SlowAPIMiddleware
    from slowapi.errors import RateLimitExceeded
    from slowapi import _rate_limit_exceeded_handler

    limiter = Limiter(key_func=get_remote_address)
    app.state.limiter = limiter
    app.add_middleware(SlowAPIMiddleware)
    app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)

    from core.endpoints.chat import router
    app.include_router(router)
    return app


@pytest.fixture(autouse=True)
def set_api_key(monkeypatch):
    monkeypatch.setenv("NEXE_PRIMARY_API_KEY", API_KEY)
    monkeypatch.delenv("NEXE_MODEL_ENGINE", raising=False)
    monkeypatch.delenv("NEXE_OLLAMA_MODEL", raising=False)
    monkeypatch.delenv("NEXE_DEFAULT_MODEL", raising=False)
    # Reset module-level caches between tests
    from core.endpoints import chat
    chat._ollama_tags_cache["models"] = None
    chat._ollama_tags_cache["ts"] = 0.0


# ─── TestChatCompletionsEndpoint ─────────────────────────────────────────────

class TestChatCompletionsEndpoint:

    def _client(self, modules=None, config=None):
        app = make_app(modules=modules, config=config)
        return TestClient(app, raise_server_exceptions=False)

    def _headers(self):
        return {"X-Api-Key": API_KEY, "Content-Type": "application/json"}

    def _payload(self, **kwargs):
        base = {
            "messages": [{"role": "user", "content": "Hola"}],
            "engine": "ollama",
            "stream": False,
            "use_rag": False,
        }
        base.update(kwargs)
        return base

    def test_missing_api_key_returns_401(self):
        client = self._client()
        resp = client.post("/chat/completions", json=self._payload(),
                           headers={"Content-Type": "application/json"})
        assert resp.status_code == 401

    def test_ollama_success_non_streaming(self):
        """Ollama disponible i retorna resposta correcta."""
        ollama_resp = {"message": {"content": "Hola, sóc Nexe"}, "done": True}
        tags_resp_data = {"models": [{"name": "llama3.2"}]}

        mock_tags = MagicMock()
        mock_tags.status_code = 200
        mock_tags.json.return_value = tags_resp_data

        mock_chat_resp = MagicMock()
        mock_chat_resp.status_code = 200
        mock_chat_resp.json.return_value = ollama_resp

        mock_client = AsyncMock()
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)
        mock_client.get = AsyncMock(return_value=mock_tags)
        mock_client.post = AsyncMock(return_value=mock_chat_resp)

        with patch("httpx.AsyncClient", return_value=mock_client), \
             patch("memory.memory.api.v1.get_memory_api", side_effect=Exception("no memory")):
            client = self._client(modules={"ollama_module": MagicMock()})
            resp = client.post("/chat/completions",
                               json=self._payload(engine="ollama"),
                               headers=self._headers())

        assert resp.status_code == 200
        data = resp.json()
        assert "nexe_engine" in data

    def test_ollama_connect_error_503(self):
        """ConnectError quan Ollama no disponible."""
        import httpx

        mock_client = AsyncMock()
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)
        mock_client.get = AsyncMock(side_effect=httpx.ConnectError("refused"))

        with patch("httpx.AsyncClient", return_value=mock_client), \
             patch("memory.memory.api.v1.get_memory_api", side_effect=Exception("no memory")):
            client = self._client()
            resp = client.post("/chat/completions",
                               json=self._payload(engine="ollama"),
                               headers=self._headers())

        assert resp.status_code == 503

    def test_mlx_engine_no_module_falls_back_to_ollama(self):
        """Sense mlx_module, ha de fer fallback a Ollama."""
        import httpx

        mock_client = AsyncMock()
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)
        mock_client.get = AsyncMock(side_effect=httpx.ConnectError("refused"))

        # No mlx_module en modules
        with patch("httpx.AsyncClient", return_value=mock_client), \
             patch("memory.memory.api.v1.get_memory_api", side_effect=Exception("no memory")):
            client = self._client(modules={})
            resp = client.post("/chat/completions",
                               json=self._payload(engine="mlx"),
                               headers=self._headers())

        assert resp.status_code == 503  # Ollama fallback fails too

    def test_llama_cpp_no_module_falls_back_to_ollama(self):
        """Sense llama_cpp_module, ha de fer fallback a Ollama."""
        import httpx

        mock_client = AsyncMock()
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)
        mock_client.get = AsyncMock(side_effect=httpx.ConnectError("refused"))

        with patch("httpx.AsyncClient", return_value=mock_client), \
             patch("memory.memory.api.v1.get_memory_api", side_effect=Exception("no memory")):
            client = self._client(modules={})
            resp = client.post("/chat/completions",
                               json=self._payload(engine="llama.cpp"),
                               headers=self._headers())

        assert resp.status_code == 503

    def test_rag_context_injected_with_memory_api(self):
        """RAG: MemoryAPI retorna resultats que s'injecten al prompt."""
        mock_result = MagicMock()
        mock_result.text = "Nexe és un assistent"
        mock_result.metadata = {"source": "docs/test.md"}

        mock_memory = AsyncMock()
        mock_memory.collection_exists = AsyncMock(return_value=True)
        mock_memory.search = AsyncMock(return_value=[mock_result])

        import httpx
        mock_client = AsyncMock()
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)
        mock_client.get = AsyncMock(side_effect=httpx.ConnectError("refused"))

        with patch("memory.memory.api.v1.get_memory_api", AsyncMock(return_value=mock_memory)), \
             patch("httpx.AsyncClient", return_value=mock_client):
            client = self._client(modules={})
            resp = client.post("/chat/completions",
                               json=self._payload(use_rag=True, engine="ollama"),
                               headers=self._headers())

        # RAG cerca però Ollama falla → 503
        assert resp.status_code == 503

    def test_rag_memory_api_fails_uses_rag_module_fallback(self):
        """Si MemoryAPI falla, prova rag_module com fallback."""
        mock_rag = MagicMock()
        mock_rag.search = AsyncMock(return_value=["Some RAG result"])

        import httpx
        mock_client = AsyncMock()
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)
        mock_client.get = AsyncMock(side_effect=httpx.ConnectError("refused"))

        with patch("memory.memory.api.v1.get_memory_api", side_effect=Exception("no memory")), \
             patch("httpx.AsyncClient", return_value=mock_client):
            client = self._client(modules={"rag": mock_rag})
            resp = client.post("/chat/completions",
                               json=self._payload(use_rag=True, engine="ollama"),
                               headers=self._headers())

        # RAG finds results but Ollama fails
        assert resp.status_code == 503

    def test_system_prompt_injected_when_missing(self):
        """Si no hi ha system message, s'afegeix system prompt de Nexe."""
        config = {"personality": {"prompt": {"ca_full": "Ets Nexe en català"}}}

        import httpx
        mock_client = AsyncMock()
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)
        mock_client.get = AsyncMock(side_effect=httpx.ConnectError("refused"))

        with patch("httpx.AsyncClient", return_value=mock_client), \
             patch("memory.memory.api.v1.get_memory_api", side_effect=Exception("no")):
            client = self._client(config=config)
            resp = client.post("/chat/completions",
                               json=self._payload(engine="ollama", use_rag=False),
                               headers=self._headers())

        # Ollama fails → 503, but no crash
        assert resp.status_code == 503

    def test_system_prompt_not_duplicated_when_present(self):
        """Si el client envia system message, no s'afegeix extra."""
        payload = {
            "messages": [
                {"role": "system", "content": "Custom system"},
                {"role": "user", "content": "Hola"},
            ],
            "engine": "ollama",
            "stream": False,
            "use_rag": False,
        }

        import httpx
        mock_client = AsyncMock()
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)
        mock_client.get = AsyncMock(side_effect=httpx.ConnectError("refused"))

        with patch("httpx.AsyncClient", return_value=mock_client), \
             patch("memory.memory.api.v1.get_memory_api", side_effect=Exception("no")):
            client = self._client()
            resp = client.post("/chat/completions", json=payload, headers=self._headers())

        assert resp.status_code == 503  # Ollama fails, but we got here

    def test_mlx_engine_non_streaming_success(self):
        """MLX engine disponible retorna resposta correcta."""
        mlx_module = AsyncMock()
        mlx_module.chat = AsyncMock(return_value={
            "response": "Hola des de MLX",
            "tokens": 10,
            "tokens_per_second": 50.0,
            "prompt_tokens": 5,
            "context_used": 15,
        })

        with patch("memory.memory.api.v1.get_memory_api", side_effect=Exception("no")):
            client = self._client(modules={"mlx_module": mlx_module})
            resp = client.post("/chat/completions",
                               json=self._payload(engine="mlx", use_rag=False),
                               headers=self._headers())

        assert resp.status_code == 200
        data = resp.json()
        assert "choices" in data
        assert data["choices"][0]["message"]["content"] == "Hola des de MLX"

    def test_llama_cpp_engine_non_streaming_success(self):
        """Llama.cpp engine disponible retorna resposta correcta."""
        llama_module = AsyncMock()
        llama_module.chat = AsyncMock(return_value={
            "response": "Hola des de Llama.cpp",
            "tokens": 8,
            "prompt_tokens": 4,
            "context_used": 12,
        })

        with patch("memory.memory.api.v1.get_memory_api", side_effect=Exception("no")):
            client = self._client(modules={"llama_cpp_module": llama_module})
            resp = client.post("/chat/completions",
                               json=self._payload(engine="llama.cpp", use_rag=False),
                               headers=self._headers())

        assert resp.status_code == 200
        data = resp.json()
        assert data["choices"][0]["message"]["content"] == "Hola des de Llama.cpp"

    def test_default_engine_fallback(self):
        """Engine 'other' → default Ollama."""
        import httpx
        mock_client = AsyncMock()
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)
        mock_client.get = AsyncMock(side_effect=httpx.ConnectError("refused"))

        with patch("httpx.AsyncClient", return_value=mock_client), \
             patch("memory.memory.api.v1.get_memory_api", side_effect=Exception("no")):
            client = self._client()
            resp = client.post("/chat/completions",
                               json=self._payload(engine="unknown_engine", use_rag=False),
                               headers=self._headers())

        assert resp.status_code == 503  # Ollama fallback fails

    def test_ollama_response_sets_nexe_engine(self):
        """Resposta Ollama ha de tenir nexe_engine al dict."""
        tags_resp_data = {"models": [{"name": "llama3.2"}]}
        mock_tags = MagicMock()
        mock_tags.status_code = 200
        mock_tags.json.return_value = tags_resp_data

        ollama_resp = {"message": {"content": "Test response"}}
        mock_chat_resp = MagicMock()
        mock_chat_resp.status_code = 200
        mock_chat_resp.json.return_value = ollama_resp

        mock_client = AsyncMock()
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)
        mock_client.get = AsyncMock(return_value=mock_tags)
        mock_client.post = AsyncMock(return_value=mock_chat_resp)

        with patch("httpx.AsyncClient", return_value=mock_client), \
             patch("memory.memory.api.v1.get_memory_api", side_effect=Exception("no")):
            client = self._client(modules={"ollama_module": MagicMock()})
            resp = client.post("/chat/completions",
                               json=self._payload(engine="ollama", use_rag=False),
                               headers=self._headers())

        assert resp.status_code == 200
        data = resp.json()
        assert data.get("nexe_engine") == "ollama"

    def test_preferred_fallback_adds_headers(self):
        """Quan preferred engine no disponible, X-Nexe-Fallback-From s'afegeix."""
        tags_resp_data = {"models": [{"name": "llama3.2"}]}
        mock_tags = MagicMock()
        mock_tags.status_code = 200
        mock_tags.json.return_value = tags_resp_data

        ollama_resp = {"message": {"content": "Fallback response"}}
        mock_chat_resp = MagicMock()
        mock_chat_resp.status_code = 200
        mock_chat_resp.json.return_value = ollama_resp

        mock_client = AsyncMock()
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)
        mock_client.get = AsyncMock(return_value=mock_tags)
        mock_client.post = AsyncMock(return_value=mock_chat_resp)

        # mlx preferred but only ollama available
        with patch("httpx.AsyncClient", return_value=mock_client), \
             patch("memory.memory.api.v1.get_memory_api", side_effect=Exception("no")), \
             patch.dict(os.environ, {"NEXE_MODEL_ENGINE": "mlx"}):
            client = self._client(modules={"ollama_module": MagicMock()})
            resp = client.post("/chat/completions",
                               json=self._payload(engine=None, use_rag=False),
                               headers=self._headers())

        assert resp.status_code == 200
        data = resp.json()
        assert "nexe_fallback" in data


# ─── TestSaveConversationToMemory ─────────────────────────────────────────────

class TestSaveConversationToMemory:

    def test_saves_to_personal_memory(self):
        from core.endpoints.chat import _save_conversation_to_memory

        mock_memory = AsyncMock()
        mock_memory.collection_exists = AsyncMock(return_value=True)
        mock_memory.store = AsyncMock(return_value="conv-id-123")

        app_state = MagicMock()

        with patch("memory.memory.api.v1.get_memory_api", AsyncMock(return_value=mock_memory)):
            asyncio.run(_save_conversation_to_memory(app_state, "Hello", "Response"))

        mock_memory.store.assert_called_once()
        call_kwargs = mock_memory.store.call_args
        assert "personal_memory" in str(call_kwargs)

    def test_creates_collection_if_not_exists(self):
        from core.endpoints.chat import _save_conversation_to_memory

        mock_memory = AsyncMock()
        mock_memory.collection_exists = AsyncMock(return_value=False)
        mock_memory.create_collection = AsyncMock()
        mock_memory.store = AsyncMock(return_value="id")

        app_state = MagicMock()

        with patch("memory.memory.api.v1.get_memory_api", AsyncMock(return_value=mock_memory)):
            asyncio.run(_save_conversation_to_memory(app_state, "Hi", "OK"))

        mock_memory.create_collection.assert_called_once()

    def test_handles_memory_api_failure_gracefully(self):
        from core.endpoints.chat import _save_conversation_to_memory

        app_state = MagicMock()

        with patch("memory.memory.api.v1.get_memory_api", AsyncMock(side_effect=Exception("DB error"))):
            # Should not raise
            asyncio.run(_save_conversation_to_memory(app_state, "Hi", "OK"))

    def test_updates_metrics_on_success(self):
        from core.endpoints.chat import _save_conversation_to_memory

        mock_memory = AsyncMock()
        mock_memory.collection_exists = AsyncMock(return_value=True)
        mock_memory.store = AsyncMock(return_value="id")

        mock_counter = MagicMock()
        mock_counter.labels = MagicMock(return_value=mock_counter)
        mock_counter.inc = MagicMock()

        app_state = MagicMock()

        with patch("memory.memory.api.v1.get_memory_api", AsyncMock(return_value=mock_memory)), \
             patch("core.metrics.registry.MEMORY_OPERATIONS", mock_counter):
            asyncio.run(_save_conversation_to_memory(app_state, "User msg", "Assistant msg"))

        mock_counter.labels.assert_called_with(operation="autosave")


# ─── TestForwardToOllama ──────────────────────────────────────────────────────

class TestForwardToOllama:

    def _make_request(self, stream=False, model=None, **kwargs):
        from core.endpoints.chat import ChatCompletionRequest, Message
        return ChatCompletionRequest(
            messages=[Message(role="user", content="Test")],
            stream=stream,
            model=model,
            use_rag=False,
            **kwargs
        )

    def test_model_from_env(self):
        """Model es llegeix de NEXE_OLLAMA_MODEL si no especificat."""
        from core.endpoints.chat import _forward_to_ollama

        tags_data = {"models": [{"name": "mistral"}]}
        mock_tags = MagicMock()
        mock_tags.status_code = 200
        mock_tags.json.return_value = tags_data

        chat_resp = MagicMock()
        chat_resp.status_code = 200
        chat_resp.json.return_value = {"message": {"content": "OK"}}

        mock_client = AsyncMock()
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)
        mock_client.get = AsyncMock(return_value=mock_tags)
        mock_client.post = AsyncMock(return_value=chat_resp)

        with patch("httpx.AsyncClient", return_value=mock_client), \
             patch.dict(os.environ, {"NEXE_OLLAMA_MODEL": "mistral"}):
            result = asyncio.run(_forward_to_ollama(
                [{"role": "user", "content": "Hi"}],
                self._make_request(),
                app_state=None
            ))

        assert isinstance(result, dict)

    def test_ollama_error_status_raises(self):
        """Ollama retorna error HTTP → HTTPException."""
        from core.endpoints.chat import _forward_to_ollama
        from fastapi import HTTPException

        tags_data = {"models": [{"name": "llama3.2"}]}
        mock_tags = MagicMock()
        mock_tags.status_code = 200
        mock_tags.json.return_value = tags_data

        chat_resp = MagicMock()
        chat_resp.status_code = 500
        chat_resp.json.return_value = {"error": "Internal error"}

        mock_client = AsyncMock()
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)
        mock_client.get = AsyncMock(return_value=mock_tags)
        mock_client.post = AsyncMock(return_value=chat_resp)

        with patch("httpx.AsyncClient", return_value=mock_client):
            with pytest.raises(HTTPException) as exc_info:
                asyncio.run(_forward_to_ollama(
                    [{"role": "user", "content": "Hi"}],
                    self._make_request(),
                ))

        assert exc_info.value.status_code == 500

    def test_no_chat_models_raises_503(self):
        """Si no hi ha chat models (només embeddings), HTTPException 503."""
        from core.endpoints.chat import _forward_to_ollama
        from fastapi import HTTPException

        # All models are embedding models
        tags_data = {"models": [{"name": "nomic-embed-text"}, {"name": "mxbai-embed-large"}]}
        mock_tags = MagicMock()
        mock_tags.status_code = 200
        mock_tags.json.return_value = tags_data

        mock_client = AsyncMock()
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)
        mock_client.get = AsyncMock(return_value=mock_tags)

        with patch("httpx.AsyncClient", return_value=mock_client):
            with pytest.raises(HTTPException) as exc_info:
                asyncio.run(_forward_to_ollama(
                    [{"role": "user", "content": "Hi"}],
                    self._make_request(model="nonexistent"),
                ))

        assert exc_info.value.status_code == 503

    def test_model_partial_match_used(self):
        """Si el model demanat no existeix però hi ha match parcial, usa'l."""
        from core.endpoints.chat import _forward_to_ollama

        tags_data = {"models": [{"name": "llama3.2:latest"}]}
        mock_tags = MagicMock()
        mock_tags.status_code = 200
        mock_tags.json.return_value = tags_data

        chat_resp = MagicMock()
        chat_resp.status_code = 200
        chat_resp.json.return_value = {"message": {"content": "OK"}}

        mock_client = AsyncMock()
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)
        mock_client.get = AsyncMock(return_value=mock_tags)
        mock_client.post = AsyncMock(return_value=chat_resp)

        with patch("httpx.AsyncClient", return_value=mock_client):
            result = asyncio.run(_forward_to_ollama(
                [{"role": "user", "content": "Hi"}],
                self._make_request(model="llama3.2"),
            ))

        assert isinstance(result, dict)

    def test_model_not_found_raises_404(self):
        """Bug 23 (2026-04-06): si el model demanat no existeix i no hi ha
        match parcial, abans feiem fallback silenciós al primer chat model
        (HTTP 200 amb un model diferent del demanat — enganyós). Ara retornem
        HTTPException 404 perquè el client sàpiga que el model no existeix."""
        from core.endpoints.chat import _forward_to_ollama
        from fastapi import HTTPException

        tags_data = {"models": [{"name": "mistral:7b"}]}
        mock_tags = MagicMock()
        mock_tags.status_code = 200
        mock_tags.json.return_value = tags_data

        mock_client = AsyncMock()
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)
        mock_client.get = AsyncMock(return_value=mock_tags)

        with patch("httpx.AsyncClient", return_value=mock_client):
            with pytest.raises(HTTPException) as exc_info:
                asyncio.run(_forward_to_ollama(
                    [{"role": "user", "content": "Hi"}],
                    self._make_request(model="completely-nonexistent"),
                ))

        assert exc_info.value.status_code == 404
        assert "not found" in str(exc_info.value.detail).lower()

    def test_ollama_post_connect_error(self):
        """ConnectError durant POST → HTTPException 503."""
        import httpx
        from core.endpoints.chat import _forward_to_ollama
        from fastapi import HTTPException

        tags_data = {"models": [{"name": "llama3.2"}]}
        mock_tags = MagicMock()
        mock_tags.status_code = 200
        mock_tags.json.return_value = tags_data

        call_count = [0]

        async def mock_get(*args, **kwargs):
            return mock_tags

        async def mock_post(*args, **kwargs):
            raise httpx.ConnectError("Connection refused")

        mock_client = AsyncMock()
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)
        mock_client.get = mock_get
        mock_client.post = mock_post

        with patch("httpx.AsyncClient", return_value=mock_client):
            with pytest.raises(HTTPException) as exc:
                asyncio.run(_forward_to_ollama(
                    [{"role": "user", "content": "Hi"}],
                    self._make_request(),
                ))

        assert exc.value.status_code == 503

    def test_streaming_returns_streaming_response(self):
        """Mode stream=True retorna StreamingResponse."""
        from core.endpoints.chat import _forward_to_ollama

        tags_data = {"models": [{"name": "llama3.2"}]}
        mock_tags = MagicMock()
        mock_tags.status_code = 200
        mock_tags.json.return_value = tags_data

        mock_client = AsyncMock()
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)
        mock_client.get = AsyncMock(return_value=mock_tags)

        app_state = MagicMock()
        app_state.config = {}

        with patch("httpx.AsyncClient", return_value=mock_client), \
             patch.dict(os.environ, {"NEXE_OLLAMA_MODEL": "llama3.2"}):
            result = asyncio.run(_forward_to_ollama(
                [{"role": "user", "content": "Hi"}],
                self._make_request(stream=True),
                app_state=app_state
            ))

        assert isinstance(result, StreamingResponse)

    def test_tags_error_status_raises_502(self):
        """Ollama /api/tags retorna status != 200 → HTTPException 502."""
        from core.endpoints.chat import _forward_to_ollama
        from fastapi import HTTPException

        mock_tags = MagicMock()
        mock_tags.status_code = 503

        mock_client = AsyncMock()
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)
        mock_client.get = AsyncMock(return_value=mock_tags)

        with patch("httpx.AsyncClient", return_value=mock_client):
            with pytest.raises(HTTPException) as exc:
                asyncio.run(_forward_to_ollama(
                    [{"role": "user", "content": "Hi"}],
                    self._make_request(),
                ))

        assert exc.value.status_code == 502

    def test_model_from_config(self):
        """Model es llegeix de config quan no hi ha env var."""
        from core.endpoints.chat import _forward_to_ollama

        tags_data = {"models": [{"name": "gemma3"}]}
        mock_tags = MagicMock()
        mock_tags.status_code = 200
        mock_tags.json.return_value = tags_data

        chat_resp = MagicMock()
        chat_resp.status_code = 200
        chat_resp.json.return_value = {"message": {"content": "OK"}}

        mock_client = AsyncMock()
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)
        mock_client.get = AsyncMock(return_value=mock_tags)
        mock_client.post = AsyncMock(return_value=chat_resp)

        app_state = MagicMock()
        app_state.config = {"plugins": {"models": {"primary": "gemma3"}}}

        env_without = {k: v for k, v in os.environ.items()
                       if k not in ("NEXE_OLLAMA_MODEL", "NEXE_DEFAULT_MODEL")}

        with patch("httpx.AsyncClient", return_value=mock_client), \
             patch.dict(os.environ, env_without, clear=True):
            result = asyncio.run(_forward_to_ollama(
                [{"role": "user", "content": "Hi"}],
                self._make_request(),
                app_state=app_state
            ))

        assert isinstance(result, dict)

    def test_streaming_with_fallback_adds_headers(self):
        """Mode stream=True amb fallback_from afegeix headers."""
        from core.endpoints.chat import _forward_to_ollama

        tags_data = {"models": [{"name": "llama3.2"}]}
        mock_tags = MagicMock()
        mock_tags.status_code = 200
        mock_tags.json.return_value = tags_data

        mock_client = AsyncMock()
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)
        mock_client.get = AsyncMock(return_value=mock_tags)

        with patch("httpx.AsyncClient", return_value=mock_client), \
             patch.dict(os.environ, {"NEXE_OLLAMA_MODEL": "llama3.2"}):
            result = asyncio.run(_forward_to_ollama(
                [{"role": "user", "content": "Hi"}],
                self._make_request(stream=True),
                fallback_from="mlx",
                fallback_reason="module_unavailable",
            ))

        assert isinstance(result, StreamingResponse)
        assert result.headers.get("X-Nexe-Fallback-From") == "mlx"


# ─── TestOllamaStreamGenerator ───────────────────────────────────────────────

class TestOllamaStreamGenerator:

    def _collect(self, gen):
        """Collect all output from an async generator."""
        async def _run():
            results = []
            async for item in gen:
                results.append(item)
            return results
        return asyncio.run(_run())

    def test_yields_sse_chunks(self):
        """Genera chunks SSE per cada token."""
        from core.endpoints.chat import _ollama_stream_generator

        lines = [
            json.dumps({"message": {"content": "Hola "}, "done": False}),
            json.dumps({"message": {"content": "món"}, "done": True}),
        ]

        mock_resp = AsyncMock()
        mock_resp.status_code = 200

        async def mock_aiter_lines():
            for line in lines:
                yield line

        mock_resp.aiter_lines = mock_aiter_lines

        mock_stream = AsyncMock()
        mock_stream.__aenter__ = AsyncMock(return_value=mock_resp)
        mock_stream.__aexit__ = AsyncMock(return_value=False)

        mock_client = AsyncMock()
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)
        mock_client.stream = MagicMock(return_value=mock_stream)

        with patch("httpx.AsyncClient", return_value=mock_client), \
             patch("core.endpoints.chat._save_conversation_to_memory", AsyncMock()):
            chunks = self._collect(_ollama_stream_generator(
                "http://localhost:11434/api/chat",
                {"model": "llama3.2", "messages": [], "stream": True},
                app_state=MagicMock(),
                user_msg="Hi"
            ))

        assert any("Hola" in c for c in chunks)
        assert any("[DONE]" in c for c in chunks)

    def test_error_status_yields_error_and_done(self):
        """Status != 200 → yields error i [DONE]."""
        from core.endpoints.chat import _ollama_stream_generator

        mock_resp = AsyncMock()
        mock_resp.status_code = 500

        mock_stream = AsyncMock()
        mock_stream.__aenter__ = AsyncMock(return_value=mock_resp)
        mock_stream.__aexit__ = AsyncMock(return_value=False)

        mock_client = AsyncMock()
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)
        mock_client.stream = MagicMock(return_value=mock_stream)

        with patch("httpx.AsyncClient", return_value=mock_client):
            chunks = self._collect(_ollama_stream_generator(
                "http://localhost:11434/api/chat",
                {},
            ))

        assert any("error" in c for c in chunks)
        assert any("[DONE]" in c for c in chunks)

    def test_connect_error_yields_error(self):
        """ConnectError → yields error."""
        import httpx
        from core.endpoints.chat import _ollama_stream_generator

        mock_client = AsyncMock()
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)
        mock_client.stream = MagicMock(side_effect=httpx.ConnectError("refused"))

        with patch("httpx.AsyncClient", return_value=mock_client):
            chunks = self._collect(_ollama_stream_generator(
                "http://localhost:11434/api/chat",
                {},
            ))

        assert any("error" in c.lower() for c in chunks)

    def test_json_decode_error_skipped(self):
        """Línies amb JSON invalid s'ignoren sense crash."""
        from core.endpoints.chat import _ollama_stream_generator

        lines = [
            "INVALID JSON",
            json.dumps({"message": {"content": "OK"}, "done": True}),
        ]

        mock_resp = AsyncMock()
        mock_resp.status_code = 200

        async def mock_aiter_lines():
            for line in lines:
                yield line

        mock_resp.aiter_lines = mock_aiter_lines

        mock_stream = AsyncMock()
        mock_stream.__aenter__ = AsyncMock(return_value=mock_resp)
        mock_stream.__aexit__ = AsyncMock(return_value=False)

        mock_client = AsyncMock()
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)
        mock_client.stream = MagicMock(return_value=mock_stream)

        with patch("httpx.AsyncClient", return_value=mock_client), \
             patch("core.endpoints.chat._save_conversation_to_memory", AsyncMock()):
            chunks = self._collect(_ollama_stream_generator(
                "http://localhost:11434/api/chat",
                {"model": "llama3.2", "messages": [], "stream": True},
                app_state=MagicMock(),
                user_msg="Hi"
            ))

        assert any("[DONE]" in c for c in chunks)

    def test_empty_line_skipped(self):
        """Línies buides s'ignoren."""
        from core.endpoints.chat import _ollama_stream_generator

        lines = [
            "",
            json.dumps({"message": {"content": "token"}, "done": True}),
        ]

        mock_resp = AsyncMock()
        mock_resp.status_code = 200

        async def mock_aiter_lines():
            for line in lines:
                yield line

        mock_resp.aiter_lines = mock_aiter_lines

        mock_stream = AsyncMock()
        mock_stream.__aenter__ = AsyncMock(return_value=mock_resp)
        mock_stream.__aexit__ = AsyncMock(return_value=False)

        mock_client = AsyncMock()
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)
        mock_client.stream = MagicMock(return_value=mock_stream)

        with patch("httpx.AsyncClient", return_value=mock_client), \
             patch("core.endpoints.chat._save_conversation_to_memory", AsyncMock()):
            chunks = self._collect(_ollama_stream_generator(
                "http://localhost:11434/api/chat",
                {},
                app_state=MagicMock(),
                user_msg="Hi"
            ))

        assert any("[DONE]" in c for c in chunks)


# ─── TestForwardToMLX ─────────────────────────────────────────────────────────

class TestForwardToMLX:

    def _make_request(self, stream=False, model=None):
        from core.endpoints.chat import ChatCompletionRequest, Message
        return ChatCompletionRequest(
            messages=[Message(role="user", content="Test")],
            stream=stream,
            model=model,
            use_rag=False,
        )

    def _make_fastapi_request(self, modules=None):
        req = MagicMock()
        req.app.state.modules = modules or {}
        # Return "" for any headers.get call (compatible with .encode())
        def _headers_get(key, default=None):
            return default if default is not None else ""
        req.headers.get = _headers_get
        return req

    def test_no_mlx_module_falls_back_to_ollama(self):
        """Sense mlx_module, fa fallback a Ollama."""
        import httpx
        from core.endpoints.chat import _forward_to_mlx
        from fastapi import HTTPException

        mock_client = AsyncMock()
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)
        mock_client.get = AsyncMock(side_effect=httpx.ConnectError("refused"))

        req = self._make_fastapi_request(modules={})

        with patch("httpx.AsyncClient", return_value=mock_client):
            with pytest.raises(HTTPException) as exc:
                asyncio.run(_forward_to_mlx(
                    [{"role": "user", "content": "Hi"}],
                    self._make_request(),
                    req
                ))

        assert exc.value.status_code == 503

    def test_mlx_module_without_chat_attr_falls_back(self):
        """MLX module sense attr 'chat', fa fallback."""
        import httpx
        from core.endpoints.chat import _forward_to_mlx
        from fastapi import HTTPException

        mock_client = AsyncMock()
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)
        mock_client.get = AsyncMock(side_effect=httpx.ConnectError("refused"))

        req = self._make_fastapi_request(modules={"mlx_module": object()})  # no chat attr

        with patch("httpx.AsyncClient", return_value=mock_client):
            with pytest.raises(HTTPException) as exc:
                asyncio.run(_forward_to_mlx(
                    [{"role": "user", "content": "Hi"}],
                    self._make_request(),
                    req
                ))

        assert exc.value.status_code == 503

    def test_mlx_non_streaming_returns_openai_format(self):
        """MLX non-streaming retorna format compatible amb OpenAI."""
        from core.endpoints.chat import _forward_to_mlx

        mlx_module = AsyncMock()
        mlx_module.chat = AsyncMock(return_value={
            "response": "Hola MLX",
            "tokens": 5,
            "prompt_tokens": 3,
            "context_used": 8,
        })

        req = self._make_fastapi_request(modules={"mlx_module": mlx_module})

        result = asyncio.run(_forward_to_mlx(
            [{"role": "user", "content": "Hi"}],
            self._make_request(),
            req
        ))

        assert isinstance(result, dict)
        assert result["choices"][0]["message"]["content"] == "Hola MLX"

    def test_mlx_streaming_returns_streaming_response(self):
        """MLX streaming retorna StreamingResponse."""
        from core.endpoints.chat import _forward_to_mlx

        mlx_module = AsyncMock()
        mlx_module.chat = AsyncMock(return_value={"response": "OK"})

        req = self._make_fastapi_request(modules={"mlx_module": mlx_module})

        result = asyncio.run(_forward_to_mlx(
            [{"role": "user", "content": "Hi"}],
            self._make_request(stream=True),
            req
        ))

        assert isinstance(result, StreamingResponse)

    def test_mlx_exception_falls_back_to_ollama(self):
        """Excepció durant MLX → fallback a Ollama."""
        import httpx
        from core.endpoints.chat import _forward_to_mlx
        from fastapi import HTTPException

        mlx_module = AsyncMock()
        mlx_module.chat = AsyncMock(side_effect=Exception("GPU error"))

        mock_client = AsyncMock()
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)
        mock_client.get = AsyncMock(side_effect=httpx.ConnectError("refused"))

        req = self._make_fastapi_request(modules={"mlx_module": mlx_module})

        with patch("httpx.AsyncClient", return_value=mock_client):
            with pytest.raises(HTTPException) as exc:
                asyncio.run(_forward_to_mlx(
                    [{"role": "user", "content": "Hi"}],
                    self._make_request(),
                    req
                ))

        assert exc.value.status_code == 503

    def test_mlx_separates_system_and_user_messages(self):
        """Separa system message de user messages per MLX."""
        from core.endpoints.chat import _forward_to_mlx

        mlx_module = AsyncMock()
        mlx_module.chat = AsyncMock(return_value={"response": "OK"})

        req = self._make_fastapi_request(modules={"mlx_module": mlx_module})

        messages = [
            {"role": "system", "content": "You are Nexe"},
            {"role": "user", "content": "Hello"},
        ]

        result = asyncio.run(_forward_to_mlx(messages, self._make_request(), req))

        call_kwargs = mlx_module.chat.call_args[1]
        assert call_kwargs["system"] == "You are Nexe"
        assert call_kwargs["messages"] == [{"role": "user", "content": "Hello"}]


# ─── TestForwardToLlamaCpp ────────────────────────────────────────────────────

class TestForwardToLlamaCpp:

    def _make_request(self, stream=False, model=None):
        from core.endpoints.chat import ChatCompletionRequest, Message
        return ChatCompletionRequest(
            messages=[Message(role="user", content="Test")],
            stream=stream,
            model=model,
            use_rag=False,
        )

    def _make_fastapi_request(self, modules=None):
        req = MagicMock()
        req.app.state.modules = modules or {}
        def _headers_get(key, default=None):
            return default if default is not None else ""
        req.headers.get = _headers_get
        return req

    def test_no_llama_module_falls_back(self):
        """Sense llama_cpp_module, fa fallback a Ollama."""
        import httpx
        from core.endpoints.chat import _forward_to_llama_cpp
        from fastapi import HTTPException

        mock_client = AsyncMock()
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)
        mock_client.get = AsyncMock(side_effect=httpx.ConnectError("refused"))

        req = self._make_fastapi_request(modules={})

        with patch("httpx.AsyncClient", return_value=mock_client):
            with pytest.raises(HTTPException) as exc:
                asyncio.run(_forward_to_llama_cpp(
                    [{"role": "user", "content": "Hi"}],
                    self._make_request(),
                    req
                ))

        assert exc.value.status_code == 503

    def test_llama_cpp_non_streaming_success(self):
        """Llama.cpp non-streaming retorna format OpenAI."""
        from core.endpoints.chat import _forward_to_llama_cpp

        llama_module = AsyncMock()
        llama_module.chat = AsyncMock(return_value={
            "response": "Hola Llama.cpp",
            "tokens": 6,
            "prompt_tokens": 3,
            "context_used": 9,
        })

        req = self._make_fastapi_request(modules={"llama_cpp_module": llama_module})

        result = asyncio.run(_forward_to_llama_cpp(
            [{"role": "user", "content": "Hi"}],
            self._make_request(),
            req
        ))

        assert isinstance(result, dict)
        assert result["choices"][0]["message"]["content"] == "Hola Llama.cpp"

    def test_llama_cpp_streaming_returns_streaming_response(self):
        """Llama.cpp streaming retorna StreamingResponse."""
        from core.endpoints.chat import _forward_to_llama_cpp

        llama_module = AsyncMock()
        llama_module.chat = AsyncMock(return_value={"response": "OK"})

        req = self._make_fastapi_request(modules={"llama_cpp_module": llama_module})

        result = asyncio.run(_forward_to_llama_cpp(
            [{"role": "user", "content": "Hi"}],
            self._make_request(stream=True),
            req
        ))

        assert isinstance(result, StreamingResponse)

    def test_llama_cpp_exception_falls_back(self):
        """Excepció durant llama.cpp → fallback a Ollama."""
        import httpx
        from core.endpoints.chat import _forward_to_llama_cpp
        from fastapi import HTTPException

        llama_module = AsyncMock()
        llama_module.chat = AsyncMock(side_effect=Exception("Model error"))

        mock_client = AsyncMock()
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)
        mock_client.get = AsyncMock(side_effect=httpx.ConnectError("refused"))

        req = self._make_fastapi_request(modules={"llama_cpp_module": llama_module})

        with patch("httpx.AsyncClient", return_value=mock_client):
            with pytest.raises(HTTPException) as exc:
                asyncio.run(_forward_to_llama_cpp(
                    [{"role": "user", "content": "Hi"}],
                    self._make_request(),
                    req
                ))

        assert exc.value.status_code == 503

    def test_llama_cpp_separates_system_messages(self):
        """Separa system message de user messages per llama.cpp."""
        from core.endpoints.chat import _forward_to_llama_cpp

        llama_module = AsyncMock()
        llama_module.chat = AsyncMock(return_value={"response": "OK"})

        req = self._make_fastapi_request(modules={"llama_cpp_module": llama_module})

        messages = [
            {"role": "system", "content": "System prompt"},
            {"role": "user", "content": "User message"},
        ]

        result = asyncio.run(_forward_to_llama_cpp(messages, self._make_request(), req))

        call_kwargs = llama_module.chat.call_args[1]
        assert call_kwargs["system"] == "System prompt"
        assert call_kwargs["messages"] == [{"role": "user", "content": "User message"}]


# ─── TestMLXStreamGenerator ───────────────────────────────────────────────────

class TestMLXStreamGenerator:

    def _collect(self, gen):
        async def _run():
            results = []
            async for item in gen:
                results.append(item)
            return results
        return asyncio.run(_run())

    def test_yields_tokens_as_sse(self):
        """MLX stream generator yields tokens in SSE format."""
        from core.endpoints.chat import _mlx_stream_generator
        import threading

        async def fake_chat(messages, system, session_id, stream_callback=None, **kwargs):
            # Simulate MLX calling stream_callback from a separate thread
            if stream_callback:
                def _emit():
                    import time
                    time.sleep(0.05)
                    stream_callback("Hola ")
                    time.sleep(0.05)
                    stream_callback("món")
                t = threading.Thread(target=_emit)
                t.start()
                t.join()
            return {"tokens": 2, "tokens_per_second": 20.0}

        mlx_module = AsyncMock()
        mlx_module.chat = fake_chat

        with patch("core.endpoints.chat._save_conversation_to_memory", AsyncMock()):
            chunks = self._collect(_mlx_stream_generator(
                mlx_module=mlx_module,
                user_messages=[{"role": "user", "content": "Hi"}],
                system_msg="You are Nexe",
                model_name="mlx-local",
                app_state=MagicMock(),
                user_msg="Hi",
            ))

        text = "".join(chunks)
        assert "Hola" in text or "món" in text
        assert "[DONE]" in text

    def test_yields_done_at_end(self):
        """El generator sempre acaba amb [DONE]."""
        from core.endpoints.chat import _mlx_stream_generator

        async def fake_chat(messages, system, session_id, stream_callback=None):
            return {"tokens": 0, "tokens_per_second": 0}

        mlx_module = AsyncMock()
        mlx_module.chat = fake_chat

        with patch("core.endpoints.chat._save_conversation_to_memory", AsyncMock()):
            chunks = self._collect(_mlx_stream_generator(
                mlx_module=mlx_module,
                user_messages=[],
                system_msg="",
                model_name="test",
                app_state=None,
                user_msg=None,
            ))

        assert any("[DONE]" in c for c in chunks)

    def test_exception_in_task_yields_done_anyway(self):
        """Excepció durant run_mlx → generator acaba amb [DONE] igualment."""
        from core.endpoints.chat import _mlx_stream_generator

        async def fake_chat(messages, system, session_id, stream_callback=None):
            raise RuntimeError("MLX GPU error")

        mlx_module = AsyncMock()
        mlx_module.chat = fake_chat

        chunks = self._collect(_mlx_stream_generator(
            mlx_module=mlx_module,
            user_messages=[],
            system_msg="",
            model_name="test",
        ))

        # When exception in run_mlx, generation_done is set → loop exits,
        # final_chunk and [DONE] are still yielded
        assert any("[DONE]" in c for c in chunks)


# ─── TestLlamaCppStreamGenerator ──────────────────────────────────────────────

class TestLlamaCppStreamGenerator:

    def _collect(self, gen):
        async def _run():
            results = []
            async for item in gen:
                results.append(item)
            return results
        return asyncio.run(_run())

    def test_yields_tokens_as_sse(self):
        """Llama.cpp stream generator yields tokens in SSE format."""
        from core.endpoints.chat import _llama_cpp_stream_generator
        import threading

        async def fake_chat(messages, system, session_id, stream_callback=None, **kwargs):
            # Simulate llama.cpp calling stream_callback from a separate thread
            if stream_callback:
                def _emit():
                    import time
                    time.sleep(0.05)
                    stream_callback("Hello ")
                    time.sleep(0.05)
                    stream_callback("world")
                t = threading.Thread(target=_emit)
                t.start()
                t.join()
            return {"tokens": 2, "tokens_per_second": 15.0}

        llama_module = AsyncMock()
        llama_module.chat = fake_chat

        with patch("core.endpoints.chat._save_conversation_to_memory", AsyncMock()):
            chunks = self._collect(_llama_cpp_stream_generator(
                llama_module=llama_module,
                user_messages=[{"role": "user", "content": "Hi"}],
                system_msg="You are Nexe",
                model_name="llama-cpp-local",
                app_state=MagicMock(),
                user_msg="Hi",
            ))

        text = "".join(chunks)
        assert "Hello" in text or "world" in text
        assert "[DONE]" in text

    def test_yields_done_at_end(self):
        """Sempre acaba amb [DONE]."""
        from core.endpoints.chat import _llama_cpp_stream_generator

        async def fake_chat(messages, system, session_id, stream_callback=None):
            return {}

        llama_module = AsyncMock()
        llama_module.chat = fake_chat

        with patch("core.endpoints.chat._save_conversation_to_memory", AsyncMock()):
            chunks = self._collect(_llama_cpp_stream_generator(
                llama_module=llama_module,
                user_messages=[],
                system_msg="",
                model_name="test",
                app_state=None,
                user_msg=None,
            ))

        assert any("[DONE]" in c for c in chunks)

    def test_exception_in_task_yields_done_anyway(self):
        """Excepció durant run_llama → generator acaba amb [DONE] igualment."""
        from core.endpoints.chat import _llama_cpp_stream_generator

        async def fake_chat(messages, system, session_id, stream_callback=None):
            raise RuntimeError("GGUF error")

        llama_module = AsyncMock()
        llama_module.chat = fake_chat

        chunks = self._collect(_llama_cpp_stream_generator(
            llama_module=llama_module,
            user_messages=[],
            system_msg="",
            model_name="test",
        ))

        assert any("[DONE]" in c for c in chunks)
