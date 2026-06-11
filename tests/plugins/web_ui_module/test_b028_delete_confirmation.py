"""
────────────────────────────────────
Server Nexe
Author: Jordi Goy
Location: tests/plugins/web_ui_module/test_b028_delete_confirmation.py
Description: B028 (RT-02/RT-04 red team) — memory deletion safety.
    (1) Natural wipe phrasings must arm the clear-all 2-turn confirmation,
        never fall through to the partial-delete path.
    (2) delete_from_memory kills at most ONE entry: the best global match —
        no cross-collection collateral at threshold 0.20.
    (3) preview/delete-by-id pair: what the user confirms is what dies.

www.jgoy.net · https://server-nexe.org
────────────────────────────────────
"""
import asyncio
from unittest.mock import AsyncMock, MagicMock

import pytest

import plugins.web_ui_module.core.memory_helper as mh_module
from plugins.web_ui_module.core.memory_helper import MemoryHelper


def make_result(text="content", score=0.9, rid="id-1", metadata=None):
    r = MagicMock()
    r.text = text
    r.score = score
    r.id = rid
    r.payload = None
    r.metadata = metadata or {"text": text}
    return r


@pytest.fixture
def mh():
    return MemoryHelper()


@pytest.fixture(autouse=True)
def reset_singleton():
    original = mh_module._memory_api_instance
    mh_module._memory_api_instance = None
    yield
    mh_module._memory_api_instance = original


def _make_two_collection_memory(personal_results, knowledge_results):
    """MemoryAPI mock where personal_memory and user_knowledge return
    different search results — the RT-04 shape."""
    mem = MagicMock()
    mem.initialize = AsyncMock()
    mem.collection_exists = AsyncMock(return_value=True)
    mem.delete = AsyncMock()

    async def _search(query=None, collection=None, top_k=5, threshold=0.0, **kw):
        if collection == "personal_memory":
            return personal_results
        if collection == "user_knowledge":
            return knowledge_results
        return []

    mem.search = AsyncMock(side_effect=_search)
    return mem


# ═══════════════════════════════════════════════════════════════
# RT-02: natural wipe phrasings → clear_all (2-turn confirm), NOT partial
# ═══════════════════════════════════════════════════════════════

class TestNaturalClearAllTriggers:
    # The exact phrase from the red team that deleted a REAL memory of the user.
    RT02_PHRASE = "esborra tota la meva memòria, oblida-ho tot"

    @pytest.mark.parametrize("message", [
        RT02_PHRASE,
        "esborra tota la meva memòria",
        "Esborra tota la memòria",
        "oblida-ho tot",
        "esborra-ho tot",
        "oblida tot el que saps",
        "buida tota la meva memòria",
        # Spanish
        "borra toda mi memoria",
        "elimina toda la memoria",
        "olvídalo todo",
        "bórralo todo",
        "olvida todo lo que sabes",
        # English
        "delete all my memories",
        "erase all of my memory",
        "wipe my memory",
        "forget everything",
        "please forget everything you know",
        "clear all my memories",
    ])
    def test_wipe_phrases_are_clear_all(self, mh, message):
        intent, _ = mh.detect_intent(message)
        assert intent == "clear_all", f"'{message}' must arm the clear-all confirmation"

    @pytest.mark.parametrize("message,expected_content", [
        ("oblida el projecte dels coets", "el projecte dels coets"),
        ("oblida que em dic Joan", "em dic Joan"),
        ("olvida que vivo en Madrid", "vivo en Madrid"),
        ("forget that I like jazz", "I like jazz"),
    ])
    def test_legit_partial_deletes_stay_partial(self, mh, message, expected_content):
        intent, content = mh.detect_intent(message)
        assert intent == "delete"
        assert content == expected_content


# ═══════════════════════════════════════════════════════════════
# RT-04: delete_from_memory = best global match only, no collateral
# ═══════════════════════════════════════════════════════════════

class TestDeleteGlobalTopOne:
    def test_rt04_no_cross_collection_collateral(self):
        """RT-04 fixture: 'oblida els coets' matched the coets memory (0.55)
        in personal_memory AND the unrelated 'Projecte Falcó' doc (0.31) in
        user_knowledge — and deleted BOTH. Now only the best match dies."""
        coets = make_result(text="el projecte dels coets va avançant", score=0.55, rid="mem-coets")
        falco = make_result(text="INFORME TRIMESTRAL Projecte Falcó", score=0.31, rid="doc-falco")
        mem = _make_two_collection_memory([coets], [falco])
        mh_module._memory_api_instance = mem
        helper = MemoryHelper()
        helper._memory_api = mem

        result = asyncio.run(helper.delete_from_memory("el projecte dels coets"))

        assert result["deleted"] == 1
        assert result["deleted_facts"][0]["id"] == "mem-coets"
        mem.delete.assert_awaited_once_with("mem-coets", "personal_memory")

    def test_best_match_wins_regardless_of_collection_order(self):
        """If the knowledge hit scores higher, that one (and only that one) dies."""
        weak = make_result(text="fet fluix", score=0.25, rid="mem-weak")
        strong = make_result(text="capitol exacte del document", score=0.88, rid="doc-strong")
        mem = _make_two_collection_memory([weak], [strong])
        mh_module._memory_api_instance = mem
        helper = MemoryHelper()
        helper._memory_api = mem

        result = asyncio.run(helper.delete_from_memory("capitol exacte del document"))

        assert result["deleted"] == 1
        mem.delete.assert_awaited_once_with("doc-strong", "user_knowledge")


# ═══════════════════════════════════════════════════════════════
# preview + delete-by-id pair (the 2-turn contract)
# ═══════════════════════════════════════════════════════════════

class TestPreviewAndExactDelete:
    def test_preview_returns_sorted_candidates_and_never_deletes(self):
        coets = make_result(text="coets", score=0.55, rid="mem-coets")
        falco = make_result(text="falco", score=0.31, rid="doc-falco")
        mem = _make_two_collection_memory([coets], [falco])
        mh_module._memory_api_instance = mem
        helper = MemoryHelper()
        helper._memory_api = mem

        preview = asyncio.run(helper.preview_delete_from_memory("coets"))

        assert preview["success"] is True
        assert [c["id"] for c in preview["candidates"]] == ["mem-coets", "doc-falco"]
        assert preview["candidates"][0]["collection"] == "personal_memory"
        mem.delete.assert_not_called()

    def test_delete_memory_entries_uses_exact_ids(self):
        mem = _make_two_collection_memory([], [])
        mh_module._memory_api_instance = mem
        helper = MemoryHelper()
        helper._memory_api = mem
        entries = [{"id": "mem-coets", "collection": "personal_memory", "text": "coets", "score": 0.55}]

        result = asyncio.run(helper.delete_memory_entries(entries))

        assert result["deleted"] == 1
        # No re-search between preview and delete: straight to the confirmed id.
        mem.search.assert_not_called()
        mem.delete.assert_awaited_once_with("mem-coets", "personal_memory")

    def test_delete_memory_entries_survives_partial_failure(self):
        mem = _make_two_collection_memory([], [])
        mem.delete = AsyncMock(side_effect=[RuntimeError("gone"), None])
        mh_module._memory_api_instance = mem
        helper = MemoryHelper()
        helper._memory_api = mem
        entries = [
            {"id": "dead", "collection": "personal_memory", "text": "a", "score": 0.5},
            {"id": "alive", "collection": "personal_memory", "text": "b", "score": 0.4},
        ]

        result = asyncio.run(helper.delete_memory_entries(entries))

        assert result["success"] is True
        assert result["deleted"] == 1
        assert result["deleted_facts"][0]["id"] == "alive"
