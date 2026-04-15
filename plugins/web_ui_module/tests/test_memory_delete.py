"""
Tests for MEM_DELETE and list functionality.
Covers: detect_intent delete/list, delete_from_memory with deleted_facts,
        DELETE_THRESHOLD, list_memories.
"""
import asyncio
import pytest
from unittest.mock import AsyncMock, MagicMock, patch

import plugins.web_ui_module.core.memory_helper as mh_module
from plugins.web_ui_module.core.memory_helper import (
    MemoryHelper,
    DELETE_THRESHOLD,
)


# ─── Helpers ──────────────────────────────────────────────────────────────────

def make_result(text="content", score=0.9, rid="id-1", metadata=None):
    """Create a mock search result."""
    r = MagicMock()
    r.text = text
    r.score = score
    r.id = rid
    r.payload = None
    r.metadata = metadata or {"text": text}
    return r


def make_point(text="content", rid="id-1", payload=None):
    """Create a mock qdrant scroll point."""
    p = MagicMock()
    p.id = rid
    p.payload = payload or {"text": text}
    return p


def make_memory_mock(collection_exists=True, search_results=None, count=None, scroll_points=None):
    """Create a complete MemoryAPI mock."""
    mem = MagicMock()
    mem.initialize = AsyncMock()
    mem.collection_exists = AsyncMock(return_value=collection_exists)
    mem.create_collection = AsyncMock()
    mem.delete_collection = AsyncMock()
    mem.store = AsyncMock(return_value="doc-id-123")
    mem.delete = AsyncMock()
    results = search_results if search_results is not None else []
    mem.search = AsyncMock(return_value=results)
    mem.count = AsyncMock(return_value=count if count is not None else len(results))
    # F3: list_memories now uses scroll instead of semantic search
    points = scroll_points if scroll_points is not None else []
    mem.scroll = AsyncMock(return_value=(points, None))
    return mem


@pytest.fixture
def mh():
    return MemoryHelper()


@pytest.fixture(autouse=True)
def reset_singleton():
    """Reset the global singleton between tests."""
    original = mh_module._memory_api_instance
    mh_module._memory_api_instance = None
    yield
    mh_module._memory_api_instance = original


# ═══════════════════════════════════════════════════════════════
# detect_intent — intent DELETE
# ═══════════════════════════════════════════════════════════════

class TestDetectDeleteIntent:

    def test_delete_catalan_oblida(self, mh):
        intent, content = mh.detect_intent("Oblida que em dic Joan")
        assert intent == "delete"
        assert "em dic Joan" in content

    def test_delete_catalan_oblida_macarrons(self, mh):
        """B-mem-delete: 'Oblida que m'agraden els macarrons' ha de ser intent delete."""
        intent, content = mh.detect_intent("Oblida que m'agraden els macarrons")
        assert intent == "delete"
        assert "m'agraden els macarrons" in content

    def test_delete_catalan_esborra(self, mh):
        intent, content = mh.detect_intent("Esborra que treballo a Barcelona")
        assert intent == "delete"
        assert "Barcelona" in content

    def test_delete_spanish_olvida(self, mh):
        intent, content = mh.detect_intent("Olvida que me llamo Juan")
        assert intent == "delete"
        assert "me llamo Juan" in content

    def test_delete_spanish_borra(self, mh):
        intent, content = mh.detect_intent("Borra que vivo en Madrid")
        assert intent == "delete"
        assert "Madrid" in content

    def test_delete_english_forget(self, mh):
        intent, content = mh.detect_intent("Forget that my name is John")
        assert intent == "delete"
        assert "my name is John" in content

    def test_delete_english_delete(self, mh):
        intent, content = mh.detect_intent("Delete that I work at Google")
        assert intent == "delete"
        assert "I work at Google" in content

    def test_delete_catalan_end_pattern(self, mh):
        intent, content = mh.detect_intent("Em dic Joan, oblida-ho")
        assert intent == "delete"
        assert "Em dic Joan" in content


# ═══════════════════════════════════════════════════════════════
# BUG #18 — Mid-sentence delete patterns
# ═══════════════════════════════════════════════════════════════

class TestDetectDeleteMidSentence:
    """BUG #18: Mid-sentence delete patterns that previously fell through to chat."""

    def test_catalan_pots_esborrar(self, mh):
        intent, content = mh.detect_intent("Pots esborrar que tinc 8 anys?")
        assert intent == "delete"
        assert "tinc 8 anys" in content

    def test_catalan_pots_oblidar(self, mh):
        intent, content = mh.detect_intent("Pots oblidar que visc a Barcelona?")
        assert intent == "delete"
        assert "visc a Barcelona" in content

    def test_catalan_vull_que_oblidis(self, mh):
        intent, content = mh.detect_intent("Vull que oblidis que m'agraden els gats")
        assert intent == "delete"
        assert "m'agraden els gats" in content

    def test_catalan_podries_esborrar(self, mh):
        intent, content = mh.detect_intent("Podries esborrar que treballo a Google?")
        assert intent == "delete"
        assert "treballo a Google" in content

    def test_spanish_puedes_borrar(self, mh):
        intent, content = mh.detect_intent("Puedes borrar que tengo 8 años?")
        assert intent == "delete"
        assert "tengo 8 años" in content

    def test_spanish_quiero_que_olvides(self, mh):
        intent, content = mh.detect_intent("Quiero que olvides que vivo en Madrid")
        assert intent == "delete"
        assert "vivo en Madrid" in content

    def test_spanish_podrias_borrar(self, mh):
        intent, content = mh.detect_intent("Podrías borrar que me llamo Juan?")
        assert intent == "delete"
        assert "me llamo Juan" in content

    def test_english_can_you_delete(self, mh):
        intent, content = mh.detect_intent("Can you delete that I am 8 years old?")
        assert intent == "delete"
        assert "I am 8 years old" in content

    def test_english_can_you_forget(self, mh):
        intent, content = mh.detect_intent("Can you forget that my name is John?")
        assert intent == "delete"
        assert "my name is John" in content

    def test_english_i_want_you_to_forget(self, mh):
        intent, content = mh.detect_intent("I want you to forget that I like cats")
        assert intent == "delete"
        assert "I like cats" in content

    def test_english_please_delete_that(self, mh):
        intent, content = mh.detect_intent("Please delete that my dog is called Rex")
        assert intent == "delete"
        assert "my dog is called Rex" in content

    def test_negative_not_a_delete(self, mh):
        """Normal chat about deletion should NOT trigger delete intent."""
        intent, _ = mh.detect_intent("How do I delete files in Python?")
        assert intent == "chat"

    def test_existing_patterns_still_work(self, mh):
        """Ensure existing start-of-string patterns still work after the change."""
        intent, content = mh.detect_intent("Oblida que em dic Joan")
        assert intent == "delete"
        assert "em dic Joan" in content


# ═══════════════════════════════════════════════════════════════
# BUG #18 — clear_all intent (wipe entire memory with confirmation)
# ═══════════════════════════════════════════════════════════════

class TestDetectClearAllIntent:
    """BUG #18 P0: 'Oblida tot' must be clear_all, not delete('tot')."""

    def test_catalan_oblida_tot(self, mh):
        intent, content = mh.detect_intent("Oblida tot")
        assert intent == "clear_all"
        assert content is None

    def test_catalan_oblida_ho_tot(self, mh):
        intent, _ = mh.detect_intent("Oblida-ho tot")
        assert intent == "clear_all"

    def test_catalan_esborra_tot(self, mh):
        intent, _ = mh.detect_intent("Esborra tot el que saps")
        assert intent == "clear_all"

    def test_catalan_esborra_memoria_sencera(self, mh):
        intent, _ = mh.detect_intent("Esborra la memòria sencera")
        assert intent == "clear_all"

    def test_spanish_olvida_todo(self, mh):
        intent, _ = mh.detect_intent("Olvida todo")
        assert intent == "clear_all"

    def test_spanish_olvidalo_todo(self, mh):
        intent, _ = mh.detect_intent("Olvídalo todo")
        assert intent == "clear_all"

    def test_spanish_borra_memoria_entera(self, mh):
        intent, _ = mh.detect_intent("Borra la memoria entera")
        assert intent == "clear_all"

    def test_english_forget_everything(self, mh):
        intent, _ = mh.detect_intent("Forget everything")
        assert intent == "clear_all"

    def test_english_delete_all_memories(self, mh):
        intent, _ = mh.detect_intent("Delete all memories")
        assert intent == "clear_all"

    def test_english_wipe_memory(self, mh):
        intent, _ = mh.detect_intent("Wipe all my memories")
        assert intent == "clear_all"

    def test_clear_all_precedence_over_delete(self, mh):
        """Regression guard: 'Oblida tot' must NOT fall through to delete('tot')."""
        intent, content = mh.detect_intent("Oblida tot")
        assert intent != "delete"
        assert content is None

    def test_specific_delete_still_works(self, mh):
        """Guard: 'Oblida que em dic Joan' is still a normal delete, not clear_all."""
        intent, content = mh.detect_intent("Oblida que em dic Joan")
        assert intent == "delete"
        assert "em dic Joan" in content

    def test_chat_mentioning_forget_not_triggered(self, mh):
        """Negative: topics about forgetting must not trigger clear_all."""
        intent, _ = mh.detect_intent("How do I forget old commands in bash history?")
        assert intent == "chat"


class TestClearAllConfirm:
    """BUG #18 P0: confirmation matcher for the 2-turn clear_all flow."""

    def test_short_si(self, mh):
        assert mh.matches_clear_all_confirm("sí")
        assert mh.matches_clear_all_confirm("sí.")
        assert mh.matches_clear_all_confirm("Sí,")

    def test_short_yes(self, mh):
        assert mh.matches_clear_all_confirm("yes")
        assert mh.matches_clear_all_confirm("YES")

    def test_si_esborra_tot(self, mh):
        assert mh.matches_clear_all_confirm("sí, esborra-ho tot")
        assert mh.matches_clear_all_confirm("sí esborra tot")

    def test_yes_delete_everything(self, mh):
        assert mh.matches_clear_all_confirm("yes, delete everything")
        assert mh.matches_clear_all_confirm("yes wipe all")

    def test_confirmo(self, mh):
        assert mh.matches_clear_all_confirm("confirmo")
        assert mh.matches_clear_all_confirm("confirm")

    def test_endavant(self, mh):
        assert mh.matches_clear_all_confirm("endavant")
        assert mh.matches_clear_all_confirm("go ahead")

    def test_no_match_for_random_chat(self, mh):
        assert not mh.matches_clear_all_confirm("què recordes de mi?")
        assert not mh.matches_clear_all_confirm("hola, com estàs?")
        assert not mh.matches_clear_all_confirm("no, cancel")
        assert not mh.matches_clear_all_confirm("sí que m'agrada el cafè")  # "sí que" ≠ confirm


# ═══════════════════════════════════════════════════════════════
# detect_intent — intent LIST
# ═══════════════════════════════════════════════════════════════

class TestDetectListIntent:

    def test_list_catalan_que_recordes(self, mh):
        intent, content = mh.detect_intent("Què recordes de mi?")
        assert intent == "list"
        assert content is None

    def test_list_catalan_que_saps(self, mh):
        intent, content = mh.detect_intent("Què saps de mi?")
        assert intent == "list"
        assert content is None

    def test_list_catalan_quines_memories(self, mh):
        intent, content = mh.detect_intent("Quines memòries tens?")
        assert intent == "list"
        assert content is None

    def test_list_catalan_que_tens_guardat(self, mh):
        intent, content = mh.detect_intent("Què tens guardat?")
        assert intent == "list"
        assert content is None

    def test_list_spanish_que_recuerdas(self, mh):
        intent, content = mh.detect_intent("Qué recuerdas de mí?")
        assert intent == "list"
        assert content is None

    def test_list_spanish_que_sabes(self, mh):
        intent, content = mh.detect_intent("Qué sabes de mí?")
        assert intent == "list"
        assert content is None

    def test_list_spanish_que_tienes_guardado(self, mh):
        intent, content = mh.detect_intent("Qué tienes guardado?")
        assert intent == "list"
        assert content is None

    def test_list_english_what_remember(self, mh):
        intent, content = mh.detect_intent("What do you remember about me?")
        assert intent == "list"
        assert content is None

    def test_list_english_list_memories(self, mh):
        intent, content = mh.detect_intent("List my memories")
        assert intent == "list"
        assert content is None

    def test_list_english_show_memory(self, mh):
        intent, content = mh.detect_intent("Show my memories")
        assert intent == "list"
        assert content is None

    def test_list_english_what_saved(self, mh):
        intent, content = mh.detect_intent("What have you saved?")
        assert intent == "list"
        assert content is None


# ═══════════════════════════════════════════════════════════════
# List does NOT match recall
# ═══════════════════════════════════════════════════════════════

class TestListNotRecall:

    def test_que_saps_de_mi_is_list_not_recall(self, mh):
        """'Què saps de mi?' should match list, not recall."""
        intent, _ = mh.detect_intent("Què saps de mi?")
        assert intent == "list"

    def test_que_recordes_de_mi_is_list_not_recall(self, mh):
        """'Què recordes de mi?' should match list, not recall."""
        intent, _ = mh.detect_intent("Què recordes de mi?")
        assert intent == "list"

    def test_what_do_you_know_about_me_is_list(self, mh):
        intent, _ = mh.detect_intent("What do you know about me")
        assert intent == "list"


# ═══════════════════════════════════════════════════════════════
# delete_from_memory returns deleted_facts
# ═══════════════════════════════════════════════════════════════

class TestDeleteFromMemory:

    def test_delete_returns_deleted_facts(self):
        r1 = make_result(text="Em dic Joan", score=0.90, rid="id-1")
        r2 = make_result(text="Treballo a BCN", score=0.85, rid="id-2")
        mem = make_memory_mock(search_results=[r1, r2])
        # Only personal_memory exists, user_knowledge does not
        mem.collection_exists = AsyncMock(side_effect=lambda c: c == "personal_memory")
        mh_module._memory_api_instance = mem
        helper = MemoryHelper()
        helper._memory_api = mem

        result = asyncio.run(helper.delete_from_memory("em dic Joan"))

        assert result["success"] is True
        assert result["deleted"] == 2
        assert len(result["deleted_facts"]) == 2
        assert result["deleted_facts"][0]["text"] == "Em dic Joan"
        assert result["deleted_facts"][0]["id"] == "id-1"
        assert result["deleted_facts"][0]["score"] == 0.90

    def test_delete_no_match_returns_empty_facts(self):
        mem = make_memory_mock(search_results=[])
        mh_module._memory_api_instance = mem
        helper = MemoryHelper()
        helper._memory_api = mem

        result = asyncio.run(helper.delete_from_memory("something random"))

        assert result["success"] is True
        assert result["deleted"] == 0
        assert result["deleted_facts"] == []

    def test_delete_uses_threshold_020(self):
        """Verify DELETE_THRESHOLD constant is 0.20.

        History: 0.82 → 0.70 (multilingual embeddings) → 0.55 → 0.20
        (bug #18 e2e 2026-04-15). Empirical finding: even verbatim
        queries scored below 0.55 with fastembed+paraphrase-multilingual.
        0.20 guarantees the fact gets found at the cost of occasional
        loose-match deletes. UX tradeoff accepted — 'forget' should
        actually forget."""
        assert DELETE_THRESHOLD == 0.20

    def test_delete_passes_threshold_to_search(self):
        mem = make_memory_mock(search_results=[])
        mh_module._memory_api_instance = mem
        helper = MemoryHelper()
        helper._memory_api = mem

        asyncio.run(helper.delete_from_memory("test"))

        # Check that search was called with threshold=DELETE_THRESHOLD
        for call in mem.search.call_args_list:
            assert call.kwargs.get("threshold") == DELETE_THRESHOLD


# ═══════════════════════════════════════════════════════════════
# list_memories
# ═══════════════════════════════════════════════════════════════

class TestListMemories:

    def test_list_returns_facts(self):
        p1 = make_point(text="Em dic Joan", rid="id-1",
                        payload={"text": "Em dic Joan", "saved_at": "2026-03-01T10:00:00Z", "source": "web_ui", "type": "user_fact"})
        p2 = make_point(text="Treballo a BCN", rid="id-2",
                        payload={"text": "Treballo a BCN", "saved_at": "2026-03-02T10:00:00Z", "source": "web_ui", "type": "user_fact"})
        mem = make_memory_mock(scroll_points=[p1, p2], count=2)
        mh_module._memory_api_instance = mem
        helper = MemoryHelper()
        helper._memory_api = mem

        result = asyncio.run(helper.list_memories(limit=20))

        assert result["success"] is True
        assert len(result["facts"]) == 2
        assert result["total"] == 2
        assert result["facts"][0]["text"] == "Em dic Joan"
        assert result["facts"][0]["id"] == "id-1"

    def test_list_empty_memory(self):
        mem = make_memory_mock(collection_exists=True, scroll_points=[], count=0)
        mh_module._memory_api_instance = mem
        helper = MemoryHelper()
        helper._memory_api = mem

        result = asyncio.run(helper.list_memories())

        assert result["success"] is True
        assert result["facts"] == []
        assert result["total"] == 0
        assert "No memories" in result["message"]

    def test_list_no_collection(self):
        mem = make_memory_mock(collection_exists=False)
        mh_module._memory_api_instance = mem
        helper = MemoryHelper()
        helper._memory_api = mem

        result = asyncio.run(helper.list_memories())

        assert result["success"] is True
        assert result["facts"] == []

    def test_list_no_memory_api(self):
        mh_module._memory_api_instance = None
        mh_module._memory_api_init_failed = True
        helper = MemoryHelper()

        result = asyncio.run(helper.list_memories())

        assert result["success"] is False
        assert result["facts"] == []
        mh_module._memory_api_init_failed = False


# ═══════════════════════════════════════════════════════════════
# F1 — _check_duplicate honest contract (Bug #4 part 2)
# ═══════════════════════════════════════════════════════════════

class TestSaveDuplicateContract:

    def test_check_duplicate_returns_success_false_with_duplicate_flag(self):
        """Bug #4 part 2: duplicates must NOT report success=True."""
        mem = make_memory_mock()
        helper = MemoryHelper()

        with patch.object(helper, "get_memory_api", AsyncMock(return_value=mem)), \
             patch.object(helper, "_check_duplicate", AsyncMock(return_value=True)):
            result = asyncio.run(helper.save_to_memory("Duplicate content", "sess-1"))

        assert result["success"] is False
        assert result.get("duplicate") is True
        assert result["document_id"] is None
        mem.store.assert_not_called()


# ═══════════════════════════════════════════════════════════════
# F3 — list_memories uses scroll (no language bias)
# ═══════════════════════════════════════════════════════════════

class TestListMemoriesScroll:

    def test_list_memories_uses_scroll_not_semantic_search(self):
        """F3: list_memories must call scroll(), never search()."""
        p = make_point(text="fact", rid="id-x", payload={"text": "fact"})
        mem = make_memory_mock(scroll_points=[p], count=1)
        mh_module._memory_api_instance = mem
        helper = MemoryHelper()
        helper._memory_api = mem

        asyncio.run(helper.list_memories(limit=10))

        mem.scroll.assert_called_once()
        mem.search.assert_not_called()

    def test_list_memories_returns_catalan_entries(self):
        """F3: scroll returns content regardless of query language bias."""
        p1 = make_point(text="El meu nom és Aran", rid="id-1",
                        payload={"text": "El meu nom és Aran", "source": "web_ui"})
        p2 = make_point(text="Visc a Vilafranca", rid="id-2",
                        payload={"text": "Visc a Vilafranca", "source": "web_ui"})
        mem = make_memory_mock(scroll_points=[p1, p2], count=2)
        mh_module._memory_api_instance = mem
        helper = MemoryHelper()
        helper._memory_api = mem

        result = asyncio.run(helper.list_memories(limit=20))

        assert result["success"] is True
        assert len(result["facts"]) == 2
        texts = [f["text"] for f in result["facts"]]
        assert "El meu nom és Aran" in texts
        assert "Visc a Vilafranca" in texts


# ═══════════════════════════════════════════════════════════════
# Bug #10 — collections= filter on memory ops
# ═══════════════════════════════════════════════════════════════

class TestCollectionsFilter:

    def test_list_memories_filter_excludes_when_no_personal_memory(self):
        """Bug #10: list returns empty when user disables personal_memory."""
        mem = make_memory_mock(scroll_points=[make_point()], count=1)
        mh_module._memory_api_instance = mem
        helper = MemoryHelper()
        helper._memory_api = mem

        result = asyncio.run(helper.list_memories(
            limit=20, collections=["nexe_documentation", "user_knowledge"]
        ))

        assert result["success"] is True
        assert result["facts"] == []
        assert result["total"] == 0
        mem.scroll.assert_not_called()

    def test_list_memories_filter_includes_when_personal_memory_present(self):
        """Bug #10: list works normally when personal_memory is in the filter."""
        p = make_point(text="hello", payload={"text": "hello"})
        mem = make_memory_mock(scroll_points=[p], count=1)
        mh_module._memory_api_instance = mem
        helper = MemoryHelper()
        helper._memory_api = mem

        result = asyncio.run(helper.list_memories(
            limit=20, collections=["personal_memory", "user_knowledge"]
        ))

        assert result["success"] is True
        assert len(result["facts"]) == 1

    def test_save_to_memory_filter_disabled(self):
        """Bug #10: save rejected when personal_memory not in collections."""
        mem = make_memory_mock()
        helper = MemoryHelper()

        with patch.object(helper, "get_memory_api", AsyncMock(return_value=mem)):
            result = asyncio.run(helper.save_to_memory(
                "fact", "sess", collections=["user_knowledge"]
            ))

        assert result["success"] is False
        assert "disabled" in result["message"].lower()
        mem.store.assert_not_called()

    def test_save_to_memory_filter_none_default(self):
        """Bug #10: collections=None keeps legacy behavior (saves)."""
        mem = make_memory_mock(search_results=[], count=0)
        helper = MemoryHelper()

        with patch.object(helper, "get_memory_api", AsyncMock(return_value=mem)), \
             patch.object(helper, "_check_duplicate", AsyncMock(return_value=False)), \
             patch.object(helper, "_prune_old_entries", AsyncMock(return_value=0)):
            result = asyncio.run(helper.save_to_memory("fact", "sess", collections=None))

        assert result["success"] is True
        assert result["document_id"] == "doc-id-123"

    def test_delete_from_memory_filter_collections(self):
        """Bug #10: delete only iterates the requested collections."""
        mem = make_memory_mock(search_results=[])
        mh_module._memory_api_instance = mem
        helper = MemoryHelper()
        helper._memory_api = mem

        asyncio.run(helper.delete_from_memory("foo", collections=["personal_memory"]))

        # collection_exists called for personal_memory only (no user_knowledge)
        called_cols = [c.args[0] for c in mem.collection_exists.call_args_list]
        assert "personal_memory" in called_cols
        assert "user_knowledge" not in called_cols
