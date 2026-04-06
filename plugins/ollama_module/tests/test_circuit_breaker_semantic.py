"""
Bug 15 — Ollama circuit breaker NO ha de tractar errors semantics 4xx
(404 model not found, 400 bad request, 422 validation) com a fallades
d'infraestructura. Nomes 5xx + ConnectError + TimeoutError obren breaker.

Tests:
- 404 -> ModelNotFoundError + breaker NO incrementa failures
- 400/422 -> OllamaSemanticError + breaker NO incrementa failures
- 503 -> breaker SI incrementa failures
- httpx.ConnectError -> breaker SI incrementa failures
"""
import pytest
import httpx
from unittest.mock import MagicMock, AsyncMock, patch

from plugins.ollama_module.module import (
    OllamaModule,
    ModelNotFoundError,
    OllamaSemanticError,
)
from core.resilience import ollama_breaker


@pytest.fixture(autouse=True)
def reset_breaker():
    """Reset breaker state before/after each test."""
    from core.resilience.circuit_breaker import CircuitBreakerState
    ollama_breaker._state = CircuitBreakerState()
    yield
    ollama_breaker._state = CircuitBreakerState()


def _make_status_error(status_code: int) -> httpx.HTTPStatusError:
    request = httpx.Request("POST", "http://localhost:11434/api/show")
    response = httpx.Response(status_code, request=request)
    return httpx.HTTPStatusError(
        f"HTTP {status_code}", request=request, response=response
    )


def _patch_post_with_status_error(status_code: int):
    """Build a mocked AsyncClient whose post() raises HTTPStatusError on raise_for_status()."""
    mock_response = MagicMock()
    mock_response.raise_for_status = MagicMock(
        side_effect=_make_status_error(status_code)
    )
    mock_client = AsyncMock()
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=None)
    mock_client.post = AsyncMock(return_value=mock_response)
    return mock_client


class TestSemanticErrorsDoNotOpenBreaker:

    @pytest.mark.asyncio
    async def test_404_raises_model_not_found_and_keeps_breaker_closed(self):
        """404 -> ModelNotFoundError, breaker no toca."""
        module = OllamaModule()
        client = _patch_post_with_status_error(404)
        with patch("plugins.ollama_module.module.httpx.AsyncClient", return_value=client):
            with pytest.raises(ModelNotFoundError) as exc_info:
                await module.get_model_info("nonexistent-model")
        assert exc_info.value.model_name == "nonexistent-model"
        assert exc_info.value.status_code == 404
        # El breaker NO ha registrat cap failure
        assert ollama_breaker._state.failure_count == 0
        assert ollama_breaker.is_closed

    @pytest.mark.asyncio
    async def test_400_raises_semantic_and_keeps_breaker_closed(self):
        module = OllamaModule()
        client = _patch_post_with_status_error(400)
        with patch("plugins.ollama_module.module.httpx.AsyncClient", return_value=client):
            with pytest.raises(OllamaSemanticError) as exc_info:
                await module.get_model_info("bad-payload")
        assert exc_info.value.status_code == 400
        assert ollama_breaker._state.failure_count == 0
        assert ollama_breaker.is_closed

    @pytest.mark.asyncio
    async def test_422_raises_semantic_and_keeps_breaker_closed(self):
        module = OllamaModule()
        client = _patch_post_with_status_error(422)
        with patch("plugins.ollama_module.module.httpx.AsyncClient", return_value=client):
            with pytest.raises(OllamaSemanticError):
                await module.get_model_info("validation-error")
        assert ollama_breaker._state.failure_count == 0
        assert ollama_breaker.is_closed


class TestInfraErrorsDoOpenBreaker:

    @pytest.mark.asyncio
    async def test_503_increments_breaker_failures(self):
        module = OllamaModule()
        client = _patch_post_with_status_error(503)
        with patch("plugins.ollama_module.module.httpx.AsyncClient", return_value=client):
            with pytest.raises(httpx.HTTPStatusError):
                await module.get_model_info("any-model")
        assert ollama_breaker._state.failure_count == 1

    @pytest.mark.asyncio
    async def test_500_increments_breaker_failures(self):
        module = OllamaModule()
        client = _patch_post_with_status_error(500)
        with patch("plugins.ollama_module.module.httpx.AsyncClient", return_value=client):
            with pytest.raises(httpx.HTTPStatusError):
                await module.get_model_info("any-model")
        assert ollama_breaker._state.failure_count == 1

    @pytest.mark.asyncio
    async def test_connect_error_increments_breaker_failures(self):
        module = OllamaModule()
        mock_client = AsyncMock()
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=None)
        mock_client.post = AsyncMock(side_effect=httpx.ConnectError("refused"))
        with patch("plugins.ollama_module.module.httpx.AsyncClient", return_value=mock_client):
            with pytest.raises(httpx.ConnectError):
                await module.get_model_info("any-model")
        assert ollama_breaker._state.failure_count == 1


class TestRepeated404DoesNotOpenBreaker:
    """Cas real del bug: caller demana model inexistent N vegades.
    Abans -> al cap de N intents el breaker s'obria i bloquejava qualsevol
    altre model valid. Despres del fix -> el breaker mai s'obre per 404."""

    @pytest.mark.asyncio
    async def test_many_404_keeps_breaker_closed(self):
        module = OllamaModule()
        client = _patch_post_with_status_error(404)
        with patch("plugins.ollama_module.module.httpx.AsyncClient", return_value=client):
            for _ in range(20):
                with pytest.raises(ModelNotFoundError):
                    await module.get_model_info("ghost-model")
        assert ollama_breaker._state.failure_count == 0
        assert ollama_breaker.is_closed
