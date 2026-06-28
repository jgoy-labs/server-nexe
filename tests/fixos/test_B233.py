"""
────────────────────────────────────
Server Nexe
Location: tests/fixos/test_B233.py
Description: TDD fix for B233 — _chat_resolve_actual_engine no passa la
             capçalera d'autenticació a /status, per tant la resposta mai
             porta l'engine real i el detector de '(fallback)' és mort.
────────────────────────────────────
"""

import pytest
import asyncio
from unittest.mock import AsyncMock, MagicMock, patch


def run(coro):
    return asyncio.run(coro)


def test_resolve_actual_engine_sends_auth_header():
    """
    B233: _chat_resolve_actual_engine ha d'enviar la capçalera Authorization
    amb el token NEXE_PRIMARY_API_KEY cap a /status.
    La capçalera és la que distingeix la resposta autenticada de la no-autenticada.
    """
    from core.cli.chat_cli import _chat_resolve_actual_engine

    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.json.return_value = {"engine": "mlx"}

    captured_headers = {}

    async def fake_get(url, timeout=5.0, headers=None):
        captured_headers.update(headers or {})
        return mock_response

    mock_client = MagicMock()
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=False)
    mock_client.get = fake_get

    with patch.dict("os.environ", {"NEXE_PRIMARY_API_KEY": "test-api-key-123"}):
        with patch("httpx.AsyncClient", return_value=mock_client):
            result = run(_chat_resolve_actual_engine("http://localhost:11434", "ollama"))

    assert "Authorization" in captured_headers, (
        "La capçalera Authorization no s'ha enviat a /status"
    )
    assert "test-api-key-123" in captured_headers["Authorization"]


def test_resolve_actual_engine_detects_fallback():
    """
    B233 (detecció de fallback): quan /status retorna un engine diferent al
    configurat, la funció ha d'afegir '(fallback)' al nom de l'engine.
    Amb la crida sense auth, el servidor retorna 401 i la detecció és morta.
    Amb auth correcta, la detecció funciona.
    """
    from core.cli.chat_cli import _chat_resolve_actual_engine

    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.json.return_value = {"engine": "llama_cpp"}

    mock_client = MagicMock()
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=False)
    mock_client.get = AsyncMock(return_value=mock_response)

    with patch.dict("os.environ", {"NEXE_PRIMARY_API_KEY": "test-api-key-123"}):
        with patch("httpx.AsyncClient", return_value=mock_client):
            result = run(_chat_resolve_actual_engine("http://localhost:11434", "mlx"))

    assert "(fallback)" in result, (
        f"S'esperava '(fallback)' al resultat però s'ha rebut: '{result}'"
    )
