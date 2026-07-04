"""
------------------------------------
Server Nexe
Author: Jordi Goy
Location: tests/plugins/web_ui_module/test_yield_atomize_save.py
Description: Unit tests for _yield_atomize_and_save_mem_saves (routes_chat.py).

www.jgoy.net · https://server-nexe.org
------------------------------------
"""

import inspect

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


class TestFilterFactsPersonalDataHallucination:
    """B126 v2: el guard de noms és CONTEXTUAL — un nom fabricat (que l'usuari
    mai ha escrit) es descarta; un nom real (present als missatges user de la
    sessió) es desa. La v1 (prohibició cega) matava la frase canònica que el
    system prompt ensenya i cap nom real es desava mai (bug 2026-07-03)."""

    def test_fabricated_names_filtered_without_user_context(self):
        from plugins.web_ui_module.api.routes_chat import _filter_facts

        hallucinations = [
            "el usuario se llama Juan",
            "the user's name is Alice",
            "l'usuari es diu Carles",
            "se llama Pedro y vive en Madrid",
        ]
        # Cap dels noms apareix als missatges de l'usuari → tots fora.
        assert _filter_facts(hallucinations, [], user_text="hola, com va?") == []

    def test_real_name_survives_with_user_context(self):
        from plugins.web_ui_module.api.routes_chat import _filter_facts

        fact = "el usuario se llama Juan"
        kept = _filter_facts([fact], [], user_text="me llamo Juan y tengo 40 años")
        assert kept == [fact]

    def test_legitimate_non_name_fact_survives(self):
        """Don't over-filter: a real preference (without a name) is preserved."""
        from plugins.web_ui_module.api.routes_chat import _filter_facts

        facts = ["a l'usuari li agrada molt el cafè amb llet"]
        assert _filter_facts(facts, []) == facts


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


class TestAtomizeFactLLM_MLXEngine:
    """B088: the LLM atomizer must work with MLX (chat = async def → a coroutine
    that returns a dict), not only with Ollama (chat sync → async-generator)."""

    @pytest.mark.asyncio
    async def test_mlx_async_chat_atomizes_via_llm(self):
        # MLX: chat is 'async def' -> calling it returns a coroutine, and
        # execute() returns a dict {"response": text}. There is NO streaming
        # without stream_callback (which the atomizer doesn't pass).
        from plugins.web_ui_module.api.routes_chat import _atomize_fact_llm

        class _MLXEngine:
            # MLX-style signature: it does NOT have the 'model' parameter -> else branch
            async def chat(self, messages, stream=True, thinking_enabled=False, **kw):
                return {"response": "L'usuari es diu Aran\nL'usuari té 8 anys"}

        engine = _MLXEngine()
        sig = inspect.signature(engine.chat)  # 'model' is NOT there -> MLX branch

        fact = "L'usuari es diu Aran i té 8 anys"  # contains ' i ' -> passes the guard
        parts = await _atomize_fact_llm(fact, engine, "mlx-model", sig, lang="ca")

        # Current RED: parts == [fact] (1 element, not atomized).
        # GREEN with fix: 2 atomic facts extracted from the dict.
        assert parts == ["L'usuari es diu Aran", "L'usuari té 8 anys"]
        assert len(parts) == 2

    @pytest.mark.asyncio
    async def test_ollama_async_gen_chat_still_works(self):
        # No-regressió: Ollama chat és SYNC i retorna un async-generator.
        from plugins.web_ui_module.api.routes_chat import _atomize_fact_llm

        async def _agen(*_a, **_kw):
            for line in ("L'usuari es diu Aran\n", "L'usuari té 8 anys\n"):
                yield {"message": {"content": line}}

        class _OllamaEngine:
            def chat(self, model, messages, stream=True, images=None, thinking_enabled=False):
                return _agen()

        engine = _OllamaEngine()
        sig = inspect.signature(engine.chat)  # 'model' hi és -> branca Ollama
        fact = "L'usuari es diu Aran i té 8 anys"
        parts = await _atomize_fact_llm(fact, engine, "ollama-model", sig, lang="ca")
        assert parts == ["L'usuari es diu Aran", "L'usuari té 8 anys"]
