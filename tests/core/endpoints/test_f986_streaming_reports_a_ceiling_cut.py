"""
────────────────────────────────────
Server Nexe
Author: Jordi Goy
Location: tests/core/endpoints/test_f986_streaming_reports_a_ceiling_cut.py
Description: #986 — a STREAMED answer cut by the token ceiling must close with
    finish_reason="length", like the blocking path already does.

    The engines know why they stopped: MLX and llama.cpp carry it in the result
    dict that reaches ``bridge.result``, and Ollama puts it in ``done_reason``
    on its final line. All three streaming paths threw it away — MLX and
    llama.cpp passed only ``bridge._truncated`` (a DIFFERENT cut: the queue
    overflowed, B216), and Ollama closed with a bare [DONE] and no final chunk
    at all. With the very same engine payload, the blocking path answered
    "length" and the stream answered "stop".

    That matters because stream=True is the default in LangChain, Open WebUI,
    aider and Continue: those clients read finish_reason to decide whether to
    ask for the tail, so "stop" on a truncated answer drops it in silence.

    These tests drive the REAL generators, not a local copy of the expression.

www.jgoy.net · https://server-nexe.org
────────────────────────────────────
"""

import asyncio
import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from core.endpoints.chat_engines._streaming import format_sse_done


def _finish_reason_of(frame: str) -> str:
    """Read finish_reason out of an SSE data frame."""
    return json.loads(frame.removeprefix("data: ").strip())["choices"][0]["finish_reason"]


def _final_chunk(chunks: list) -> dict:
    """The last real chunk before [DONE] — the one that carries finish_reason."""
    payloads = [c for c in chunks if c.startswith("data: ") and "[DONE]" not in c]
    return json.loads(payloads[-1].removeprefix("data: ").strip())


async def _collect(gen) -> list:
    return [c async for c in gen]


async def _async_iter(items):
    for it in items:
        yield it


class TestFormatSseDone:
    """The close formatter must honour the engine's reason, not only B216."""

    def test_an_engine_ceiling_cut_closes_with_length(self):
        frame = format_sse_done("m", "mlx", truncated=False, finish_reason="length")
        assert _finish_reason_of(frame) == "length"

    def test_a_clean_engine_stop_closes_with_stop(self):
        frame = format_sse_done("m", "mlx", truncated=False, finish_reason="stop")
        assert _finish_reason_of(frame) == "stop"

    def test_an_engine_that_reports_nothing_degrades_to_stop(self):
        """Absence is not a truncation — same rule as the blocking builder."""
        frame = format_sse_done("m", "mlx", truncated=False, finish_reason=None)
        assert _finish_reason_of(frame) == "stop"

    def test_a_queue_overflow_still_closes_with_length(self):
        """B216 must survive: the drop stays visible even on a clean engine stop."""
        frame = format_sse_done("m", "mlx", truncated=True, finish_reason="stop")
        assert _finish_reason_of(frame) == "length"


def _fake_engine_module(finish_reason, text="tallat a mig"):
    """An engine whose chat() streams one token and reports finish_reason."""
    module = MagicMock()

    async def _chat(*, stream_callback, **kwargs):
        stream_callback(text)
        result = {"response": text, "tokens": 40}
        if finish_reason is not None:
            result["finish_reason"] = finish_reason
        return result

    module.chat = _chat
    return module


class TestMlxStream:
    """The MLX generator drops bridge.result on the floor no more."""

    def test_a_ceiling_cut_reaches_the_client_as_length(self):
        from core.endpoints.chat_engines.mlx import _mlx_stream_generator

        gen = _mlx_stream_generator(
            _fake_engine_module("length"), [{"role": "user", "content": "hola"}],
            "sys", "some-model",
        )
        chunks = asyncio.run(_collect(gen))
        assert _final_chunk(chunks)["choices"][0]["finish_reason"] == "length"

    def test_a_complete_answer_still_closes_with_stop(self):
        from core.endpoints.chat_engines.mlx import _mlx_stream_generator

        gen = _mlx_stream_generator(
            _fake_engine_module("stop", text="sencer"),
            [{"role": "user", "content": "hola"}], "sys", "some-model",
        )
        chunks = asyncio.run(_collect(gen))
        assert _final_chunk(chunks)["choices"][0]["finish_reason"] == "stop"

    def test_an_engine_that_reports_nothing_does_not_invent_a_cut(self):
        from core.endpoints.chat_engines.mlx import _mlx_stream_generator

        gen = _mlx_stream_generator(
            _fake_engine_module(None, text="sencer"),
            [{"role": "user", "content": "hola"}], "sys", "some-model",
        )
        chunks = asyncio.run(_collect(gen))
        assert _final_chunk(chunks)["choices"][0]["finish_reason"] == "stop"


class TestLlamaCppStream:
    """Same wiring on the llama.cpp path (it reports nothing today — #987)."""

    def test_a_ceiling_cut_reaches_the_client_as_length(self):
        from core.endpoints.chat_engines.llama_cpp import _llama_cpp_stream_generator

        gen = _llama_cpp_stream_generator(
            _fake_engine_module("length"), [{"role": "user", "content": "hola"}],
            "sys", "some-model",
        )
        chunks = asyncio.run(_collect(gen))
        assert _final_chunk(chunks)["choices"][0]["finish_reason"] == "length"

    def test_a_complete_answer_still_closes_with_stop(self):
        from core.endpoints.chat_engines.llama_cpp import _llama_cpp_stream_generator

        gen = _llama_cpp_stream_generator(
            _fake_engine_module("stop", text="sencer"),
            [{"role": "user", "content": "hola"}], "sys", "some-model",
        )
        chunks = asyncio.run(_collect(gen))
        assert _final_chunk(chunks)["choices"][0]["finish_reason"] == "stop"


def _ollama_client(lines):
    """An httpx.AsyncClient stub that streams the given JSON lines."""
    resp = AsyncMock()
    resp.status_code = 200
    resp.aiter_lines = MagicMock(return_value=_async_iter(lines))

    stream_cm = AsyncMock()
    stream_cm.__aenter__ = AsyncMock(return_value=resp)
    stream_cm.__aexit__ = AsyncMock(return_value=False)

    client = AsyncMock()
    client.__aenter__ = AsyncMock(return_value=client)
    client.__aexit__ = AsyncMock(return_value=False)
    client.stream = MagicMock(return_value=stream_cm)
    return client


class TestOllamaStream:
    """Ollama used to close with a bare [DONE]: no final chunk to read at all."""

    @pytest.mark.parametrize("done_reason,expected", [("length", "length"), ("stop", "stop")])
    def test_done_reason_reaches_the_client(self, done_reason, expected):
        from core.endpoints.chat_engines.ollama import _ollama_stream_generator

        lines = [
            json.dumps({"message": {"content": "tallat"}, "done": False}),
            json.dumps({"message": {"content": ""}, "done": True, "done_reason": done_reason}),
        ]
        with patch("httpx.AsyncClient", return_value=_ollama_client(lines)):
            gen = _ollama_stream_generator("http://localhost/api/chat", {"model": "qwen"}, None, None)
            chunks = asyncio.run(_collect(gen))

        assert any("[DONE]" in c for c in chunks), "the stream must still terminate with [DONE]"
        assert _final_chunk(chunks)["choices"][0]["finish_reason"] == expected

    def test_the_final_chunk_comes_before_done(self):
        """A client that stops reading at [DONE] must still see the reason."""
        from core.endpoints.chat_engines.ollama import _ollama_stream_generator

        lines = [json.dumps({"message": {"content": "x"}, "done": True, "done_reason": "length"})]
        with patch("httpx.AsyncClient", return_value=_ollama_client(lines)):
            gen = _ollama_stream_generator("http://localhost/api/chat", {"model": "qwen"}, None, None)
            chunks = asyncio.run(_collect(gen))

        done_index = next(i for i, c in enumerate(chunks) if "[DONE]" in c)
        reasons = [
            i for i, c in enumerate(chunks)
            if "finish_reason" in c and "[DONE]" not in c
        ]
        assert reasons and max(reasons) < done_index

    def test_an_older_build_without_done_reason_does_not_invent_a_cut(self):
        """Older Ollama omits done_reason — absence is not a truncation."""
        from core.endpoints.chat_engines.ollama import _ollama_stream_generator

        lines = [json.dumps({"message": {"content": "sencer"}, "done": True})]
        with patch("httpx.AsyncClient", return_value=_ollama_client(lines)):
            gen = _ollama_stream_generator("http://localhost/api/chat", {"model": "qwen"}, None, None)
            chunks = asyncio.run(_collect(gen))

        assert _final_chunk(chunks)["choices"][0]["finish_reason"] == "stop"


class TestBlockingAndStreamingAgree:
    """The bug in one line: same engine payload, two different answers."""

    def test_the_same_ceiling_cut_reads_the_same_on_both_paths(self):
        from core.endpoints.chat_engines._common import build_openai_response

        engine_result = {"response": "tallat a mig", "finish_reason": "length", "tokens": 40}

        blocking = build_openai_response(engine_result, "some-model", "mlx")
        streamed = format_sse_done(
            "some-model", "mlx", truncated=False,
            finish_reason=engine_result["finish_reason"],
        )

        assert blocking["choices"][0]["finish_reason"] == _finish_reason_of(streamed) == "length"
