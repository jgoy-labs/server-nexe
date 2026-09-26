"""
────────────────────────────────────
Server Nexe — test
Author: Jordi Goy
Location: tests/core/endpoints/test_1075_textless_hit_keeps_the_context.py
Description: #1075 — `SearchResult.text` is `Optional[str]`. A single hit with
             `text=None` used to raise in `_deduplicate_results`
             (`None[:500]`), the orchestrator's broad except swallowed it and
             the whole turn went out with NO context, good hits included.
             Pinned here: the text-less hit is skipped, the good one still
             makes the context, and "None" is never written into it.

www.jgoy.net · https://server-nexe.org
────────────────────────────────────
"""
from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from core.endpoints.chat_rag import (
    _deduplicate_results,
    _format_results,
    build_rag_context,
)
from core.memory_access import DOCS_COLLECTION
from memory.memory.api.models import SearchResult


def _hit(text, id_="h"):
    return SearchResult(
        id=id_, score=0.9, collection=DOCS_COLLECTION, text=text,
        metadata={"source": "guide.md"},
    )


GOOD = "The server listens on port 9119 by default."


class TestDeduplicateSkipsTextlessHits:
    def test_none_text_is_skipped_not_raised(self):
        good = _hit(GOOD, "good")
        out = _deduplicate_results([_hit(None, "none"), good])
        assert out == [good]

    def test_non_str_and_empty_text_are_skipped(self):
        good = _hit(GOOD, "good")
        out = _deduplicate_results([_hit(b"bytes", "b"), _hit("", "e"), good])
        assert out == [good]

    def test_dedup_key_is_the_whole_text(self):
        # This pinned the 500-char key while #1091 was an open decision.
        # Decided (24/09): the whole text is the key, so both survive.
        a = _hit("A" * 500 + "x", "a")
        b = _hit("A" * 500 + "y", "b")
        assert _deduplicate_results([a, b]) == [a, b]


class TestFormatNeverWritesNone:
    def test_textless_hit_does_not_reach_the_context(self):
        out = _format_results([_hit(None, "none"), _hit(GOOD, "good")], "en")
        assert "None" not in out
        assert GOOD in out


@pytest.mark.asyncio
async def test_build_rag_context_keeps_the_good_hit():
    memory = MagicMock()
    memory.collection_exists = AsyncMock(return_value=True)
    memory.search = AsyncMock(return_value=[_hit(None, "none"), _hit(GOOD, "good")])
    memory.embed_query = AsyncMock(return_value=[0.0])

    with patch("memory.memory.api.v1.get_memory_api", AsyncMock(return_value=memory)):
        context, items = await build_rag_context(
            "which port?", app_state=None, server_lang="en",
            collections=[DOCS_COLLECTION], limit=5,
        )

    assert GOOD in context
    assert "None" not in context
    assert items == [(DOCS_COLLECTION, 0.9)]
