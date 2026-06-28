"""Tests for the helper functions extracted from _forward_to_ollama."""
import httpx
import pytest
from fastapi import HTTPException
from fastapi.responses import StreamingResponse
from unittest.mock import AsyncMock, MagicMock, patch


# ─── _resolve_ollama_model ───────────────────────────────────────────────────

class TestResolveOllamaModel:
    def test_uses_request_model(self):
        from core.endpoints.chat_engines.ollama import _resolve_ollama_model
        request = MagicMock(model="phi3")
        assert _resolve_ollama_model(request, None) == "phi3"

    def test_falls_back_to_nexe_ollama_model_env(self, monkeypatch):
        from core.endpoints.chat_engines.ollama import _resolve_ollama_model
        monkeypatch.setenv("NEXE_OLLAMA_MODEL", "mistral")
        monkeypatch.delenv("NEXE_DEFAULT_MODEL", raising=False)
        request = MagicMock(model=None)
        assert _resolve_ollama_model(request, None) == "mistral"

    def test_ignores_http_url_in_default_model(self, monkeypatch):
        from core.endpoints.chat_engines.ollama import _resolve_ollama_model
        monkeypatch.delenv("NEXE_OLLAMA_MODEL", raising=False)
        monkeypatch.setenv("NEXE_DEFAULT_MODEL", "http://huggingface.co/model")
        request = MagicMock(model=None)
        assert _resolve_ollama_model(request, None) == "llama3.2"

    def test_ultimate_fallback_is_llama32(self, monkeypatch):
        from core.endpoints.chat_engines.ollama import _resolve_ollama_model
        monkeypatch.delenv("NEXE_OLLAMA_MODEL", raising=False)
        monkeypatch.delenv("NEXE_DEFAULT_MODEL", raising=False)
        request = MagicMock(model=None)
        assert _resolve_ollama_model(request, None) == "llama3.2"


# ─── _validate_ollama_model ──────────────────────────────────────────────────

class TestValidateOllamaModel:
    async def test_returns_model_from_cache_when_fresh(self):
        from core.endpoints.chat_engines.ollama import _validate_ollama_model, _ollama_tags_cache
        import time
        _ollama_tags_cache["models"] = ["llama3.2", "phi3"]
        _ollama_tags_cache["ts"] = time.time()
        model, chat_models = await _validate_ollama_model("http://localhost:11434", "llama3.2")
        assert model == "llama3.2"
        assert "llama3.2" in chat_models

    async def test_returns_model_from_api_on_cache_miss(self):
        from core.endpoints.chat_engines.ollama import _validate_ollama_model, _ollama_tags_cache
        _ollama_tags_cache["models"] = None
        _ollama_tags_cache["ts"] = 0.0

        mock_resp = MagicMock(status_code=200)
        mock_resp.json.return_value = {"models": [{"name": "llama3.2"}]}

        mock_http = AsyncMock()
        mock_http.__aenter__.return_value.get = AsyncMock(return_value=mock_resp)
        mock_http.__aexit__ = AsyncMock(return_value=False)

        with patch("core.endpoints.chat_engines.ollama.httpx.AsyncClient", return_value=mock_http):
            model, chat_models = await _validate_ollama_model("http://localhost:11434", "llama3.2")
        assert model == "llama3.2"

    async def test_raises_503_on_connect_error(self):
        from core.endpoints.chat_engines.ollama import _validate_ollama_model, _ollama_tags_cache
        _ollama_tags_cache["models"] = None
        _ollama_tags_cache["ts"] = 0.0

        mock_http = AsyncMock()
        mock_http.__aenter__.return_value.get = AsyncMock(side_effect=httpx.ConnectError("conn"))
        mock_http.__aexit__ = AsyncMock(return_value=False)

        with patch("core.endpoints.chat_engines.ollama.httpx.AsyncClient", return_value=mock_http):
            with pytest.raises(HTTPException) as exc:
                await _validate_ollama_model("http://localhost:11434", "llama3.2")
        assert exc.value.status_code == 503


# ─── _build_ollama_payload ───────────────────────────────────────────────────

class TestBuildOllamaPayload:
    def test_builds_payload_with_correct_keys(self):
        from core.endpoints.chat_engines.ollama import _build_ollama_payload
        # top_p=None explicit: a bare MagicMock would return a truthy Mock child
        # for request.top_p, so the opt-in guard would inject a non-serializable
        # object into options. Pin it (mirror of the real schema default).
        request = MagicMock(stream=False, temperature=0.7, max_tokens=512, top_p=None)
        messages = [{"role": "user", "content": "hi"}]
        payload = _build_ollama_payload(request, messages, "llama3.2")
        assert payload["model"] == "llama3.2"
        assert payload["messages"] == messages
        assert payload["stream"] is False
        assert "options" in payload

    def test_think_enabled_from_env(self, monkeypatch):
        from core.endpoints.chat_engines.ollama import _build_ollama_payload
        monkeypatch.setenv("NEXE_OLLAMA_THINK", "true")
        request = MagicMock(stream=False, temperature=0.5, max_tokens=None, top_p=None)
        payload = _build_ollama_payload(request, [], "phi3")
        assert payload["think"] is True

    # ─── B076/S5-04: top_p wiring (opt-in mirror of temperature) ──────────────
    def test_top_p_forwarded_into_options_when_set(self):
        from core.endpoints.chat_engines.ollama import _build_ollama_payload
        request = MagicMock(stream=False, temperature=0.7, max_tokens=512, top_p=0.42)
        payload = _build_ollama_payload(request, [], "llama3.2")
        assert payload["options"]["top_p"] == 0.42

    def test_top_p_absent_from_options_when_none(self):
        from core.endpoints.chat_engines.ollama import _build_ollama_payload
        request = MagicMock(stream=False, temperature=0.7, max_tokens=512, top_p=None)
        payload = _build_ollama_payload(request, [], "llama3.2")
        # None preserves the prior byte-exact payload: no top_p key at all.
        assert "top_p" not in payload["options"]


# ─── _ollama_streaming_response ──────────────────────────────────────────────

class TestOllamaStreamingResponse:
    def test_returns_streaming_response(self):
        from core.endpoints.chat_engines.ollama import _ollama_streaming_response
        with patch("core.endpoints.chat_engines.ollama._ollama_stream_generator") as mock_gen:
            mock_gen.return_value = MagicMock()
            result = _ollama_streaming_response("http://localhost:11434/api/chat", {}, None, None, None, None)
        assert isinstance(result, StreamingResponse)

    def test_includes_fallback_headers_when_provided(self):
        from core.endpoints.chat_engines.ollama import _ollama_streaming_response
        with patch("core.endpoints.chat_engines.ollama._ollama_stream_generator") as mock_gen:
            mock_gen.return_value = MagicMock()
            result = _ollama_streaming_response(
                "http://localhost:11434/api/chat", {}, None, None,
                fallback_from="mlx", fallback_reason="not available"
            )
        assert result.headers.get("x-nexe-fallback-from") == "mlx"
        assert result.headers.get("x-nexe-fallback-reason") == "not available"


# ─── _ollama_blocking_response ───────────────────────────────────────────────

class TestOllamaBlockingResponse:
    async def test_returns_openai_format_on_success(self):
        from core.endpoints.chat_engines.ollama import _ollama_blocking_response
        raw = {
            "model": "llama3.2", "created_at": "2024",
            "message": {"role": "assistant", "content": "hi"},
            "done": True, "prompt_eval_count": 10, "eval_count": 20,
        }
        mock_resp = MagicMock(status_code=200)
        mock_resp.json.return_value = raw

        mock_http = AsyncMock()
        mock_http.__aenter__.return_value.post = AsyncMock(return_value=mock_resp)
        mock_http.__aexit__ = AsyncMock(return_value=False)

        with patch("core.endpoints.chat_engines.ollama.httpx.AsyncClient", return_value=mock_http):
            result = await _ollama_blocking_response("http://localhost:11434/api/chat", {}, None, None)

        assert result["object"] == "chat.completion"
        assert result["nexe_engine"] == "ollama"
        assert result["usage"]["total_tokens"] == 30

    async def test_raises_http_exception_on_error_status(self):
        from core.endpoints.chat_engines.ollama import _ollama_blocking_response
        mock_resp = MagicMock(status_code=500)
        mock_resp.json.return_value = {"error": "internal error"}

        mock_http = AsyncMock()
        mock_http.__aenter__.return_value.post = AsyncMock(return_value=mock_resp)
        mock_http.__aexit__ = AsyncMock(return_value=False)

        with patch("core.endpoints.chat_engines.ollama.httpx.AsyncClient", return_value=mock_http):
            with pytest.raises(HTTPException) as exc:
                await _ollama_blocking_response("http://localhost:11434/api/chat", {}, None, None)
        assert exc.value.status_code == 500

    async def test_raises_503_on_connect_error(self):
        from core.endpoints.chat_engines.ollama import _ollama_blocking_response
        mock_http = AsyncMock()
        mock_http.__aenter__.return_value.post = AsyncMock(side_effect=httpx.ConnectError("conn"))
        mock_http.__aexit__ = AsyncMock(return_value=False)

        with patch("core.endpoints.chat_engines.ollama.httpx.AsyncClient", return_value=mock_http):
            with patch("core.messages.get_message", return_value="Ollama unavailable"):
                with pytest.raises(HTTPException) as exc:
                    await _ollama_blocking_response("http://localhost:11434/api/chat", {}, None, None)
        assert exc.value.status_code == 503
