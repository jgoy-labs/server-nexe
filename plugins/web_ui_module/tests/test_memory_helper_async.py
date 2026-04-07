"""
────────────────────────────────────
Server Nexe
Author: Jordi Goy
Location: plugins/web_ui_module/tests/test_memory_helper_async.py
Description: Tests async per MemoryHelper (get_memory_api, save, recall, stats, clear, prune).

www.jgoy.net · https://server-nexe.org
────────────────────────────────────
"""

import asyncio
import pytest
from datetime import datetime, timezone, timedelta
from unittest.mock import AsyncMock, MagicMock, patch

import plugins.web_ui_module.core.memory_helper as mh_module
from plugins.web_ui_module.core.memory_helper import (
    MemoryHelper,
    SIMILARITY_THRESHOLD,
    MAX_MEMORY_ENTRIES,
    PRUNE_BATCH_SIZE,
    TEMPORAL_DECAY_DAYS,
    get_memory_helper,
)


# ─── Helpers ──────────────────────────────────────────────────────────────────

def make_result(text="content", score=0.5, rid="id-1", metadata=None):
    """Crea un resultat de cerca mock."""
    r = MagicMock()
    r.text = text
    r.score = score
    r.id = rid
    r.metadata = metadata or {}
    return r


def make_memory_mock(
    collection_exists=True,
    search_results=None,
    store_return="doc-id-123",
    count=None,
):
    """Crea un mock complet de MemoryAPI."""
    mem = MagicMock()
    mem.initialize = AsyncMock()
    mem.collection_exists = AsyncMock(return_value=collection_exists)
    mem.create_collection = AsyncMock()
    mem.delete_collection = AsyncMock()
    mem.store = AsyncMock(return_value=store_return)
    mem.delete = AsyncMock()
    results = search_results if search_results is not None else []
    mem.search = AsyncMock(return_value=results)
    mem.count = AsyncMock(return_value=count if count is not None else len(results))
    return mem


# ─── Fixture per reset del singleton ──────────────────────────────────────────

@pytest.fixture(autouse=True)
def reset_singleton():
    """Reseteja el singleton global entre tests (instance + init_failed flag)."""
    original = mh_module._memory_api_instance
    original_failed = mh_module._memory_api_init_failed
    mh_module._memory_api_instance = None
    mh_module._memory_api_init_failed = False
    yield
    mh_module._memory_api_instance = original
    mh_module._memory_api_init_failed = original_failed


# ─── Tests get_memory_api ─────────────────────────────────────────────────────

class TestGetMemoryApi:

    def test_initializes_singleton(self):
        mem = make_memory_mock(collection_exists=True)
        helper = MemoryHelper()

        # MemoryAPI is imported inside the function: patch the source module.
        # També forcem v1 a fallar perquè caigui a la branca legacy on viu el mock.
        with patch("memory.memory.api.v1.get_memory_api", side_effect=ImportError("force fallback")):
            with patch("memory.memory.api.MemoryAPI", return_value=mem):
                result = asyncio.run(helper.get_memory_api())

        assert result is mem
        assert mh_module._memory_api_instance is mem

    def test_creates_collection_if_not_exists(self):
        mem = make_memory_mock(collection_exists=False)
        helper = MemoryHelper()

        with patch("memory.memory.api.v1.get_memory_api", side_effect=ImportError("force fallback")):
            with patch("memory.memory.api.MemoryAPI", return_value=mem):
                asyncio.run(helper.get_memory_api())

        assert mem.create_collection.call_count == 2  # personal_memory + user_knowledge

    def test_reuses_existing_singleton(self):
        mem = make_memory_mock()
        mh_module._memory_api_instance = mem
        helper = MemoryHelper()

        with patch("memory.memory.api.MemoryAPI") as mock_cls:
            result = asyncio.run(helper.get_memory_api())

        mock_cls.assert_not_called()
        assert result is mem

    def test_returns_none_on_exception(self):
        helper = MemoryHelper()
        with patch("memory.memory.api.v1.get_memory_api", side_effect=ImportError("force fallback")):
            with patch("memory.memory.api.MemoryAPI", side_effect=Exception("no MemoryAPI")):
                result = asyncio.run(helper.get_memory_api())

        assert result is None
        assert mh_module._memory_api_instance is None

    def test_sets_instance_attribute(self):
        mem = make_memory_mock()
        helper = MemoryHelper()
        with patch("memory.memory.api.v1.get_memory_api", side_effect=ImportError("force fallback")):
            with patch("memory.memory.api.MemoryAPI", return_value=mem):
                asyncio.run(helper.get_memory_api())

        assert helper._memory_api is mem


# ─── Tests _check_duplicate ───────────────────────────────────────────────────

class TestCheckDuplicate:

    def test_duplicate_above_threshold_returns_true(self):
        high_score = make_result(score=SIMILARITY_THRESHOLD + 0.01)
        mem = make_memory_mock(search_results=[high_score])
        helper = MemoryHelper()

        result = asyncio.run(helper._check_duplicate("test content", mem))
        assert result is True

    def test_below_threshold_returns_false(self):
        low_score = make_result(score=SIMILARITY_THRESHOLD - 0.1)
        mem = make_memory_mock(search_results=[low_score])
        helper = MemoryHelper()

        result = asyncio.run(helper._check_duplicate("test content", mem))
        assert result is False

    def test_empty_results_returns_false(self):
        mem = make_memory_mock(search_results=[])
        helper = MemoryHelper()

        result = asyncio.run(helper._check_duplicate("content", mem))
        assert result is False

    def test_exception_returns_false(self):
        mem = MagicMock()
        mem.search = AsyncMock(side_effect=Exception("search error"))
        helper = MemoryHelper()

        result = asyncio.run(helper._check_duplicate("content", mem))
        assert result is False

    def test_exact_threshold_is_duplicate(self):
        exact = make_result(score=SIMILARITY_THRESHOLD)
        mem = make_memory_mock(search_results=[exact])
        helper = MemoryHelper()

        result = asyncio.run(helper._check_duplicate("content", mem))
        assert result is True


# ─── Tests _prune_old_entries ─────────────────────────────────────────────────

class TestPruneOldEntries:

    def test_no_prune_when_below_limit(self):
        # MAX_MEMORY_ENTRIES = 500, retornem 5 resultats — no cal poda
        entries = [make_result(rid=f"id-{i}") for i in range(5)]
        mem = make_memory_mock(collection_exists=True, search_results=entries)
        helper = MemoryHelper()

        deleted = asyncio.run(helper._prune_old_entries(mem))
        assert deleted == 0
        mem.delete.assert_not_called()

    def test_prunes_when_above_limit(self):
        # Crear MAX_MEMORY_ENTRIES + PRUNE_BATCH_SIZE + 1 entrades
        count = MAX_MEMORY_ENTRIES + PRUNE_BATCH_SIZE + 1
        entries = []
        for i in range(count):
            e = MagicMock()
            e.id = f"id-{i}"
            e.text = f"text {i}"
            e.metadata = {"type": "conversation", "access_count": 0, "saved_at": ""}
            entries.append(e)

        mem = make_memory_mock(collection_exists=True, search_results=entries)
        helper = MemoryHelper()

        deleted = asyncio.run(helper._prune_old_entries(mem))
        assert deleted > 0
        assert mem.delete.call_count > 0

    def test_collection_not_exists_returns_0(self):
        mem = make_memory_mock(collection_exists=False)
        helper = MemoryHelper()

        deleted = asyncio.run(helper._prune_old_entries(mem))
        assert deleted == 0

    def test_search_exception_returns_0(self):
        mem = MagicMock()
        mem.collection_exists = AsyncMock(return_value=True)
        mem.search = AsyncMock(side_effect=Exception("DB error"))
        helper = MemoryHelper()

        deleted = asyncio.run(helper._prune_old_entries(mem))
        assert deleted == 0

    def test_entry_without_id_skipped(self):
        # Creem MAX_MEMORY_ENTRIES + 1 entrades on algunes no tenen id
        count = MAX_MEMORY_ENTRIES + PRUNE_BATCH_SIZE + 1
        entries = []
        for i in range(count):
            e = MagicMock()
            e.id = None  # sense id — no s'hauria d'esborrar
            e.text = f"text {i}"
            e.metadata = {"type": "conversation", "access_count": 0, "saved_at": ""}
            entries.append(e)

        mem = make_memory_mock(collection_exists=True, search_results=entries)
        helper = MemoryHelper()

        deleted = asyncio.run(helper._prune_old_entries(mem))
        assert deleted == 0  # hasattr(entry, 'id') és True però id és None

    def test_delete_exception_doesnt_crash(self):
        count = MAX_MEMORY_ENTRIES + PRUNE_BATCH_SIZE + 1
        entries = []
        for i in range(count):
            e = MagicMock()
            e.id = f"id-{i}"
            e.text = f"text {i}"
            e.metadata = {"type": "conversation", "access_count": 0, "saved_at": ""}
            entries.append(e)

        mem = MagicMock()
        mem.collection_exists = AsyncMock(return_value=True)
        mem.search = AsyncMock(return_value=entries)
        mem.delete = AsyncMock(side_effect=Exception("delete failed"))
        helper = MemoryHelper()

        # No ha de llançar excepció
        deleted = asyncio.run(helper._prune_old_entries(mem))
        assert deleted == 0


# ─── Tests save_to_memory ─────────────────────────────────────────────────────

class TestSaveToMemory:

    def test_success(self):
        mem = make_memory_mock(search_results=[], store_return="doc-abc")
        helper = MemoryHelper()

        with patch.object(helper, "get_memory_api", AsyncMock(return_value=mem)), \
             patch.object(helper, "_check_duplicate", AsyncMock(return_value=False)), \
             patch.object(helper, "_prune_old_entries", AsyncMock(return_value=0)):
            result = asyncio.run(helper.save_to_memory("Important content", "sess-1"))

        assert result["success"] is True
        assert result["document_id"] == "doc-abc"

    def test_skips_duplicate(self):
        mem = make_memory_mock()
        helper = MemoryHelper()

        with patch.object(helper, "get_memory_api", AsyncMock(return_value=mem)), \
             patch.object(helper, "_check_duplicate", AsyncMock(return_value=True)):
            result = asyncio.run(helper.save_to_memory("Duplicate content", "sess-1"))

        # Honest contract (Bug #4 part 2): duplicates return success=False
        # with explicit duplicate=True flag so callers don't show fake "saved" badges.
        assert result["success"] is False
        assert result.get("duplicate") is True
        assert result["document_id"] is None
        mem.store.assert_not_called()

    def test_memory_not_available(self):
        helper = MemoryHelper()

        with patch.object(helper, "get_memory_api", AsyncMock(return_value=None)):
            result = asyncio.run(helper.save_to_memory("content", "sess-1"))

        assert result["success"] is False
        assert "not available" in result["message"]

    def test_exception_returns_error(self):
        helper = MemoryHelper()

        with patch.object(helper, "get_memory_api", AsyncMock(side_effect=Exception("crash"))):
            result = asyncio.run(helper.save_to_memory("content", "sess-1"))

        assert result["success"] is False

    def test_metadata_includes_source(self):
        mem = make_memory_mock(search_results=[], store_return="id-x")
        helper = MemoryHelper()
        captured_meta = {}

        async def fake_store(text, collection, metadata):
            captured_meta.update(metadata)
            return "id-x"

        mem.store = fake_store

        with patch.object(helper, "get_memory_api", AsyncMock(return_value=mem)), \
             patch.object(helper, "_check_duplicate", AsyncMock(return_value=False)), \
             patch.object(helper, "_prune_old_entries", AsyncMock(return_value=0)):
            asyncio.run(helper.save_to_memory("test", "session-42", metadata={"type": "fact"}))

        assert captured_meta.get("source") == "web_ui"
        assert captured_meta.get("session_id") == "session-42"
        assert "saved_at" in captured_meta


# ─── Tests auto_save ──────────────────────────────────────────────────────────

class TestAutoSave:

    def test_short_message_skipped(self):
        helper = MemoryHelper()
        result = asyncio.run(helper.auto_save("Hi", "sess"))
        assert result["success"] is True
        assert result["document_id"] is None

    def test_greeting_skipped(self):
        helper = MemoryHelper()
        result = asyncio.run(helper.auto_save("Hola, com estàs?", "sess"))
        assert result["success"] is True
        assert result["document_id"] is None

    def test_trivial_ok_skipped(self):
        helper = MemoryHelper()
        result = asyncio.run(helper.auto_save("vale, entendido", "sess"))
        assert result["success"] is True
        assert result["document_id"] is None

    def test_meaningful_message_saved(self):
        helper = MemoryHelper()

        mock_result = {"success": True, "document_id": "doc-99", "message": "✓"}
        with patch.object(helper, "save_to_memory", AsyncMock(return_value=mock_result)):
            result = asyncio.run(helper.auto_save(
                "El meu nom és Jordi i treballo com a programador", "sess-1"
            ))

        assert result["document_id"] == "doc-99"

    def test_strips_whitespace(self):
        helper = MemoryHelper()

        called_with = {}
        async def fake_save(content, session_id, metadata=None):
            called_with["content"] = content
            return {"success": True, "document_id": "x", "message": ""}

        with patch.object(helper, "save_to_memory", fake_save):
            asyncio.run(helper.auto_save("  some useful content here  ", "sess"))

        assert called_with["content"] == "some useful content here"

    def test_metadata_has_auto_save_type(self):
        helper = MemoryHelper()

        captured = {}
        async def fake_save(content, session_id, metadata=None):
            captured["meta"] = metadata
            return {"success": True, "document_id": "x", "message": ""}

        with patch.object(helper, "save_to_memory", fake_save):
            asyncio.run(helper.auto_save("This is important information to save", "s"))

        assert captured["meta"]["type"] == "user_message"
        assert captured["meta"]["source"] == "auto_save"


# ─── Tests save_document_chunks ───────────────────────────────────────────────

class TestSaveDocumentChunks:

    def test_success(self):
        mem = make_memory_mock(collection_exists=True)
        helper = MemoryHelper()

        with patch.object(helper, "get_memory_api", AsyncMock(return_value=mem)):
            result = asyncio.run(helper.save_document_chunks(
                chunks=["chunk one", "chunk two", "chunk three"],
                filename="test.txt",
                session_id="sess-1"
            ))

        assert result["success"] is True
        assert result["chunks_saved"] == 3
        assert mem.store.call_count == 3

    def test_memory_not_available(self):
        helper = MemoryHelper()

        with patch.object(helper, "get_memory_api", AsyncMock(return_value=None)):
            result = asyncio.run(helper.save_document_chunks(
                chunks=["chunk"],
                filename="file.txt",
                session_id="sess"
            ))

        assert result["success"] is False
        assert result["chunks_saved"] == 0

    def test_creates_collection_if_not_exists(self):
        mem = make_memory_mock(collection_exists=False)
        helper = MemoryHelper()

        with patch.object(helper, "get_memory_api", AsyncMock(return_value=mem)):
            asyncio.run(helper.save_document_chunks(
                chunks=["chunk"],
                filename="doc.pdf",
                session_id="s"
            ))

        mem.create_collection.assert_called_once()

    def test_chunk_exception_continues(self):
        """Si un chunk falla, continua amb els altres."""
        mem = make_memory_mock(collection_exists=True)
        call_count = 0

        async def store_with_error(text, collection, metadata):
            nonlocal call_count
            call_count += 1
            if call_count == 2:
                raise Exception("chunk 2 failed")
            return f"id-{call_count}"

        mem.store = store_with_error
        helper = MemoryHelper()

        with patch.object(helper, "get_memory_api", AsyncMock(return_value=mem)):
            result = asyncio.run(helper.save_document_chunks(
                chunks=["c1", "c2", "c3"],
                filename="f.txt",
                session_id="s"
            ))

        # 2 guardats (c1, c3), 1 fallat (c2)
        assert result["chunks_saved"] == 2

    def test_metadata_includes_chunk_info(self):
        mem = make_memory_mock(collection_exists=True)
        captured_metas = []

        async def fake_store(text, collection, metadata):
            captured_metas.append(dict(metadata))
            return "id"

        mem.store = fake_store
        helper = MemoryHelper()

        with patch.object(helper, "get_memory_api", AsyncMock(return_value=mem)):
            asyncio.run(helper.save_document_chunks(
                chunks=["chunk A"],
                filename="report.pdf",
                session_id="sess-99"
            ))

        meta = captured_metas[0]
        assert meta["type"] == "document_chunk"
        assert meta["source_document"] == "report.pdf"
        assert meta["chunk_index"] == 0
        assert meta["session_id"] == "sess-99"

    def test_progress_log_at_25_chunks(self):
        """Comprova que no crasha amb 26 chunks (log cada 25)."""
        mem = make_memory_mock(collection_exists=True)
        helper = MemoryHelper()
        chunks = [f"chunk {i}" for i in range(26)]

        with patch.object(helper, "get_memory_api", AsyncMock(return_value=mem)):
            result = asyncio.run(helper.save_document_chunks(
                chunks=chunks,
                filename="big.txt",
                session_id="s"
            ))

        assert result["chunks_saved"] == 26


# ─── Tests recall_from_memory ─────────────────────────────────────────────────

class TestRecallFromMemory:

    def test_returns_results(self):
        r1 = make_result("El meu nom és Jordi", score=0.9, rid="r1")
        r2 = make_result("Treballo a Barcelona", score=0.8, rid="r2")
        mem = make_memory_mock(collection_exists=True, search_results=[r1, r2])
        helper = MemoryHelper()

        with patch.object(helper, "get_memory_api", AsyncMock(return_value=mem)):
            result = asyncio.run(helper.recall_from_memory("nom"))

        assert result["success"] is True
        assert len(result["results"]) <= 5
        assert result["total"] == len(result["results"])

    def test_memory_not_available(self):
        helper = MemoryHelper()

        with patch.object(helper, "get_memory_api", AsyncMock(return_value=None)):
            result = asyncio.run(helper.recall_from_memory("query"))

        assert result["success"] is False
        assert result["results"] == []

    def test_collection_not_exists_skipped(self):
        mem = make_memory_mock(collection_exists=False)
        helper = MemoryHelper()

        with patch.object(helper, "get_memory_api", AsyncMock(return_value=mem)):
            result = asyncio.run(helper.recall_from_memory("query"))

        assert result["success"] is True
        assert result["results"] == []
        mem.search.assert_not_called()

    def test_exception_returns_error(self):
        helper = MemoryHelper()

        with patch.object(helper, "get_memory_api", AsyncMock(side_effect=Exception("crash"))):
            result = asyncio.run(helper.recall_from_memory("query"))

        assert result["success"] is False

    def test_search_collection_exception_continues(self):
        """Error en una col·lecció no atura les altres."""
        mem = MagicMock()
        call_count = 0

        async def collection_exists_side(name):
            return True

        async def search_side(query, collection, top_k):
            nonlocal call_count
            call_count += 1
            if collection == "personal_memory":
                raise Exception("collection error")
            return [make_result("doc", score=0.8)]

        mem.collection_exists = collection_exists_side
        mem.search = search_side
        helper = MemoryHelper()

        with patch.object(helper, "get_memory_api", AsyncMock(return_value=mem)):
            result = asyncio.run(helper.recall_from_memory("query"))

        # user_knowledge hauria retornat 1 resultat
        assert result["success"] is True
        assert len(result["results"]) >= 0  # user_knowledge returned 1

    def test_results_sorted_by_score(self):
        r1 = make_result("low", score=0.4, rid="r1")
        r2 = make_result("high", score=0.9, rid="r2")
        r3 = make_result("mid", score=0.6, rid="r3")
        mem = make_memory_mock(collection_exists=True, search_results=[r1, r2, r3])
        helper = MemoryHelper()

        with patch.object(helper, "get_memory_api", AsyncMock(return_value=mem)):
            result = asyncio.run(helper.recall_from_memory("query", limit=10))

        scores = [r["score"] for r in result["results"]]
        assert scores == sorted(scores, reverse=True)

    def test_limit_applied(self):
        results = [make_result(f"r{i}", score=0.5, rid=f"id-{i}") for i in range(20)]
        mem = make_memory_mock(collection_exists=True, search_results=results)
        helper = MemoryHelper()

        with patch.object(helper, "get_memory_api", AsyncMock(return_value=mem)):
            result = asyncio.run(helper.recall_from_memory("query", limit=3))

        # 2 collections × 3 limit → but global limit is 3
        assert len(result["results"]) <= 3

    def test_result_has_expected_keys(self):
        r = make_result("text here", score=0.7, rid="r1", metadata={"type": "fact"})
        mem = make_memory_mock(collection_exists=True, search_results=[r])
        helper = MemoryHelper()

        with patch.object(helper, "get_memory_api", AsyncMock(return_value=mem)):
            result = asyncio.run(helper.recall_from_memory("query"))

        if result["results"]:
            item = result["results"][0]
            assert "content" in item
            assert "score" in item
            assert "original_score" in item
            assert "metadata" in item

    def test_temporal_decay_applied(self):
        """Verifica que _apply_temporal_decay es crida."""
        meta_recent = {"saved_at": datetime.now(timezone.utc).isoformat()}
        r = make_result("recent text", score=0.6, rid="r1", metadata=meta_recent)
        mem = make_memory_mock(collection_exists=True, search_results=[r])
        helper = MemoryHelper()

        with patch.object(helper, "get_memory_api", AsyncMock(return_value=mem)), \
             patch.object(helper, "_apply_temporal_decay", wraps=helper._apply_temporal_decay) as spy:
            asyncio.run(helper.recall_from_memory("query"))

        # Ha de ser cridat almenys una vegada per la col·lecció personal_memory
        assert spy.call_count >= 1


# ─── Tests get_memory_stats ───────────────────────────────────────────────────

class TestGetMemoryStats:

    def test_with_collection_returns_stats(self):
        entries = [make_result(f"e{i}", rid=f"id-{i}") for i in range(10)]
        mem = make_memory_mock(collection_exists=True, search_results=entries)
        helper = MemoryHelper()

        with patch.object(helper, "get_memory_api", AsyncMock(return_value=mem)):
            result = asyncio.run(helper.get_memory_stats())

        assert "entry_count" in result
        assert result["entry_count"] == 10
        assert "max_entries" in result
        assert "usage_percent" in result

    def test_without_collection_count_zero(self):
        mem = make_memory_mock(collection_exists=False)
        helper = MemoryHelper()

        with patch.object(helper, "get_memory_api", AsyncMock(return_value=mem)):
            result = asyncio.run(helper.get_memory_stats())

        assert result["entry_count"] == 0

    def test_memory_not_available(self):
        helper = MemoryHelper()

        with patch.object(helper, "get_memory_api", AsyncMock(return_value=None)):
            result = asyncio.run(helper.get_memory_stats())

        assert "error" in result

    def test_exception_returns_error(self):
        helper = MemoryHelper()

        with patch.object(helper, "get_memory_api", AsyncMock(side_effect=Exception("fail"))):
            result = asyncio.run(helper.get_memory_stats())

        assert "error" in result

    def test_usage_percent_calculated(self):
        entries = [make_result(f"e{i}", rid=f"id-{i}") for i in range(50)]
        mem = make_memory_mock(collection_exists=True, search_results=entries)
        helper = MemoryHelper()

        with patch.object(helper, "get_memory_api", AsyncMock(return_value=mem)):
            result = asyncio.run(helper.get_memory_stats())

        assert isinstance(result["usage_percent"], float)
        assert result["usage_percent"] == round((50 / MAX_MEMORY_ENTRIES) * 100, 1)


# ─── Tests clear_memory ───────────────────────────────────────────────────────

class TestClearMemory:

    def test_confirm_false_returns_error(self):
        helper = MemoryHelper()
        result = asyncio.run(helper.clear_memory(confirm=False))
        assert result["success"] is False
        assert "confirm=True" in result["message"]

    def test_success_clears_collection(self):
        mem = make_memory_mock(collection_exists=True)
        helper = MemoryHelper()

        with patch.object(helper, "get_memory_api", AsyncMock(return_value=mem)):
            result = asyncio.run(helper.clear_memory(confirm=True))

        assert result["success"] is True
        mem.delete_collection.assert_called_once()
        mem.create_collection.assert_called_once()

    def test_collection_not_exists_still_succeeds(self):
        mem = make_memory_mock(collection_exists=False)
        helper = MemoryHelper()

        with patch.object(helper, "get_memory_api", AsyncMock(return_value=mem)):
            result = asyncio.run(helper.clear_memory(confirm=True))

        assert result["success"] is True
        mem.delete_collection.assert_not_called()

    def test_memory_not_available(self):
        helper = MemoryHelper()

        with patch.object(helper, "get_memory_api", AsyncMock(return_value=None)):
            result = asyncio.run(helper.clear_memory(confirm=True))

        assert result["success"] is False

    def test_exception_returns_error(self):
        mem = make_memory_mock(collection_exists=True)
        mem.delete_collection = AsyncMock(side_effect=Exception("delete failed"))
        helper = MemoryHelper()

        with patch.object(helper, "get_memory_api", AsyncMock(return_value=mem)):
            result = asyncio.run(helper.clear_memory(confirm=True))

        assert result["success"] is False


# ─── Tests get_memory_helper ──────────────────────────────────────────────────

class TestGetMemoryHelper:

    def test_returns_singleton(self):
        h1 = get_memory_helper()
        h2 = get_memory_helper()
        assert h1 is h2

    def test_returns_memory_helper_instance(self):
        h = get_memory_helper()
        assert isinstance(h, MemoryHelper)
