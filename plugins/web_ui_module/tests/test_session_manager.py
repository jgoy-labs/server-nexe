"""
Tests unitaris per SessionManager i ChatSession.
Sense GPU — tota la lògica és en memòria + disc (tmp_path).
"""
import pytest
from datetime import datetime, timezone, timedelta

from plugins.web_ui_module.core.session_manager import ChatSession, SessionManager


# ═══════════════════════════════════════════════════════════════
# Fixtures
# ═══════════════════════════════════════════════════════════════

@pytest.fixture
def sm(tmp_path):
    return SessionManager(storage_path=str(tmp_path))


# ═══════════════════════════════════════════════════════════════
# ChatSession
# ═══════════════════════════════════════════════════════════════

class TestChatSession:

    def test_creation_generates_uuid(self):
        s = ChatSession()
        assert s.id is not None
        assert len(s.id) > 0

    def test_custom_session_id(self):
        s = ChatSession(session_id="custom-123")
        assert s.id == "custom-123"

    def test_created_at_is_utc(self):
        s = ChatSession()
        assert s.created_at.tzinfo is not None

    def test_add_message_user(self):
        s = ChatSession()
        s.add_message("user", "Hello")
        history = s.get_history()
        assert len(history) == 1
        assert history[0]["role"] == "user"
        assert history[0]["content"] == "Hello"

    def test_add_message_assistant(self):
        s = ChatSession()
        s.add_message("user", "Hi")
        s.add_message("assistant", "Hello back")
        history = s.get_history()
        assert len(history) == 2
        assert history[1]["role"] == "assistant"

    def test_get_history_returns_copy(self):
        s = ChatSession()
        s.add_message("user", "test")
        h = s.get_history()
        h.append({"role": "injected", "content": "bad"})
        assert len(s.get_history()) == 1  # Original no ha canviat

    def test_last_activity_updated_on_add_message(self):
        s = ChatSession()
        t0 = s.last_activity
        s.add_message("user", "msg")
        assert s.last_activity >= t0

    def test_to_dict_contains_keys(self):
        s = ChatSession(session_id="abc")
        s.add_message("user", "hi")
        d = s.to_dict()
        assert d["id"] == "abc"
        assert "messages" in d
        assert "created_at" in d
        assert "last_activity" in d

    def test_from_dict_roundtrip(self):
        s = ChatSession(session_id="rt-test")
        s.add_message("user", "hello")
        s.add_message("assistant", "world")
        d = s.to_dict()
        s2 = ChatSession.from_dict(d)
        assert s2.id == "rt-test"
        assert len(s2.get_history()) == 2
        assert s2.get_history()[0]["content"] == "hello"

    def test_attach_document(self):
        s = ChatSession()
        s.attach_document("doc.txt", "Full content", chunks=["c1", "c2"])
        doc = s.get_and_clear_attached_document()
        assert doc is not None
        assert doc["filename"] == "doc.txt"

    def test_get_and_clear_persists_document(self):
        """Document persists for follow-up questions (no longer clears)."""
        s = ChatSession()
        s.attach_document("f.txt", "content")
        doc1 = s.get_and_clear_attached_document()
        assert doc1 is not None
        doc2 = s.get_and_clear_attached_document()
        assert doc2 is not None
        assert doc1["filename"] == doc2["filename"]

    def test_add_context_file(self):
        s = ChatSession()
        s.add_context_file("file1.txt")
        s.add_context_file("file2.txt")
        d = s.to_dict()
        assert "file1.txt" in d["context_files"]
        assert "file2.txt" in d["context_files"]

    def test_clear_context_files(self):
        s = ChatSession()
        s.add_context_file("f.txt")
        s.clear_context_files()
        assert s.to_dict()["context_files"] == []


# ═══════════════════════════════════════════════════════════════
# SessionManager — CRUD
# ═══════════════════════════════════════════════════════════════

class TestSessionManagerCRUD:

    def test_create_session(self, sm):
        s = sm.create_session()
        assert s.id is not None

    def test_create_session_custom_id(self, sm):
        s = sm.create_session(session_id="my-id")
        assert s.id == "my-id"

    def test_get_session_returns_session(self, sm):
        s = sm.create_session()
        found = sm.get_session(s.id)
        assert found is not None
        assert found.id == s.id

    def test_get_nonexistent_returns_none(self, sm):
        assert sm.get_session("does-not-exist") is None

    def test_get_or_create_creates_new(self, sm):
        s = sm.get_or_create_session("new-x")
        assert s.id == "new-x"

    def test_get_or_create_returns_existing(self, sm):
        s1 = sm.create_session(session_id="stable")
        s1.add_message("user", "persist")
        s2 = sm.get_or_create_session("stable")
        assert s2.id == "stable"
        assert len(s2.get_history()) == 1

    def test_delete_session(self, sm):
        s = sm.create_session()
        sid = s.id
        assert sm.delete_session(sid) is True
        assert sm.get_session(sid) is None

    def test_delete_nonexistent_returns_false(self, sm):
        assert sm.delete_session("ghost") is False

    def test_list_sessions_count(self, sm):
        sm.create_session()
        sm.create_session()
        assert len(sm.list_sessions()) == 2

    def test_list_sessions_metadata_keys(self, sm):
        s = sm.create_session()
        s.add_message("user", "hi")
        items = sm.list_sessions()
        meta = items[0]
        assert "id" in meta
        assert "message_count" in meta
        assert meta["message_count"] == 1


# ═══════════════════════════════════════════════════════════════
# SessionManager — Persistència
# ═══════════════════════════════════════════════════════════════

class TestSessionManagerPersistence:

    def test_session_saved_to_disk(self, tmp_path):
        sm1 = SessionManager(storage_path=str(tmp_path))
        s = sm1.create_session(session_id="persist-me")
        s.add_message("user", "hello")
        sm1._save_session_to_disk(s)  # persistència explícita

        sm2 = SessionManager(storage_path=str(tmp_path))
        loaded = sm2.get_session("persist-me")
        assert loaded is not None
        assert len(loaded.get_history()) == 1

    def test_delete_removes_disk_file(self, tmp_path):
        sm = SessionManager(storage_path=str(tmp_path))
        s = sm.create_session(session_id="bye")
        sm.delete_session("bye")

        sm2 = SessionManager(storage_path=str(tmp_path))
        assert sm2.get_session("bye") is None

    def test_loads_existing_sessions_on_init(self, tmp_path):
        sm1 = SessionManager(storage_path=str(tmp_path))
        sm1.create_session(session_id="s1")
        sm1.create_session(session_id="s2")

        sm2 = SessionManager(storage_path=str(tmp_path))
        assert sm2.get_session("s1") is not None
        assert sm2.get_session("s2") is not None


# ═══════════════════════════════════════════════════════════════
# SessionManager — Cleanup
# ═══════════════════════════════════════════════════════════════

class TestSessionManagerCleanup:

    def test_cleanup_removes_old_session(self, sm):
        s = sm.create_session()
        s.last_activity = datetime.now(timezone.utc) - timedelta(hours=25)
        removed = sm.cleanup_inactive(max_age_hours=24)
        assert removed == 1
        assert sm.get_session(s.id) is None

    def test_cleanup_keeps_recent_session(self, sm):
        sm.create_session()
        removed = sm.cleanup_inactive(max_age_hours=24)
        assert removed == 0

    def test_cleanup_mixed(self, sm):
        old = sm.create_session()
        old.last_activity = datetime.now(timezone.utc) - timedelta(hours=30)
        sm.create_session()  # Recent
        removed = sm.cleanup_inactive(max_age_hours=24)
        assert removed == 1

    def test_cleanup_empty_manager(self, sm):
        assert sm.cleanup_inactive(max_age_hours=24) == 0


# ═══════════════════════════════════════════════════════════════
# ChatSession — Compacting
# ═══════════════════════════════════════════════════════════════

class TestChatSessionCompacting:

    def _fill_session(self, s, n):
        """Omple sessió amb n missatges user/assistant alternats."""
        for i in range(n):
            role = "user" if i % 2 == 0 else "assistant"
            s.add_message(role, f"msg-{i}")

    def test_needs_compaction_false_when_few_messages(self):
        s = ChatSession()
        self._fill_session(s, 4)
        assert s.needs_compaction() is False

    def test_needs_compaction_true_at_threshold(self):
        s = ChatSession()
        self._fill_session(s, ChatSession.COMPACT_EVERY)
        assert s.needs_compaction() is True

    def test_needs_compaction_true_above_threshold(self):
        s = ChatSession()
        self._fill_session(s, ChatSession.COMPACT_EVERY + 4)
        assert s.needs_compaction() is True

    def test_get_messages_to_compact_empty_when_few(self):
        s = ChatSession()
        self._fill_session(s, 4)
        assert s.get_messages_to_compact() == []

    def test_get_messages_to_compact_returns_old_messages(self):
        s = ChatSession()
        self._fill_session(s, 12)
        to_compact = s.get_messages_to_compact()
        # 12 - COMPACT_KEEP(6) = 6 missatges a compactar
        assert len(to_compact) == 12 - ChatSession.COMPACT_KEEP
        assert to_compact[0]["content"] == "msg-0"

    def test_apply_compaction_keeps_recent(self):
        s = ChatSession()
        self._fill_session(s, 12)
        s.apply_compaction("Resum de la conversa sobre tests.")
        assert len(s.messages) == ChatSession.COMPACT_KEEP
        # Últim missatge hauria de ser msg-11
        assert s.messages[-1]["content"] == "msg-11"

    def test_apply_compaction_stores_summary(self):
        s = ChatSession()
        self._fill_session(s, 12)
        s.apply_compaction("Resum: parlàvem de testing.")
        assert s.context_summary == "Resum: parlàvem de testing."

    def test_apply_compaction_increments_count(self):
        s = ChatSession()
        self._fill_session(s, 12)
        assert s.compaction_count == 0
        s.apply_compaction("resum 1")
        assert s.compaction_count == 1
        # Afegir més missatges i compactar de nou
        self._fill_session(s, 10)
        s.apply_compaction("resum 2")
        assert s.compaction_count == 2

    def test_get_context_messages_without_summary(self):
        s = ChatSession()
        s.add_message("user", "hola")
        ctx = s.get_context_messages()
        assert len(ctx) == 1
        assert ctx[0]["content"] == "hola"

    def test_get_context_messages_with_summary(self):
        s = ChatSession()
        self._fill_session(s, 12)
        s.apply_compaction("Conversa sobre IA i models locals.")
        ctx = s.get_context_messages()
        # 2 missatges de resum + COMPACT_KEEP missatges recents
        assert len(ctx) == 2 + ChatSession.COMPACT_KEEP
        assert "[Resum de la conversa anterior]" in ctx[0]["content"]
        assert "Conversa sobre IA i models locals." in ctx[0]["content"]
        assert ctx[1]["role"] == "assistant"

    def test_compaction_survives_serialization(self, tmp_path):
        sm = SessionManager(storage_path=str(tmp_path))
        s = sm.create_session(session_id="compact-persist")
        self._fill_session(s, 12)
        s.apply_compaction("Resum persistent.")
        sm._save_session_to_disk(s)

        sm2 = SessionManager(storage_path=str(tmp_path))
        loaded = sm2.get_session("compact-persist")
        assert loaded.context_summary == "Resum persistent."
        assert loaded.compaction_count == 1
        assert len(loaded.messages) == ChatSession.COMPACT_KEEP

    def test_to_dict_includes_summary_when_present(self):
        s = ChatSession()
        self._fill_session(s, 12)
        s.apply_compaction("test summary")
        d = s.to_dict()
        assert d["context_summary"] == "test summary"
        assert d["compaction_count"] == 1

    def test_to_dict_excludes_summary_when_none(self):
        s = ChatSession()
        s.add_message("user", "hi")
        d = s.to_dict()
        assert "context_summary" not in d

    def test_multiple_compactions_accumulate(self):
        s = ChatSession()
        # Primera ronda
        self._fill_session(s, 12)
        s.apply_compaction("Resum 1: IA local")
        assert len(s.messages) == ChatSession.COMPACT_KEEP
        # Segona ronda
        self._fill_session(s, 10)
        s.apply_compaction("Resum 2: IA local + streaming")
        assert s.compaction_count == 2
        assert s.context_summary == "Resum 2: IA local + streaming"
        assert len(s.messages) == ChatSession.COMPACT_KEEP
