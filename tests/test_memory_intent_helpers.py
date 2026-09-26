"""Tests for the non-streaming helpers of the UI door.

The memory-intent handlers these used to sit beside moved to the core in C3.1
(tests/core/memory_facts/test_intents.py); the arming of a model's
[MEM_DELETE:] followed at C4.5 (tests/core/memory_facts/test_deletes.py).
What stays here belongs to memory.write and the cleaner.
"""
import pytest
from unittest.mock import AsyncMock, MagicMock, patch


# ---------------------------------------------------------------------------
# Import helpers (will exist after refactor)
# ---------------------------------------------------------------------------
from core.memory_facts.write import write_facts
# C4.4: the non-streaming cleaner is the core's one cleaner now.
from core.turn.text.clean import clean_model_text as _clean_nonstreaming_text


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
# write_facts — C3.3: the same code both doors now run
# ===========================================================================

class TestWriteFacts:
    @pytest.mark.asyncio
    async def test_saves_valid_fact(self):
        mh = _make_memory_helper()
        mh.save_to_memory.return_value = {"document_id": "doc-99", "success": True}
        session = _make_session(messages=[{"role": "user", "content": "msg1"}, {"role": "user", "content": "msg2"}])
        await write_facts(["I like jazz music"], session, mh)
        mh.save_to_memory.assert_called_once()
        call_kwargs = mh.save_to_memory.call_args[1]
        assert call_kwargs["content"] == "I like jazz music"

    @pytest.mark.asyncio
    async def test_skips_short_facts(self):
        mh = _make_memory_helper()
        session = _make_session(messages=[{"role": "user", "content": "a"}, {"role": "user", "content": "b"}])
        await write_facts(["hi", "ok", "yes"], session, mh)
        mh.save_to_memory.assert_not_called()

    @pytest.mark.asyncio
    async def test_skips_junk_facts(self):
        mh = _make_memory_helper()
        session = _make_session(messages=[{"role": "user", "content": "a"}, {"role": "user", "content": "b"}])
        junk_facts = [
            "no coneix res sobre l'usuari",
            "no s'han detectat dades personals",
        ]
        await write_facts(junk_facts, session, mh)
        mh.save_to_memory.assert_not_called()

    @pytest.mark.asyncio
    async def test_skips_first_turn(self):
        mh = _make_memory_helper()
        session = _make_session(messages=[{"role": "user", "content": "first message"}])
        await write_facts(["I like cats"], session, mh)
        mh.save_to_memory.assert_not_called()

    @pytest.mark.asyncio
    async def test_handles_save_exception(self):
        mh = _make_memory_helper()
        mh.save_to_memory.side_effect = RuntimeError("db crash")
        session = _make_session(messages=[{"role": "user", "content": "a"}, {"role": "user", "content": "b"}])
        # Must not raise
        await write_facts(["I like jazz"], session, mh)
