"""
Tests per _prewarm_fastembed (B.1) — core/lifespan.py
"""

import pytest
from unittest.mock import AsyncMock, patch

from memory.memory.config import IngestConfig


@pytest.mark.asyncio
async def test_prewarm_calls_warmup():
    """Happy path: warmup() is called and pre_warm is activated on the instance."""
    from core.lifespan import _prewarm_fastembed

    mock_api = AsyncMock()
    mock_api.ingest_config = IngestConfig()

    with patch("memory.memory.api.v1.get_memory_api", AsyncMock(return_value=mock_api)):
        await _prewarm_fastembed()

    assert mock_api.ingest_config.pre_warm is True
    mock_api.warmup.assert_awaited_once()


@pytest.mark.asyncio
async def test_prewarm_handles_warmup_exception():
    """If warmup() raises, the function catches the exception without re-raising."""
    from core.lifespan import _prewarm_fastembed

    mock_api = AsyncMock()
    mock_api.ingest_config = IngestConfig()
    mock_api.warmup.side_effect = RuntimeError("ONNX load failed")

    with patch("memory.memory.api.v1.get_memory_api", AsyncMock(return_value=mock_api)):
        await _prewarm_fastembed()  # must not raise


@pytest.mark.asyncio
async def test_prewarm_handles_get_memory_api_exception():
    """If get_memory_api() fails, the function catches the exception without re-raising."""
    from core.lifespan import _prewarm_fastembed

    with patch("memory.memory.api.v1.get_memory_api", AsyncMock(side_effect=Exception("no db"))):
        await _prewarm_fastembed()  # must not raise
