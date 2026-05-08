"""TDD per al refactor de generate_rag_metadata (CCN 28 → ≤8).

Cobreix: _fallback_metadata, _parse_llm_metadata_response,
         _get_engine_instance, _collect_stream_response,
         _call_llm_for_metadata, _try_engines, generate_rag_metadata.
"""

import inspect
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from plugins.web_ui_module.core.rag_handler import (
    _call_llm_for_metadata,
    _collect_stream_response,
    _fallback_metadata,
    _get_engine_instance,
    _parse_llm_metadata_response,
    _try_engines,
    generate_rag_metadata,
)


# ─── _fallback_metadata ──────────────────────────────────────────────────────

class TestFallbackMetadata:
    def test_returns_all_required_fields(self):
        result = _fallback_metadata("contingut del doc", "nom_stem", "ca")
        assert set(result) == {"abstract", "tags", "priority", "type", "lang"}

    def test_abstract_is_first_300_chars_of_normalized_content(self):
        long_text = "paraula " * 200
        result = _fallback_metadata(long_text, "stem", "ca")
        assert len(result["abstract"]) <= 300

    def test_tags_contains_stem(self):
        result = _fallback_metadata("text", "el meu document", "ca")
        assert result["tags"] == ["el meu document"]

    def test_lang_is_propagated(self):
        result = _fallback_metadata("text", "stem", "es")
        assert result["lang"] == "es"

    def test_priority_and_type_fixed(self):
        result = _fallback_metadata("text", "stem", "en")
        assert result["priority"] == "P2"
        assert result["type"] == "docs"

    def test_short_content_not_truncated(self):
        result = _fallback_metadata("breu", "stem", "ca")
        assert result["abstract"] == "breu"


# ─── _parse_llm_metadata_response ────────────────────────────────────────────

class TestParseLlmMetadataResponse:
    def test_parses_abstract_and_tags(self):
        text = "abstract: Descripció del document\ntags: [python, test, ci]"
        abstract, tags = _parse_llm_metadata_response(text, "stem")
        assert abstract == "Descripció del document"
        assert tags == ["python", "test", "ci"]

    def test_no_abstract_line_returns_empty(self):
        text = "tags: [python, test]"
        abstract, tags = _parse_llm_metadata_response(text, "stem")
        assert abstract == ""

    def test_no_tags_line_returns_stem(self):
        text = "abstract: El document parla de Python"
        abstract, tags = _parse_llm_metadata_response(text, "el meu stem")
        assert tags == ["el meu stem"]

    def test_strips_quotes_from_abstract(self):
        text = "abstract: \"Entre cometes\""
        abstract, _ = _parse_llm_metadata_response(text, "s")
        assert abstract == "Entre cometes"

    def test_tags_limited_to_six(self):
        text = "abstract: x\ntags: [a, b, c, d, e, f, g, h]"
        _, tags = _parse_llm_metadata_response(text, "s")
        assert len(tags) <= 6

    def test_abstract_limited_to_400_chars(self):
        long_abstract = "A" * 500
        text = f"abstract: {long_abstract}"
        abstract, _ = _parse_llm_metadata_response(text, "s")
        assert len(abstract) <= 400

    def test_strips_think_tags(self):
        text = "<think>raonament intern</think>\nabstract: Net\ntags: [ok]"
        abstract, tags = _parse_llm_metadata_response(text, "s")
        assert abstract == "Net"
        assert tags == ["ok"]

    def test_case_insensitive_keys(self):
        text = "Abstract: Majúscules\nTags: [a, b]"
        abstract, tags = _parse_llm_metadata_response(text, "s")
        assert abstract == "Majúscules"
        assert tags == ["a", "b"]

    def test_empty_response_returns_empty_abstract_and_stem(self):
        abstract, tags = _parse_llm_metadata_response("", "stem_val")
        assert abstract == ""
        assert tags == ["stem_val"]


# ─── _get_engine_instance ─────────────────────────────────────────────────────

class TestGetEngineInstance:
    def test_none_reg_returns_none(self):
        assert _get_engine_instance(None) is None

    def test_reg_without_instance_returns_none(self):
        reg = MagicMock()
        reg.instance = None
        assert _get_engine_instance(reg) is None

    def test_reg_with_get_module_instance_calls_it(self):
        engine = MagicMock()
        reg = MagicMock()
        reg.instance.get_module_instance.return_value = engine
        result = _get_engine_instance(reg)
        assert result is engine
        reg.instance.get_module_instance.assert_called_once()

    def test_reg_without_get_module_instance_returns_none(self):
        reg = MagicMock()
        del reg.instance.get_module_instance
        result = _get_engine_instance(reg)
        assert result is None


# ─── _collect_stream_response ─────────────────────────────────────────────────

class TestCollectStreamResponse:
    @pytest.mark.asyncio
    async def test_dict_chunks_with_message_content(self):
        async def gen():
            yield {"message": {"content": "Hola"}}
            yield {"message": {"content": " món"}}

        result = await _collect_stream_response(gen())
        assert result == "Hola món"

    @pytest.mark.asyncio
    async def test_dict_chunks_with_direct_content(self):
        async def gen():
            yield {"content": "text directe"}

        result = await _collect_stream_response(gen())
        assert result == "text directe"

    @pytest.mark.asyncio
    async def test_str_chunks_concatenated(self):
        async def gen():
            yield "part1"
            yield "part2"

        result = await _collect_stream_response(gen())
        assert result == "part1part2"

    @pytest.mark.asyncio
    async def test_empty_stream_returns_empty(self):
        async def gen():
            return
            yield  # noqa: unreachable

        result = await _collect_stream_response(gen())
        assert result == ""

    @pytest.mark.asyncio
    async def test_mixed_dict_and_str_chunks(self):
        async def gen():
            yield {"content": "A"}
            yield "B"

        result = await _collect_stream_response(gen())
        assert result == "AB"


# ─── _call_llm_for_metadata ──────────────────────────────────────────────────

class TestCallLlmForMetadata:
    def _make_engine(self, has_model_param: bool, return_value):
        engine = MagicMock()
        if has_model_param:
            engine.chat = MagicMock(
                return_value=return_value,
                __signature__=inspect.Signature([
                    inspect.Parameter("model", inspect.Parameter.KEYWORD_ONLY),
                    inspect.Parameter("messages", inspect.Parameter.KEYWORD_ONLY),
                    inspect.Parameter("stream", inspect.Parameter.KEYWORD_ONLY),
                ])
            )
        else:
            engine.chat = MagicMock(
                return_value=return_value,
                __signature__=inspect.Signature([
                    inspect.Parameter("messages", inspect.Parameter.KEYWORD_ONLY),
                    inspect.Parameter("system", inspect.Parameter.KEYWORD_ONLY),
                    inspect.Parameter("stream", inspect.Parameter.KEYWORD_ONLY),
                ])
            )
        return engine

    @pytest.mark.asyncio
    async def test_coroutine_result_dict_with_message_content(self):
        async def coro():
            return {"message": {"content": "resposta"}}

        engine = self._make_engine(has_model_param=True, return_value=coro())
        result = await _call_llm_for_metadata(engine, "llama3", "sys", "usr")
        assert result == "resposta"

    @pytest.mark.asyncio
    async def test_coroutine_result_dict_with_content_key(self):
        async def coro():
            return {"content": "contingut directe"}

        engine = self._make_engine(has_model_param=False, return_value=coro())
        result = await _call_llm_for_metadata(engine, "llama3", "sys", "usr")
        assert result == "contingut directe"

    @pytest.mark.asyncio
    async def test_coroutine_result_dict_with_response_key(self):
        async def coro():
            return {"response": "via response"}

        engine = self._make_engine(has_model_param=True, return_value=coro())
        result = await _call_llm_for_metadata(engine, "llama3", "sys", "usr")
        assert result == "via response"

    @pytest.mark.asyncio
    async def test_coroutine_result_non_dict_converted_to_str(self):
        async def coro():
            return 42

        engine = self._make_engine(has_model_param=True, return_value=coro())
        result = await _call_llm_for_metadata(engine, "llama3", "sys", "usr")
        assert result == "42"

    @pytest.mark.asyncio
    async def test_sync_result_converted_to_str(self):
        engine = self._make_engine(has_model_param=True, return_value="sync text")
        result = await _call_llm_for_metadata(engine, "llama3", "sys", "usr")
        assert result == "sync text"

    @pytest.mark.asyncio
    async def test_engine_with_model_param_passes_model(self):
        async def coro():
            return {"content": "ok"}

        engine = self._make_engine(has_model_param=True, return_value=coro())
        await _call_llm_for_metadata(engine, "model-x", "sys", "usr")
        call_kwargs = engine.chat.call_args
        assert call_kwargs.kwargs.get("model") == "model-x"

    @pytest.mark.asyncio
    async def test_engine_without_model_param_passes_system(self):
        async def coro():
            return {"content": "ok"}

        engine = self._make_engine(has_model_param=False, return_value=coro())
        await _call_llm_for_metadata(engine, "model-x", "sys-prompt", "usr")
        call_kwargs = engine.chat.call_args
        assert call_kwargs.kwargs.get("system") == "sys-prompt"
        assert "model" not in call_kwargs.kwargs


# ─── _try_engines ─────────────────────────────────────────────────────────────

class TestTryEngines:
    def _make_module_manager(self, engines: dict):
        mm = MagicMock()
        mm.registry.get_module = lambda name: engines.get(name)
        return mm

    def _make_reg_with_engine(self, engine):
        reg = MagicMock()
        reg.instance.get_module_instance.return_value = engine
        return reg

    @pytest.mark.asyncio
    async def test_no_engines_returns_none(self):
        mm = self._make_module_manager({})
        result = await _try_engines(mm, "m", "sys", "usr", "stem", "ca")
        assert result is None

    @pytest.mark.asyncio
    async def test_engine_without_chat_skipped(self):
        engine = MagicMock(spec=[])
        reg = self._make_reg_with_engine(engine)
        mm = self._make_module_manager({"mlx_module": reg})
        result = await _try_engines(mm, "m", "sys", "usr", "stem", "ca")
        assert result is None

    @pytest.mark.asyncio
    async def test_engine_raises_tries_next(self):
        engine = MagicMock()
        engine.chat.side_effect = RuntimeError("fail")
        reg = self._make_reg_with_engine(engine)
        mm = self._make_module_manager({"mlx_module": reg})
        result = await _try_engines(mm, "m", "sys", "usr", "stem", "ca")
        assert result is None

    @pytest.mark.asyncio
    async def test_engine_no_abstract_returns_none(self):
        with patch(
            "plugins.web_ui_module.core.rag_handler._call_llm_for_metadata",
            new=AsyncMock(return_value="tags: [a, b]"),
        ):
            engine = MagicMock()
            reg = self._make_reg_with_engine(engine)
            mm = self._make_module_manager({"mlx_module": reg})
            result = await _try_engines(mm, "m", "sys", "usr", "stem", "ca")
        assert result is None

    @pytest.mark.asyncio
    async def test_engine_with_abstract_returns_dict(self):
        llm_response = "abstract: Bon document\ntags: [a, b]"
        with patch(
            "plugins.web_ui_module.core.rag_handler._call_llm_for_metadata",
            new=AsyncMock(return_value=llm_response),
        ):
            engine = MagicMock()
            reg = self._make_reg_with_engine(engine)
            mm = self._make_module_manager({"mlx_module": reg})
            result = await _try_engines(mm, "m", "sys", "usr", "stem", "ca")
        assert result is not None
        assert result["abstract"] == "Bon document"
        assert result["tags"] == ["a", "b"]
        assert result["priority"] == "P2"
        assert result["lang"] == "ca"


# ─── generate_rag_metadata ────────────────────────────────────────────────────

class TestGenerateRagMetadata:
    @pytest.mark.asyncio
    async def test_module_manager_none_returns_fallback(self):
        state = MagicMock()
        state.module_manager = None
        with patch("core.lifespan.get_server_state", return_value=state):
            result = await generate_rag_metadata("contingut", "doc.txt")
        assert result["tags"] == ["doc"]
        assert result["priority"] == "P2"

    @pytest.mark.asyncio
    async def test_get_server_state_raises_returns_fallback(self):
        with patch(
            "core.lifespan.get_server_state",
            side_effect=RuntimeError("no server"),
        ):
            result = await generate_rag_metadata("contingut", "doc.txt")
        assert result["priority"] == "P2"
        assert result["type"] == "docs"

    @pytest.mark.asyncio
    async def test_llm_returns_abstract_used(self):
        state = MagicMock()
        state.module_manager = MagicMock()
        llm_result = {"abstract": "LLM abstract", "tags": ["a"], "priority": "P2", "type": "docs", "lang": "ca"}
        with patch("core.lifespan.get_server_state", return_value=state):
            with patch(
                "plugins.web_ui_module.core.rag_handler._try_engines",
                new=AsyncMock(return_value=llm_result),
            ):
                result = await generate_rag_metadata("contingut", "doc.txt")
        assert result["abstract"] == "LLM abstract"

    @pytest.mark.asyncio
    async def test_llm_returns_none_fallback_used(self):
        state = MagicMock()
        state.module_manager = MagicMock()
        with patch("core.lifespan.get_server_state", return_value=state):
            with patch(
                "plugins.web_ui_module.core.rag_handler._try_engines",
                new=AsyncMock(return_value=None),
            ):
                result = await generate_rag_metadata("text curt", "fitxer.md")
        assert result["tags"] == ["fitxer"]

    @pytest.mark.asyncio
    async def test_stem_computed_from_filename(self):
        state = MagicMock()
        state.module_manager = None
        with patch("core.lifespan.get_server_state", return_value=state):
            result = await generate_rag_metadata("text", "el_meu-doc.pdf")
        assert result["tags"] == ["el meu doc"]
