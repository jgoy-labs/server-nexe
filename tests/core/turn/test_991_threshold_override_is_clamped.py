"""#991: the per-turn RAG threshold override is clamped to [0.0, 1.0].

`core/turn/recall.py` passed `float(threshold_override)` straight on, so a
client could hand the vector search a similarity threshold of 5.0 (no hit can
ever pass) or -1 (every hit passes). What reaches `build_rag_context` is
pinned here, not the helper in isolation.
"""
from __future__ import annotations

import logging
from unittest.mock import AsyncMock, patch

import pytest

from core.turn.recall import _build_rag_context


async def _threshold_reaching_build(override):
    build = AsyncMock(return_value=("", []))
    with patch("core.endpoints.chat_rag.build_rag_context", build):
        await _build_rag_context("hola", threshold_override=override)
    build.assert_awaited_once()
    return build.await_args.kwargs["threshold_override"]


@pytest.mark.asyncio
@pytest.mark.parametrize("override, expected", [
    (5.0, 1.0),
    (-1, 0.0),
    (0.42, 0.42),
    (None, None),
])
async def test_what_reaches_build_rag_context(override, expected):
    assert await _threshold_reaching_build(override) == expected


@pytest.mark.asyncio
async def test_a_clamp_is_logged(caplog):
    with caplog.at_level(logging.WARNING, logger="core.turn.recall"):
        await _threshold_reaching_build(5.0)
    assert any("clamped to 1.0" in r.getMessage() for r in caplog.records)


@pytest.mark.asyncio
async def test_an_in_range_value_is_not_logged(caplog):
    with caplog.at_level(logging.WARNING, logger="core.turn.recall"):
        await _threshold_reaching_build(0.42)
    assert not any("clamped" in r.getMessage() for r in caplog.records)


@pytest.mark.asyncio
async def test_a_nan_override_falls_back_to_the_per_collection_thresholds(caplog):
    # min(1, max(0, nan)) is 0.0 — a NaN would silently let every hit through.
    with caplog.at_level(logging.WARNING, logger="core.turn.recall"):
        assert await _threshold_reaching_build(float("nan")) is None
    assert any("not a number" in r.getMessage() for r in caplog.records)
