"""
Tests for uncovered lines in core/endpoints/chat.py.
Targets: lines 244-245, 260-261, 275-276, 302, 305-310, 353-354,
379-380, 382-386, 432-433, 464, 484-485, 531-532, 537,
582-583, 590-591, 629-630, 698-699, 710-713, 948-949, 1011-1017
"""
import asyncio
import json
import os
import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from core.dependencies import limiter as _limiter
from core.endpoints.chat_engines._streaming import NEXE_END


def _end(chunks) -> dict:
    """The generator's closing sentinel. `[DONE]` belongs to the turn."""
    ends = [c[NEXE_END] for c in chunks if isinstance(c, dict) and NEXE_END in c]
    assert ends, "the generator closes with a sentinel; [DONE] belongs to the turn"
    assert not any(isinstance(c, str) and "[DONE]" in c for c in chunks)
    return ends[-1]


@pytest.fixture(autouse=True)
def _disable_rate_limiter():
    """Disable slowapi rate limiter for direct function calls (no real Request)."""
    _limiter.enabled = False
    yield
    _limiter.enabled = True


# ─── Test _ollama_stream_generator uncovered branches ──────────────────
class TestOllamaStreamGenerator:

    def test_stream_completes_with_a_sentinel(self):
        """Streaming Ollama closes with a sentinel after a content chunk."""
        from core.endpoints.chat import _ollama_stream_generator

        ollama_lines = [
            json.dumps({"message": {"content": "Hello"}, "done": False}),
            json.dumps({"message": {"content": ""}, "done": True}),
        ]

        mock_resp = AsyncMock()
        mock_resp.status_code = 200
        mock_resp.aiter_lines = MagicMock(return_value=_make_async_iter(ollama_lines))

        mock_stream_cm = AsyncMock()
        mock_stream_cm.__aenter__ = AsyncMock(return_value=mock_resp)
        mock_stream_cm.__aexit__ = AsyncMock(return_value=False)

        mock_client = AsyncMock()
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)
        mock_client.stream = MagicMock(return_value=mock_stream_cm)

        app_state = MagicMock()

        with patch("httpx.AsyncClient", return_value=mock_client):
            gen = _ollama_stream_generator("http://localhost/api/chat", {}, app_state, "test msg")
            chunks = asyncio.run(_collect_async_gen(gen))
            assert "Hello" in "".join(c for c in chunks if isinstance(c, str))
            assert _end(chunks)["failure"] is None

    def test_stream_cancelled(self):
        """Lines 590-591: CancelledError is handled."""
        from core.endpoints.chat import _ollama_stream_generator

        mock_stream_cm = AsyncMock()
        mock_stream_cm.__aenter__ = AsyncMock(side_effect=asyncio.CancelledError())
        mock_stream_cm.__aexit__ = AsyncMock(return_value=False)

        mock_client = AsyncMock()
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)
        mock_client.stream = MagicMock(return_value=mock_stream_cm)

        with patch("httpx.AsyncClient", return_value=mock_client):
            gen = _ollama_stream_generator("http://localhost/api/chat", {}, None, None)
            chunks = asyncio.run(_collect_async_gen(gen))
            assert chunks == []

    def test_stream_json_decode_error(self):
        """Lines 586-587: JSON decode error in stream."""
        from core.endpoints.chat import _ollama_stream_generator

        lines = ["not-json", json.dumps({"done": True})]

        mock_resp = AsyncMock()
        mock_resp.status_code = 200
        mock_resp.aiter_lines = MagicMock(return_value=_make_async_iter(lines))

        mock_stream_cm = AsyncMock()
        mock_stream_cm.__aenter__ = AsyncMock(return_value=mock_resp)
        mock_stream_cm.__aexit__ = AsyncMock(return_value=False)

        mock_client = AsyncMock()
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)
        mock_client.stream = MagicMock(return_value=mock_stream_cm)

        with patch("httpx.AsyncClient", return_value=mock_client):
            gen = _ollama_stream_generator("http://localhost/api/chat", {}, None, None)
            chunks = asyncio.run(_collect_async_gen(gen))
            assert _end(chunks)["failure"] is None

    def test_stream_error_status_is_http(self):
        """A non-200 before any token raises, so the cascade can still retry."""
        from fastapi import HTTPException
        from core.endpoints.chat import _ollama_stream_generator

        mock_resp = AsyncMock()
        mock_resp.status_code = 500

        mock_stream_cm = AsyncMock()
        mock_stream_cm.__aenter__ = AsyncMock(return_value=mock_resp)
        mock_stream_cm.__aexit__ = AsyncMock(return_value=False)

        mock_client = AsyncMock()
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)
        mock_client.stream = MagicMock(return_value=mock_stream_cm)

        with patch("httpx.AsyncClient", return_value=mock_client):
            gen = _ollama_stream_generator("http://localhost/api/chat", {}, None, None)
            with pytest.raises(HTTPException) as exc:
                asyncio.run(_collect_async_gen(gen))
        assert exc.value.status_code == 500

    def test_stream_connect_error_is_http(self):
        """A connection error before any token is HTTP 503, not an SSE frame."""
        import httpx
        from fastapi import HTTPException
        from core.endpoints.chat import _ollama_stream_generator

        mock_client = AsyncMock()
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)
        mock_client.stream = MagicMock(side_effect=httpx.ConnectError("no connection"))

        with patch("httpx.AsyncClient", return_value=mock_client):
            gen = _ollama_stream_generator("http://localhost/api/chat", {}, None, None)
            with pytest.raises(HTTPException) as exc:
                asyncio.run(_collect_async_gen(gen))
        assert exc.value.status_code == 503

    def test_stream_byte_cap_terminates_runaway(self, monkeypatch):
        """B104: a model in a loop must NOT accumulate without limit; on exceeding
        MAX_STREAM_BYTES the generator must emit a cap error and stop
        (symmetric with TokenBridge._cap_triggered of the MLX/llama_cpp path)."""
        from core.endpoints.chat import _ollama_stream_generator
        from core.endpoints.chat_engines import ollama as _ollama_mod

        # Lower the cap to 1 KiB so a few chunks exceed it.
        monkeypatch.setattr(_ollama_mod, "MAX_STREAM_BYTES", 1024, raising=False)

        chunk = "x" * 512  # 512 bytes ASCII -> 2 fit (1024), the 3rd exceeds
        # "runaway": 100 chunks; "done" never arrives. Without a cap, the generator
        # would emit all 100 deltas.
        ollama_lines = [
            json.dumps({"message": {"content": chunk}, "done": False})
            for _ in range(100)
        ]

        mock_resp = AsyncMock()
        mock_resp.status_code = 200
        mock_resp.aiter_lines = MagicMock(return_value=_make_async_iter(ollama_lines))

        mock_stream_cm = AsyncMock()
        mock_stream_cm.__aenter__ = AsyncMock(return_value=mock_resp)
        mock_stream_cm.__aexit__ = AsyncMock(return_value=False)

        mock_client = AsyncMock()
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)
        mock_client.stream = MagicMock(return_value=mock_stream_cm)

        with patch("httpx.AsyncClient", return_value=mock_client):
            gen = _ollama_stream_generator("http://localhost/api/chat", {}, None, None)
            chunks = asyncio.run(_collect_async_gen(gen))

        end = _end(chunks)
        assert end["failure"] == "stream_cap_exceeded"
        assert end["truncated"] is True
        # 2) Comportamental: NO ha consumit els 100 chunks; para molt abans.
        delta_chunks = [c for c in chunks if isinstance(c, str) and '"delta"' in c]
        assert len(delta_chunks) < 10, f"acumula sense límit: {len(delta_chunks)} deltes"


# ─── Test _mlx_stream_generator uncovered branches ─────────────────────
class TestMlxStreamGenerator:

    def test_mlx_stream_on_token_enqueue_failure(self):
        """Lines 629-630: token enqueue failure logged."""
        from core.endpoints.chat import _mlx_stream_generator

        mock_mlx = AsyncMock()
        mock_mlx.chat = AsyncMock(return_value={"response": "test", "tokens": 5, "tokens_per_second": 10})

        gen = _mlx_stream_generator(mock_mlx, [{"role": "user", "content": "hi"}], "system", "model")
        chunks = asyncio.run(_collect_async_gen(gen))
        assert _end(chunks)["failure"] is None

    def test_mlx_stream_completes_with_done(self):
        """MLX streaming still closes with [DONE] after emitting tokens."""
        from core.endpoints.chat import _mlx_stream_generator

        mock_mlx = AsyncMock()

        async def fake_chat(**kwargs):
            cb = kwargs.get("stream_callback")
            if cb:
                cb("Hello")
            return {"response": "Hello", "tokens": 1, "tokens_per_second": 1}

        mock_mlx.chat = fake_chat
        app_state = MagicMock()

        gen = _mlx_stream_generator(mock_mlx, [{"role": "user", "content": "hi"}],
                                    "system", "model", app_state=app_state, user_msg="hi")
        chunks = asyncio.run(_collect_async_gen(gen))
        assert _end(chunks)["failure"] is None

    def test_mlx_stream_exception(self):
        """#1036 (C2.4): an exception before any token reached the client
        raises instead of yielding an error chunk — the forwarder's peek can
        catch it and let the cascade retry the next engine. Either way, the
        failure is never silent."""
        from core.endpoints.chat import _mlx_stream_generator

        mock_mlx = AsyncMock()
        mock_mlx.chat = AsyncMock(side_effect=RuntimeError("MLX crashed"))

        gen = _mlx_stream_generator(mock_mlx, [], "system", "model")
        with pytest.raises(RuntimeError, match="MLX crashed"):
            asyncio.run(_collect_async_gen(gen))


# ─── Test _llama_cpp_stream_generator uncovered branches ───────────────
class TestLlamaCppStreamGenerator:

    def test_llama_cpp_stream_on_token_enqueue_failure(self):
        """Lines 948-949: token enqueue failure logged."""
        from core.endpoints.chat import _llama_cpp_stream_generator

        mock_llama = AsyncMock()
        mock_llama.chat = AsyncMock(return_value={"response": "test", "tokens": 5})

        gen = _llama_cpp_stream_generator(mock_llama, [{"role": "user", "content": "hi"}], "system", "model")
        chunks = asyncio.run(_collect_async_gen(gen))
        assert _end(chunks)["failure"] is None

    def test_llama_cpp_stream_completes_with_done(self):
        """llama.cpp streaming still closes with [DONE] after emitting tokens."""
        from core.endpoints.chat import _llama_cpp_stream_generator

        mock_llama = AsyncMock()

        async def fake_chat(**kwargs):
            cb = kwargs.get("stream_callback")
            if cb:
                cb("Hello")
            return {"response": "Hello", "tokens": 1}

        mock_llama.chat = fake_chat
        app_state = MagicMock()

        gen = _llama_cpp_stream_generator(mock_llama, [{"role": "user", "content": "hi"}],
                                          "system", "model", app_state=app_state, user_msg="hi")
        chunks = asyncio.run(_collect_async_gen(gen))
        assert _end(chunks)["failure"] is None

    def test_llama_cpp_stream_exception(self):
        """#1036 (C2.4): an exception before any token reached the client
        raises instead of yielding an error chunk — see the MLX generator's
        equivalent test for the full rationale."""
        from core.endpoints.chat import _llama_cpp_stream_generator

        mock_llama = AsyncMock()
        mock_llama.chat = AsyncMock(side_effect=RuntimeError("Llama crashed"))

        gen = _llama_cpp_stream_generator(mock_llama, [], "system", "model")
        with pytest.raises(RuntimeError, match="Llama crashed"):
            asyncio.run(_collect_async_gen(gen))


# ─── Test chat_completions endpoint uncovered branches ─────────────────
class TestChatCompletionsRagBranches:

    def test_rag_docs_search_exception(self):
        """Lines 244-245: RAG docs search exception caught."""
        from core.endpoints.chat import chat_completions, ChatCompletionRequest, Message
        from fastapi import BackgroundTasks

        mock_memory = AsyncMock()
        mock_memory.collection_exists = AsyncMock(side_effect=[Exception("docs fail"), False, False])

        req = _make_request()
        bg = BackgroundTasks()
        request = ChatCompletionRequest(
            messages=[Message(role="user", content="hello")],
            use_rag=True, stream=False, engine="ollama"
        )

        with patch("memory.memory.api.v1.get_memory_api", new=AsyncMock(return_value=mock_memory)), \
             patch("core.endpoints.chat._forward_to_ollama",
                   new=AsyncMock(return_value={"choices": [{"message": {"content": "hi"}}]})):
            result = asyncio.run(chat_completions(request, req, bg))
            assert result is not None

    def test_rag_knowledge_search_exception(self):
        """Lines 260-261: RAG knowledge search exception caught."""
        from core.endpoints.chat import chat_completions, ChatCompletionRequest, Message
        from fastapi import BackgroundTasks

        mock_memory = AsyncMock()
        mock_memory.collection_exists = AsyncMock(side_effect=[False, Exception("knowledge fail"), False])

        req = _make_request()
        bg = BackgroundTasks()
        request = ChatCompletionRequest(
            messages=[Message(role="user", content="hello")],
            use_rag=True, stream=False, engine="ollama"
        )

        with patch("memory.memory.api.v1.get_memory_api", new=AsyncMock(return_value=mock_memory)), \
             patch("core.endpoints.chat._forward_to_ollama",
                   new=AsyncMock(return_value={"choices": [{"message": {"content": "hi"}}]})):
            result = asyncio.run(chat_completions(request, req, bg))
            assert result is not None

    def test_rag_chat_memory_search_exception(self):
        """Lines 275-276: RAG chat memory search exception caught."""
        from core.endpoints.chat import chat_completions, ChatCompletionRequest, Message
        from fastapi import BackgroundTasks

        mock_memory = AsyncMock()
        mock_memory.collection_exists = AsyncMock(side_effect=[False, False, Exception("mem fail")])

        req = _make_request()
        bg = BackgroundTasks()
        request = ChatCompletionRequest(
            messages=[Message(role="user", content="hello")],
            use_rag=True, stream=False, engine="ollama"
        )

        with patch("memory.memory.api.v1.get_memory_api", new=AsyncMock(return_value=mock_memory)), \
             patch("core.endpoints.chat._forward_to_ollama",
                   new=AsyncMock(return_value={"choices": [{"message": {"content": "hi"}}]})):
            result = asyncio.run(chat_completions(request, req, bg))
            assert result is not None

    def test_rag_fallback_to_rag_module_no_results(self):
        """Lines 302, 305-310: MemoryAPI fails, RAG fallback returns no results."""
        from core.endpoints.chat import chat_completions, ChatCompletionRequest, Message
        from fastapi import BackgroundTasks

        mock_rag = MagicMock()
        mock_rag.search = AsyncMock(return_value=[])

        req = _make_request(modules={"rag": mock_rag})
        bg = BackgroundTasks()
        request = ChatCompletionRequest(
            messages=[Message(role="user", content="hello")],
            use_rag=True, stream=False, engine="ollama"
        )

        with patch("memory.memory.api.v1.get_memory_api", new=AsyncMock(side_effect=Exception("no memory"))), \
             patch("core.endpoints.chat._forward_to_ollama",
                   new=AsyncMock(return_value={"choices": [{"message": {"content": "hi"}}]})):
            result = asyncio.run(chat_completions(request, req, bg))
            assert result is not None

    def test_rag_fallback_str_results(self):
        """Line 302: RAG results is not a list."""
        from core.endpoints.chat import chat_completions, ChatCompletionRequest, Message
        from fastapi import BackgroundTasks

        mock_rag = MagicMock()
        mock_rag.search = AsyncMock(return_value="plain text results")

        req = _make_request(modules={"rag": mock_rag})
        bg = BackgroundTasks()
        request = ChatCompletionRequest(
            messages=[Message(role="user", content="hello")],
            use_rag=True, stream=False, engine="ollama"
        )

        with patch("memory.memory.api.v1.get_memory_api", new=AsyncMock(side_effect=Exception("no memory"))), \
             patch("core.endpoints.chat._forward_to_ollama",
                   new=AsyncMock(return_value={"choices": [{"message": {"content": "hi"}}]})):
            result = asyncio.run(chat_completions(request, req, bg))
            assert result is not None

    def test_rag_fallback_no_rag_module(self):
        """Lines 306-307: No RAG source available."""
        from core.endpoints.chat import chat_completions, ChatCompletionRequest, Message
        from fastapi import BackgroundTasks

        req = _make_request(modules={})
        bg = BackgroundTasks()
        request = ChatCompletionRequest(
            messages=[Message(role="user", content="hello")],
            use_rag=True, stream=False, engine="ollama"
        )

        with patch("memory.memory.api.v1.get_memory_api", new=AsyncMock(side_effect=Exception("no memory"))), \
             patch("core.endpoints.chat._forward_to_ollama",
                   new=AsyncMock(return_value={"choices": [{"message": {"content": "hi"}}]})):
            result = asyncio.run(chat_completions(request, req, bg))
            assert result is not None

    def test_chat_metrics_failure(self):
        """Lines 353-354: chat engine metrics failure caught."""
        from core.endpoints.chat import chat_completions, ChatCompletionRequest, Message
        from fastapi import BackgroundTasks

        req = _make_request()
        bg = BackgroundTasks()
        request = ChatCompletionRequest(
            messages=[Message(role="user", content="hello")],
            use_rag=False, stream=False, engine="ollama"
        )

        with patch("core.endpoints.chat._forward_to_ollama",
                   new=AsyncMock(return_value={"choices": [{"message": {"content": "hi"}}]})), \
             patch.dict("sys.modules", {"core.metrics.registry": None}):
            result = asyncio.run(chat_completions(request, req, bg))
            assert result is not None

    def test_streaming_response_adds_headers(self):
        """Lines 382-386: streaming response gets engine headers."""
        from core.endpoints.chat import chat_completions, ChatCompletionRequest, Message
        from fastapi import BackgroundTasks
        from fastapi.responses import StreamingResponse

        async def fake_gen():
            yield "data: [DONE]\n\n"

        streaming_resp = StreamingResponse(fake_gen(), media_type="text/event-stream")

        req = _make_request()
        bg = BackgroundTasks()
        request = ChatCompletionRequest(
            messages=[Message(role="user", content="hello")],
            use_rag=False, stream=True, engine="ollama"
        )

        with patch("core.endpoints.chat._forward_to_ollama",
                   new=AsyncMock(return_value=streaming_resp)), \
             patch.dict(os.environ, {"NEXE_MODEL_ENGINE": "mlx"}):
            result = asyncio.run(chat_completions(request, req, bg))
            assert isinstance(result, StreamingResponse)

    def test_ollama_model_partial_match_uses_matching(self):
        """Bug 23 (2026-04-06): if there is a partial match (same family),
        the code must promote it to the canonical model and proceed. This test
        verifies the partial match path. Previously, the "fallback to the first
        chat model" version also passed; now it only passes if there is a real match."""
        from core.endpoints.chat import _forward_to_ollama, ChatCompletionRequest, Message

        # The default of _forward_to_ollama without env vars is "llama3.2".
        # We add an available model with the same prefix so the partial
        # match (`model_name.split(":")[0] in m`) picks it up.
        tags_data = {"models": [{"name": "llama3.2:latest"}]}
        mock_tags = MagicMock(status_code=200)
        mock_tags.json.return_value = tags_data

        mock_chat = MagicMock(status_code=200)
        mock_chat.json.return_value = {"message": {"content": "hi"}}

        mock_client = AsyncMock()
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)
        mock_client.get = AsyncMock(return_value=mock_tags)
        mock_client.post = AsyncMock(return_value=mock_chat)

        request = ChatCompletionRequest(
            messages=[Message(role="user", content="hi")],
            stream=False
        )

        with patch("httpx.AsyncClient", return_value=mock_client):
            env_copy = dict(os.environ)
            env_copy.pop("NEXE_OLLAMA_MODEL", None)
            env_copy.pop("NEXE_DEFAULT_MODEL", None)
            with patch.dict(os.environ, env_copy, clear=True):
                result = asyncio.run(_forward_to_ollama(
                    [{"role": "user", "content": "hi"}],
                    request, app_state=MagicMock(config={}),
                ))
                assert result is not None

    def test_ollama_non_streaming_error_json_decode_fail(self):
        """Lines 531-532: Ollama error with unparseable response."""
        from core.endpoints.chat import _forward_to_ollama, ChatCompletionRequest, Message

        tags_data = {"models": [{"name": "llama3.2"}]}
        mock_tags = MagicMock(status_code=200)
        mock_tags.json.return_value = tags_data

        mock_error = MagicMock(status_code=500)
        mock_error.json.side_effect = ValueError("bad json")

        mock_client = AsyncMock()
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)
        mock_client.get = AsyncMock(return_value=mock_tags)
        mock_client.post = AsyncMock(return_value=mock_error)

        request = ChatCompletionRequest(
            messages=[Message(role="user", content="hi")],
            model="llama3.2",  # Bug 23: explicit model to avoid env pollution
            stream=False,
        )

        from fastapi import HTTPException
        env_copy = {k: v for k, v in os.environ.items() if not k.startswith("NEXE_")}
        with patch.dict(os.environ, env_copy, clear=True):
            with patch("httpx.AsyncClient", return_value=mock_client):
                with pytest.raises(HTTPException) as exc:
                    asyncio.run(_forward_to_ollama(
                        [{"role": "user", "content": "hi"}], request
                    ))
                assert exc.value.status_code == 500

    def test_ollama_non_streaming_with_fallback_info(self):
        """Line 537: fallback info added to non-streaming response."""
        from core.endpoints.chat import _forward_to_ollama, ChatCompletionRequest, Message

        tags_data = {"models": [{"name": "llama3.2"}]}
        mock_tags = MagicMock(status_code=200)
        mock_tags.json.return_value = tags_data

        mock_chat = MagicMock(status_code=200)
        mock_chat.json.return_value = {"message": {"content": "hi"}}

        mock_client = AsyncMock()
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)
        mock_client.get = AsyncMock(return_value=mock_tags)
        mock_client.post = AsyncMock(return_value=mock_chat)

        request = ChatCompletionRequest(
            messages=[Message(role="user", content="hi")],
            model="llama3.2",  # Bug 23: explicit model to avoid env pollution
            stream=False,
        )

        env_copy = {k: v for k, v in os.environ.items() if not k.startswith("NEXE_")}
        with patch.dict(os.environ, env_copy, clear=True):
            with patch("httpx.AsyncClient", return_value=mock_client):
                result = asyncio.run(_forward_to_ollama(
                    [{"role": "user", "content": "hi"}], request,
                    fallback_from="mlx", fallback_reason="module_unavailable"
                ))
                assert "nexe_fallback" in result


# ─── Helpers ───────────────────────────────────────────────────────────

async def _make_async_iter(items):
    for item in items:
        yield item


async def _collect_async_gen(gen):
    chunks = []
    try:
        async for chunk in gen:
            chunks.append(chunk)
    except (asyncio.CancelledError, StopAsyncIteration):
        pass
    return chunks


def _make_request(modules=None, config=None):
    """Create a mock FastAPI Request."""
    req = MagicMock()
    req.app.state.config = config or {}
    req.app.state.modules = modules or {}
    req.headers = {"x-api-key": "test-key"}
    # #1078: `session` reads this into ctx.attachments["document"]. An
    # unconfigured MagicMock answers truthy, which `budget` now treats as a
    # real attached document — these tests are not about attachments.
    req.app.state.session_manager.get_or_create_session.return_value.get_attached_document.return_value = None
    return req


# ─── MC-114: unexpected errors in chat hot-paths must carry exc_info ────────
import logging  # noqa: E402


def _has_exc_info(caplog, needle):
    """True if some ERROR record matching `needle` was logged WITH a stack trace."""
    recs = [r for r in caplog.records
            if r.levelno >= logging.ERROR and needle in r.getMessage()]
    return bool(recs) and any(r.exc_info is not None for r in recs)


class TestMC114ExcInfo:
    """The diagnostic value of these error logs is the stack trace. Logging only
    str(e) loses where the failure came from. Each path must log with
    exc_info=True so the traceback reaches the logs."""

    def test_mlx_stream_exception_has_exc_info(self, caplog):
        """The log this pins is `run_mlx`'s own (mlx.py), unaffected by #1036
        (C2.4): it fires before the generator decides whether to raise or
        yield a chunk, so it stays regardless of which one happens here."""
        from core.endpoints.chat import _mlx_stream_generator
        mock_mlx = AsyncMock()
        mock_mlx.chat = AsyncMock(side_effect=RuntimeError("MLX crashed"))
        with caplog.at_level(logging.ERROR):
            gen = _mlx_stream_generator(mock_mlx, [], "system", "model")
            with pytest.raises(RuntimeError, match="MLX crashed"):
                asyncio.run(_collect_async_gen(gen))
        assert _has_exc_info(caplog, "MLX streaming error")

    def test_llama_cpp_stream_exception_has_exc_info(self, caplog):
        """See the MLX generator's equivalent test for why this log survives
        #1036 (C2.4) unchanged."""
        from core.endpoints.chat import _llama_cpp_stream_generator
        mock_llama = AsyncMock()
        mock_llama.chat = AsyncMock(side_effect=RuntimeError("Llama crashed"))
        with caplog.at_level(logging.ERROR):
            gen = _llama_cpp_stream_generator(mock_llama, [], "system", "model")
            with pytest.raises(RuntimeError, match="Llama crashed"):
                asyncio.run(_collect_async_gen(gen))
        assert _has_exc_info(caplog, "Llama.cpp streaming error")

    def test_rag_error_has_exc_info(self, caplog):
        """#899: el boom venia de `_rag_module_fallback`, que ja no existeix.

        Retirat el fallback, l'únic codi que queda dins el `try` EXTERN de
        `build_rag_context` és el log de degradació del `except` intern — que
        és, doncs, l'única manera d'arribar avui a «RAG Error». Es fa petar
        aquell log: `logger.error` segueix sent el real, així que el que es
        mesura (que l'error porta `exc_info`) és el de sempre.
        """
        from core.endpoints import chat_rag
        from core.endpoints.chat_rag import build_rag_context
        with patch("memory.memory.api.v1.get_memory_api",
                   new=AsyncMock(side_effect=RuntimeError("api down"))), \
             patch.object(chat_rag.logger, "warning",
                          side_effect=RuntimeError("log boom")):
            with caplog.at_level(logging.ERROR):
                asyncio.run(build_rag_context("hello", MagicMock(), "en"))
        assert _has_exc_info(caplog, "RAG Error")
