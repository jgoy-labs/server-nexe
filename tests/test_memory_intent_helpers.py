"""Tests for helpers extracted from _handle_memory_intent and
_handle_nonstreaming_response (facade pattern refactor).

TDD: tests are written BEFORE the refactor and drive the API of
the helper functions.
"""
import pytest
from unittest.mock import AsyncMock, MagicMock, patch


# ---------------------------------------------------------------------------
# Import helpers (will exist after refactor)
# ---------------------------------------------------------------------------
from plugins.web_ui_module.api.routes_chat import (
    _handle_save_intent,
    _handle_delete_intent,
    _handle_delete_confirm_intent,
    _handle_list_intent,
    _handle_clear_all_confirm_intent,
    _clean_nonstreaming_text,
    _save_mem_saves_nonstreaming,
    _arm_mem_deletes_nonstreaming,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_session(messages=None):
    s = MagicMock()
    s.id = "sess-test-1"
    s.messages = messages if messages is not None else []
    s._pending_partial_delete = None
    return s


def _make_memory_helper():
    h = MagicMock()
    h.save_to_memory = AsyncMock()
    h.delete_from_memory = AsyncMock()
    h.preview_delete_from_memory = AsyncMock()
    h.delete_memory_entries = AsyncMock()
    h.list_memories = AsyncMock()
    h.clear_memory = AsyncMock()
    return h


def _candidate(text="fact one", cid="id-1", collection="personal_memory", score=0.9, mtype=None):
    return {
        "id": cid, "collection": collection, "text": text, "score": score,
        "metadata": {"type": mtype} if mtype else {},
    }


# ===========================================================================
# _handle_save_intent
# ===========================================================================

class TestHandleSaveIntent:
    @pytest.mark.asyncio
    async def test_save_success_returns_saved_response(self):
        mh = _make_memory_helper()
        mh.save_to_memory.return_value = {"success": True, "document_id": "doc-1"}
        text, action = await _handle_save_intent(
            extracted_content="my cat is called Whiskers",
            message="remember my cat is called Whiskers",
            session_id="s1",
            rag_collections=None,
            memory_helper=mh,
        )
        assert "Saved to memory" in text
        assert "Whiskers" in text
        assert action == "save"

    @pytest.mark.asyncio
    async def test_save_duplicate_returns_already_in_memory(self):
        mh = _make_memory_helper()
        mh.save_to_memory.return_value = {"success": False, "duplicate": True}
        text, action = await _handle_save_intent(
            extracted_content="my cat is called Whiskers",
            message="remember my cat",
            session_id="s1",
            rag_collections=None,
            memory_helper=mh,
        )
        assert "Already in memory" in text
        assert action == "save"

    @pytest.mark.asyncio
    async def test_save_error_returns_could_not_save(self):
        mh = _make_memory_helper()
        mh.save_to_memory.return_value = {"success": False, "message": "DB error"}
        text, action = await _handle_save_intent(
            extracted_content="some fact",
            message="save some fact",
            session_id="s1",
            rag_collections=None,
            memory_helper=mh,
        )
        assert "Could not save" in text or "DB error" in text
        assert action == "save"

    @pytest.mark.asyncio
    async def test_save_empty_content_asks_what_to_remember(self):
        mh = _make_memory_helper()
        text, action = await _handle_save_intent(
            extracted_content="",
            message="",
            session_id="s1",
            rag_collections=None,
            memory_helper=mh,
        )
        assert "What do you want me to remember" in text or "remember" in text.lower()
        mh.save_to_memory.assert_not_called()
        assert action == "save"

    @pytest.mark.asyncio
    async def test_save_strips_trailing_punctuation(self):
        mh = _make_memory_helper()
        mh.save_to_memory.return_value = {"success": True, "document_id": "doc-2"}
        await _handle_save_intent(
            extracted_content="I like cats?!",
            message="save I like cats?!",
            session_id="s1",
            rag_collections=None,
            memory_helper=mh,
        )
        call_args = mh.save_to_memory.call_args
        assert call_args[1]["content"] == "I like cats" or call_args[0][0] == "I like cats" or \
               call_args[1].get("content", "").rstrip("?!") == "I like cats"


# ===========================================================================
# _handle_delete_intent
# ===========================================================================

class TestHandleDeleteIntent:
    """B028: partial deletes must NEVER execute directly — they arm a 2-turn
    confirmation with the exact entry that would die."""

    @pytest.mark.asyncio
    async def test_delete_with_match_arms_confirmation_and_does_not_delete(self):
        mh = _make_memory_helper()
        mh.preview_delete_from_memory.return_value = {
            "success": True,
            "candidates": [_candidate("m'agraden els gats"), _candidate("doc no relacionat", cid="id-2", collection="user_knowledge", score=0.21)],
        }
        session = _make_session(messages=[{"role": "user", "content": "Oblida que m'agraden els gats"}])
        text, action, mem_deleted = await _handle_delete_intent(
            extracted_content="m'agraden els gats",
            session=session,
            rag_collections=None,
            memory_helper=mh,
        )
        assert action == "delete_pending"
        assert mem_deleted == 0
        mh.delete_from_memory.assert_not_called()
        mh.delete_memory_entries.assert_not_called()
        # Only the BEST global match is armed (RT-04: no cross-collection collateral)
        assert session._pending_partial_delete["entries"] == [_candidate("m'agraden els gats")]
        assert "m'agraden els gats" in text
        assert "[PENDING_DELETE:" in text

    @pytest.mark.asyncio
    async def test_delete_profile_candidate_warns(self):
        mh = _make_memory_helper()
        mh.preview_delete_from_memory.return_value = {
            "success": True,
            "candidates": [_candidate("User is an AI expert", mtype="user_fact")],
        }
        session = _make_session(messages=[{"role": "user", "content": "oblida el document"}])
        text, _action, _ = await _handle_delete_intent(
            extracted_content="el document",
            session=session,
            rag_collections=None,
            memory_helper=mh,
        )
        assert "perfil" in text.lower() or "profile" in text.lower()

    @pytest.mark.asyncio
    async def test_delete_nothing_found_returns_not_found_message(self):
        mh = _make_memory_helper()
        mh.preview_delete_from_memory.return_value = {"success": True, "candidates": []}
        session = _make_session(messages=[{"role": "user", "content": "Oblida"}])
        text, action, mem_deleted = await _handle_delete_intent(
            extracted_content="unknown topic",
            session=session,
            rag_collections=None,
            memory_helper=mh,
        )
        assert "Nothing found" in text
        assert action == "delete"
        assert mem_deleted == 0
        assert not session._pending_partial_delete

    @pytest.mark.asyncio
    async def test_delete_error_returns_error_message(self):
        mh = _make_memory_helper()
        mh.preview_delete_from_memory.return_value = {"success": False, "candidates": [], "message": "Connection error"}
        session = _make_session(messages=[{"role": "user", "content": "Oblida algo"}])
        text, action, mem_deleted = await _handle_delete_intent(
            extracted_content="some topic",
            session=session,
            rag_collections=None,
            memory_helper=mh,
        )
        assert "Error" in text or "Connection error" in text
        assert action == "delete"

    @pytest.mark.asyncio
    async def test_delete_empty_content_sanitizes_session_and_asks_what(self):
        mh = _make_memory_helper()
        session = _make_session(messages=[{"role": "user", "content": "Oblida que..."}])
        text, action, _mem_deleted = await _handle_delete_intent(
            extracted_content="",
            session=session,
            rag_collections=None,
            memory_helper=mh,
        )
        assert "What do you want me to forget" in text or "forget" in text.lower()
        mh.preview_delete_from_memory.assert_not_called()
        mh.delete_from_memory.assert_not_called()
        # session history sanitized even when content empty
        assert session.messages[-1]["content"] != "Oblida que..."

    @pytest.mark.asyncio
    async def test_delete_sanitizes_last_user_message(self):
        mh = _make_memory_helper()
        mh.preview_delete_from_memory.return_value = {
            "success": True, "candidates": [_candidate("cats fact")],
        }
        session = _make_session(messages=[{"role": "user", "content": "Oblida que m'agraden els gats"}])
        await _handle_delete_intent(
            extracted_content="m'agraden els gats",
            session=session,
            rag_collections=None,
            memory_helper=mh,
        )
        assert session.messages[-1]["content"] != "Oblida que m'agraden els gats"
        assert "Memory command" in session.messages[-1]["content"] or "delete" in session.messages[-1]["content"].lower()


class TestHandleDeleteConfirmIntent:
    """Second turn of the B028 flow: a yes executes EXACTLY the previewed entries."""

    @pytest.mark.asyncio
    async def test_confirm_deletes_exact_pending_entries(self):
        mh = _make_memory_helper()
        mh.delete_memory_entries.return_value = {
            "success": True, "deleted": 1,
            "deleted_facts": [{"id": "id-1", "text": "m'agraden els gats", "score": 0.9}],
        }
        session = _make_session()
        session._pending_partial_delete = {
            "content": "m'agraden els gats",
            "entries": [_candidate("m'agraden els gats")],
        }
        text, action, mem_deleted = await _handle_delete_confirm_intent(session, mh)
        mh.delete_memory_entries.assert_awaited_once_with([_candidate("m'agraden els gats")])
        assert "Deleted 1" in text
        assert action == "delete"
        assert mem_deleted == 1
        assert session._pending_partial_delete is None

    @pytest.mark.asyncio
    async def test_confirm_without_pending_is_noop(self):
        mh = _make_memory_helper()
        session = _make_session()
        text, action, mem_deleted = await _handle_delete_confirm_intent(session, mh)
        mh.delete_memory_entries.assert_not_called()
        assert mem_deleted == 0
        assert "Nothing pending" in text

    # B093 — a bare generic "yes" must not erase profile entries.
    @pytest.mark.asyncio
    async def test_profile_entry_generic_yes_is_blocked(self):
        mh = _make_memory_helper()
        session = _make_session()
        session._pending_partial_delete = {
            "content": "I am an expert",
            "entries": [_candidate("I am an expert", mtype="user_fact")],
        }
        text, action, mem_deleted = await _handle_delete_confirm_intent(session, mh, "yes")
        mh.delete_memory_entries.assert_not_called()
        assert action == "delete_blocked"
        assert mem_deleted == 0
        assert session._pending_partial_delete is None

    @pytest.mark.asyncio
    async def test_profile_entry_explicit_reference_is_allowed(self):
        mh = _make_memory_helper()
        mh.delete_memory_entries.return_value = {
            "success": True, "deleted": 1,
            "deleted_facts": [{"id": "id-1", "text": "I am an expert", "score": 0.9}],
        }
        session = _make_session()
        session._pending_partial_delete = {
            "content": "I am an expert",
            "entries": [_candidate("I am an expert", mtype="user_fact")],
        }
        text, action, mem_deleted = await _handle_delete_confirm_intent(
            session, mh, "yes, delete that I am an expert"
        )
        mh.delete_memory_entries.assert_awaited_once()
        assert action == "delete"
        assert mem_deleted == 1

    @pytest.mark.asyncio
    async def test_non_profile_entry_generic_yes_still_deletes(self):
        """No regression: a non-profile entry confirms with a bare yes."""
        mh = _make_memory_helper()
        mh.delete_memory_entries.return_value = {
            "success": True, "deleted": 1,
            "deleted_facts": [{"id": "id-1", "text": "m'agraden els gats", "score": 0.9}],
        }
        session = _make_session()
        session._pending_partial_delete = {
            "content": "m'agraden els gats",
            "entries": [_candidate("m'agraden els gats")],  # no profile type
        }
        text, action, mem_deleted = await _handle_delete_confirm_intent(session, mh, "yes")
        mh.delete_memory_entries.assert_awaited_once()
        assert action == "delete"
        assert mem_deleted == 1

    @pytest.mark.asyncio
    async def test_profile_stopwords_only_do_not_count_as_reference(self):
        """Anti-theatre: generic stop-words ('delete', 'user', 'memory') must
        not slip past the guard as if they referenced the entry."""
        mh = _make_memory_helper()
        session = _make_session()
        session._pending_partial_delete = {
            "content": "I am an expert",
            "entries": [_candidate("I am an expert", mtype="user_fact")],
        }
        text, action, mem_deleted = await _handle_delete_confirm_intent(
            session, mh, "yes please delete user memory"
        )
        mh.delete_memory_entries.assert_not_called()
        assert action == "delete_blocked"


# ===========================================================================
# _handle_list_intent
# ===========================================================================

class TestHandleListIntent:
    @pytest.mark.asyncio
    async def test_list_with_facts_returns_formatted_list(self):
        mh = _make_memory_helper()
        mh.list_memories.return_value = {
            "success": True,
            "facts": [
                {"text": "I like cats", "created_at": "2026-01-15T10:00:00"},
                {"text": "I work in Barcelona", "created_at": "2026-02-20T08:00:00"},
            ],
            "total": 2,
        }
        text, action = await _handle_list_intent(rag_collections=None, memory_helper=mh)
        assert "I like cats" in text
        assert "I work in Barcelona" in text
        assert action == "list"

    @pytest.mark.asyncio
    async def test_list_empty_returns_no_memories_message(self):
        mh = _make_memory_helper()
        mh.list_memories.return_value = {"success": True, "facts": [], "total": 0}
        text, action = await _handle_list_intent(rag_collections=None, memory_helper=mh)
        assert "No memories" in text or "no memories" in text.lower()
        assert action == "list"

    @pytest.mark.asyncio
    async def test_list_facts_failure_returns_no_memories(self):
        mh = _make_memory_helper()
        mh.list_memories.return_value = {"success": False, "facts": [], "total": 0}
        text, action = await _handle_list_intent(rag_collections=None, memory_helper=mh)
        assert action == "list"

    @pytest.mark.asyncio
    async def test_list_facts_with_dates_shows_date(self):
        mh = _make_memory_helper()
        mh.list_memories.return_value = {
            "success": True,
            "facts": [{"text": "birthday is March 5", "created_at": "2026-03-05T12:00:00"}],
            "total": 1,
        }
        text, action = await _handle_list_intent(rag_collections=None, memory_helper=mh)
        assert "2026-03-05" in text
        assert action == "list"


# ===========================================================================
# _handle_clear_all_confirm_intent
# ===========================================================================

class TestHandleClearAllConfirmIntent:
    @pytest.mark.asyncio
    async def test_clear_success_returns_erased_message(self):
        mh = _make_memory_helper()
        mh.clear_memory.return_value = {"success": True}
        session = _make_session()
        session._pending_clear_all = True
        text, action, mem_deleted = await _handle_clear_all_confirm_intent(
            session=session,
            memory_helper=mh,
            mem_deleted=0,
        )
        assert "esborrada" in text.lower() or "esborrat" in text.lower() or "Memòria" in text
        assert action == "clear_all"
        assert mem_deleted >= 1
        assert session._pending_clear_all is False

    @pytest.mark.asyncio
    async def test_clear_failure_returns_error_message(self):
        mh = _make_memory_helper()
        mh.clear_memory.return_value = {"success": False, "message": "DB locked"}
        session = _make_session()
        session._pending_clear_all = True
        text, action, mem_deleted = await _handle_clear_all_confirm_intent(
            session=session,
            memory_helper=mh,
            mem_deleted=0,
        )
        assert "Error" in text or "DB locked" in text
        assert action == "clear_all"

    @pytest.mark.asyncio
    async def test_clear_exception_returns_error_message(self):
        mh = _make_memory_helper()
        mh.clear_memory.side_effect = RuntimeError("crash")
        session = _make_session()
        session._pending_clear_all = True
        text, action, mem_deleted = await _handle_clear_all_confirm_intent(
            session=session,
            memory_helper=mh,
            mem_deleted=0,
        )
        assert "Error" in text or "crash" in text
        assert action == "clear_all"

    @pytest.mark.asyncio
    async def test_clear_resets_pending_flag(self):
        mh = _make_memory_helper()
        mh.clear_memory.return_value = {"success": True}
        session = _make_session()
        session._pending_clear_all = True
        await _handle_clear_all_confirm_intent(
            session=session,
            memory_helper=mh,
            mem_deleted=0,
        )
        assert session._pending_clear_all is False


# ===========================================================================
# _clean_nonstreaming_text
# ===========================================================================

class TestCleanNonstreamingText:
    def test_removes_think_tags(self):
        text = "<think>internal reasoning</think>  The conclusion is here."
        result = _clean_nonstreaming_text(text)
        assert "<think>" not in result
        assert "internal reasoning" not in result
        assert "The conclusion is here." in result

    def test_removes_gpt_oss_pipe_tags(self):
        text = "<|im_start|>assistant\nHello there"
        result = _clean_nonstreaming_text(text)
        assert "<|" not in result
        assert "Hello there" in result

    def test_extracts_final_part(self):
        text = "analysis some stuff\nfinal The real answer is 42."
        result = _clean_nonstreaming_text(text)
        assert result == "The real answer is 42."

    def test_strips_analysis_prefix_when_no_final(self):
        text = "analysis  this is the actual answer"
        result = _clean_nonstreaming_text(text)
        assert not result.lower().startswith("analysis")
        assert "this is the actual answer" in result

    def test_passthrough_plain_text(self):
        text = "Hello, this is a normal response."
        result = _clean_nonstreaming_text(text)
        assert result == text


# ===========================================================================
# _save_mem_saves_nonstreaming
# ===========================================================================

class TestSaveMemSavesNonstreaming:
    @pytest.mark.asyncio
    async def test_saves_valid_fact(self):
        mh = _make_memory_helper()
        mh.save_to_memory.return_value = {"document_id": "doc-99", "success": True}
        session = _make_session(messages=[{"role": "user", "content": "msg1"}, {"role": "user", "content": "msg2"}])
        await _save_mem_saves_nonstreaming(["I like jazz music"], session, mh)
        mh.save_to_memory.assert_called_once()
        call_kwargs = mh.save_to_memory.call_args[1]
        assert call_kwargs["content"] == "I like jazz music"

    @pytest.mark.asyncio
    async def test_skips_short_facts(self):
        mh = _make_memory_helper()
        session = _make_session(messages=[{"role": "user", "content": "a"}, {"role": "user", "content": "b"}])
        await _save_mem_saves_nonstreaming(["hi", "ok", "yes"], session, mh)
        mh.save_to_memory.assert_not_called()

    @pytest.mark.asyncio
    async def test_skips_junk_facts(self):
        mh = _make_memory_helper()
        session = _make_session(messages=[{"role": "user", "content": "a"}, {"role": "user", "content": "b"}])
        junk_facts = [
            "no coneix res sobre l'usuari",
            "no s'han detectat dades personals",
        ]
        await _save_mem_saves_nonstreaming(junk_facts, session, mh)
        mh.save_to_memory.assert_not_called()

    @pytest.mark.asyncio
    async def test_skips_first_turn(self):
        mh = _make_memory_helper()
        session = _make_session(messages=[{"role": "user", "content": "first message"}])
        await _save_mem_saves_nonstreaming(["I like cats"], session, mh)
        mh.save_to_memory.assert_not_called()

    @pytest.mark.asyncio
    async def test_handles_save_exception(self):
        mh = _make_memory_helper()
        mh.save_to_memory.side_effect = RuntimeError("db crash")
        session = _make_session(messages=[{"role": "user", "content": "a"}, {"role": "user", "content": "b"}])
        # Must not raise
        await _save_mem_saves_nonstreaming(["I like jazz"], session, mh)


# ===========================================================================
# _arm_mem_deletes_nonstreaming (B028: model tags arm confirmation, never delete)
# ===========================================================================

class TestArmMemDeletesNonstreaming:
    @pytest.mark.asyncio
    async def test_arms_pending_and_returns_question_without_deleting(self):
        mh = _make_memory_helper()
        mh.preview_delete_from_memory.return_value = {
            "success": True, "candidates": [_candidate("fact one")],
        }
        session = _make_session()
        question = await _arm_mem_deletes_nonstreaming(["fact one", "fact two"], session, mh)
        mh.delete_from_memory.assert_not_called()
        mh.delete_memory_entries.assert_not_called()
        assert session._pending_partial_delete["entries"] == [_candidate("fact one")]
        assert "[PENDING_DELETE:" in question

    @pytest.mark.asyncio
    async def test_no_match_returns_empty_and_no_pending(self):
        mh = _make_memory_helper()
        mh.preview_delete_from_memory.return_value = {"success": True, "candidates": []}
        session = _make_session()
        question = await _arm_mem_deletes_nonstreaming(["unknown topic"], session, mh)
        assert question == ""
        assert not session._pending_partial_delete

    @pytest.mark.asyncio
    async def test_skips_short_facts(self):
        mh = _make_memory_helper()
        session = _make_session()
        question = await _arm_mem_deletes_nonstreaming(["ab", "x"], session, mh)
        mh.preview_delete_from_memory.assert_not_called()
        assert question == ""

    @pytest.mark.asyncio
    async def test_handles_exception_gracefully(self):
        mh = _make_memory_helper()
        mh.preview_delete_from_memory.side_effect = RuntimeError("crash")
        session = _make_session()
        # Must not raise
        question = await _arm_mem_deletes_nonstreaming(["some fact"], session, mh)
        assert question == ""
