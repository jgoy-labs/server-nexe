"""
------------------------------------
Server Nexe
Author: Jordi Goy
Location: tests/plugins/web_ui_module/test_yield_atomize_save.py
Description: Unit tests for _yield_atomize_and_save_mem_saves (routes_chat.py).

www.jgoy.net · https://server-nexe.org
------------------------------------
"""

import pytest
from unittest.mock import AsyncMock, patch

MODULE = "plugins.web_ui_module.api.routes_chat"


class _FakeSession:
    """Minimal session stub — no MagicMock so getattr() behaves naturally."""

    def __init__(self, session_id="test-sess", deleted_facts=None):
        self.id = session_id
        if deleted_facts is not None:
            self._recently_deleted_facts = deleted_facts


async def _collect(gen):
    """Drain an async generator into a list."""
    items = []
    async for item in gen:
        items.append(item)
    return items


@pytest.fixture
def memory_helper():
    mh = AsyncMock()
    mh.save_to_memory = AsyncMock(return_value={"document_id": "doc-1"})
    return mh


@pytest.fixture
def engine():
    return AsyncMock()


def _passthrough_atomizer(f, *_a, **_kw):
    """Side-effect: return the fact unchanged (single-element list)."""
    return [f]


class TestAtomizeAndSave_HappyPath:

    @pytest.mark.asyncio
    async def test_three_facts_atomized_and_saved(self, engine, memory_helper):
        from plugins.web_ui_module.api.routes_chat import _yield_atomize_and_save_mem_saves

        mem_saves = ["fact one is here", "fact two is here", "fact three here"]
        session = _FakeSession()
        count_out = []

        with patch(f"{MODULE}._atomize_fact_llm", new_callable=AsyncMock) as mock_atom:
            mock_atom.side_effect = _passthrough_atomizer
            tokens = await _collect(_yield_atomize_and_save_mem_saves(
                mem_saves, engine, "model", None, "ca", memory_helper, session, count_out,
            ))

        assert tokens[0] == "\x00[SAVING]\x00"
        assert any("MEM:3" in t for t in tokens)
        assert count_out == [3]
        assert memory_helper.save_to_memory.call_count == 3


class TestAtomizeAndSave_EmptyInput:

    @pytest.mark.asyncio
    async def test_empty_list_no_mem_token(self, engine, memory_helper):
        from plugins.web_ui_module.api.routes_chat import _yield_atomize_and_save_mem_saves

        mem_saves = []
        session = _FakeSession()
        count_out = []

        with patch(f"{MODULE}._atomize_fact_llm", new_callable=AsyncMock):
            tokens = await _collect(_yield_atomize_and_save_mem_saves(
                mem_saves, engine, "model", None, "ca", memory_helper, session, count_out,
            ))

        assert tokens == ["\x00[SAVING]\x00"]
        assert count_out == [0]


class TestAtomizeAndSave_DeletedFactsFiltered:

    @pytest.mark.asyncio
    async def test_recently_deleted_facts_skipped(self, engine, memory_helper):
        from plugins.web_ui_module.api.routes_chat import _yield_atomize_and_save_mem_saves

        mem_saves = ["I like pizza"]
        # fact.lower() in del.lower() → "i like pizza" in "i like pizza very much" → True
        session = _FakeSession(deleted_facts=["I like pizza very much"])
        count_out = []

        with patch(f"{MODULE}._atomize_fact_llm", new_callable=AsyncMock) as mock_atom:
            mock_atom.side_effect = _passthrough_atomizer
            tokens = await _collect(_yield_atomize_and_save_mem_saves(
                mem_saves, engine, "model", None, "ca", memory_helper, session, count_out,
            ))

        assert count_out == [0]
        memory_helper.save_to_memory.assert_not_called()


class TestAtomizeAndSave_JunkFiltered:

    @pytest.mark.asyncio
    async def test_junk_patterns_skipped(self, engine, memory_helper):
        from plugins.web_ui_module.api.routes_chat import _yield_atomize_and_save_mem_saves

        # "no coneix" matches _JUNK_PATTERNS_RE
        mem_saves = ["no coneix cap dada rellevant"]
        session = _FakeSession()
        count_out = []

        with patch(f"{MODULE}._atomize_fact_llm", new_callable=AsyncMock) as mock_atom:
            mock_atom.side_effect = _passthrough_atomizer
            tokens = await _collect(_yield_atomize_and_save_mem_saves(
                mem_saves, engine, "model", None, "ca", memory_helper, session, count_out,
            ))

        assert count_out == [0]
        memory_helper.save_to_memory.assert_not_called()


class TestAtomizeAndSave_ShortFactsSkipped:

    @pytest.mark.asyncio
    async def test_short_facts_below_5_chars_skipped(self, engine, memory_helper):
        from plugins.web_ui_module.api.routes_chat import _yield_atomize_and_save_mem_saves

        mem_saves = ["hi", "ok!", "ab"]
        session = _FakeSession()
        count_out = []

        with patch(f"{MODULE}._atomize_fact_llm", new_callable=AsyncMock) as mock_atom:
            mock_atom.side_effect = _passthrough_atomizer
            tokens = await _collect(_yield_atomize_and_save_mem_saves(
                mem_saves, engine, "model", None, "ca", memory_helper, session, count_out,
            ))

        assert count_out == [0]
        memory_helper.save_to_memory.assert_not_called()


class TestAtomizeAndSave_AtomizeLLMFailure:

    @pytest.mark.asyncio
    async def test_atomize_failure_falls_back_to_raw(self, engine, memory_helper):
        from plugins.web_ui_module.api.routes_chat import _yield_atomize_and_save_mem_saves

        mem_saves = ["I like cats and dogs very much"]
        session = _FakeSession()
        count_out = []

        with patch(f"{MODULE}._atomize_fact_llm", new_callable=AsyncMock) as mock_atom:
            mock_atom.side_effect = RuntimeError("LLM failed")
            tokens = await _collect(_yield_atomize_and_save_mem_saves(
                mem_saves, engine, "model", None, "ca", memory_helper, session, count_out,
            ))

        # Falls back to raw fact → saved
        assert count_out == [1]
        memory_helper.save_to_memory.assert_called_once()


class TestAtomizeAndSave_SaveFailure:

    @pytest.mark.asyncio
    async def test_save_failure_does_not_increment_count(self, engine):
        from plugins.web_ui_module.api.routes_chat import _yield_atomize_and_save_mem_saves

        memory_helper = AsyncMock()
        memory_helper.save_to_memory = AsyncMock(side_effect=RuntimeError("DB error"))

        mem_saves = ["valid fact here for testing"]
        session = _FakeSession()
        count_out = []

        with patch(f"{MODULE}._atomize_fact_llm", new_callable=AsyncMock) as mock_atom:
            mock_atom.side_effect = _passthrough_atomizer
            tokens = await _collect(_yield_atomize_and_save_mem_saves(
                mem_saves, engine, "model", None, "ca", memory_helper, session, count_out,
            ))

        assert count_out == [0]
        assert not any("MEM:" in t for t in tokens)


class TestAtomizeAndSave_DedupSkipped:

    @pytest.mark.asyncio
    async def test_no_document_id_does_not_count(self, engine):
        from plugins.web_ui_module.api.routes_chat import _yield_atomize_and_save_mem_saves

        memory_helper = AsyncMock()
        memory_helper.save_to_memory = AsyncMock(return_value={"dedup": True})

        mem_saves = ["valid fact dedup testing"]
        session = _FakeSession()
        count_out = []

        with patch(f"{MODULE}._atomize_fact_llm", new_callable=AsyncMock) as mock_atom:
            mock_atom.side_effect = _passthrough_atomizer
            tokens = await _collect(_yield_atomize_and_save_mem_saves(
                mem_saves, engine, "model", None, "ca", memory_helper, session, count_out,
            ))

        assert count_out == [0]
        assert not any("MEM:" in t for t in tokens)


class TestAtomizeAndSave_MutatesMemSaves:

    @pytest.mark.asyncio
    async def test_mem_saves_list_mutated_to_atomized(self, engine, memory_helper):
        from plugins.web_ui_module.api.routes_chat import _yield_atomize_and_save_mem_saves

        mem_saves = ["cats and dogs combined"]
        session = _FakeSession()
        count_out = []

        with patch(f"{MODULE}._atomize_fact_llm", new_callable=AsyncMock) as mock_atom:
            mock_atom.side_effect = lambda f, *a, **kw: ["likes cats a lot", "likes dogs a lot"]
            await _collect(_yield_atomize_and_save_mem_saves(
                mem_saves, engine, "model", None, "ca", memory_helper, session, count_out,
            ))

        # mem_saves[:] = _atomized mutates the original list
        assert mem_saves == ["likes cats a lot", "likes dogs a lot"]
