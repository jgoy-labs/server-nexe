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
    DELETE_TRIGGERS,
    LIST_TRIGGERS,
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


def make_memory_mock(collection_exists=True, search_results=None, count=None):
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
        # Only nexe_web_ui exists, user_knowledge does not
        mem.collection_exists = AsyncMock(side_effect=lambda c: c == "nexe_web_ui")
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

    def test_delete_uses_threshold_082(self):
        """Verify DELETE_THRESHOLD constant is 0.82."""
        assert DELETE_THRESHOLD == 0.82

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
        r1 = make_result(text="Em dic Joan", score=0.5, rid="id-1",
                         metadata={"text": "Em dic Joan", "saved_at": "2026-03-01T10:00:00Z", "source": "web_ui", "type": "user_fact"})
        r2 = make_result(text="Treballo a BCN", score=0.4, rid="id-2",
                         metadata={"text": "Treballo a BCN", "saved_at": "2026-03-02T10:00:00Z", "source": "web_ui", "type": "user_fact"})
        mem = make_memory_mock(search_results=[r1, r2], count=2)
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
        mem = make_memory_mock(collection_exists=True, search_results=[], count=0)
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
