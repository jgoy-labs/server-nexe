"""
Tests per _prewarm_fastembed (B.1) — core/lifespan.py
"""

import pytest
from unittest.mock import AsyncMock, patch

from memory.memory.config import IngestConfig


@pytest.mark.asyncio
async def test_prewarm_calls_warmup():
    """Happy path: warmup() és cridada i pre_warm s'activa a la instància."""
    from core.lifespan import _prewarm_fastembed

    mock_api = AsyncMock()
    mock_api.ingest_config = IngestConfig()

    with patch("memory.memory.api.v1.get_memory_api", AsyncMock(return_value=mock_api)):
        await _prewarm_fastembed()

    assert mock_api.ingest_config.pre_warm is True
    mock_api.warmup.assert_awaited_once()


@pytest.mark.asyncio
async def test_prewarm_handles_warmup_exception():
    """Si warmup() llança, la funció captura l'excepció sense re-raise."""
    from core.lifespan import _prewarm_fastembed

    mock_api = AsyncMock()
    mock_api.ingest_config = IngestConfig()
    mock_api.warmup.side_effect = RuntimeError("ONNX load failed")

    with patch("memory.memory.api.v1.get_memory_api", AsyncMock(return_value=mock_api)):
        await _prewarm_fastembed()  # no ha de llançar


@pytest.mark.asyncio
async def test_prewarm_handles_get_memory_api_exception():
    """Si get_memory_api() falla, la funció captura l'excepció sense re-raise."""
    from core.lifespan import _prewarm_fastembed

    with patch("memory.memory.api.v1.get_memory_api", AsyncMock(side_effect=Exception("no db"))):
        await _prewarm_fastembed()  # no ha de llançar
