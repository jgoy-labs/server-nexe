"""
────────────────────────────────────
Server Nexe
Author: Jordi Goy
Location: tests/core/endpoints/test_f989_truncation_cause_is_readable.py
Description: #989 — finish_reason="length" covers two cuts that demand opposite
    reactions from a client, and the field alone cannot tell them apart:

    * ceiling — the answer is missing its TAIL. Asking for the continuation
      stitches it in the right place.
    * overflow (B216) — tokens were dropped from the MIDDLE while generation
      carried on, so the ending that arrived is the natural one. Asking for the
      continuation appends new text over an internal hole: the result reads as
      coherent and is not.

    #986 made the ceiling cut visible for the first time and, in doing so,
    overloaded a field that until then only ever meant overflow. The final
    chunk now also carries x_nexe_truncation so the cause is readable.

    It is an extension, not OpenAI: it lives at the ROOT of the chunk, so a
    strict client validating `choices` never sees it and finish_reason keeps
    the canonical value the ecosystem expects.

www.jgoy.net · https://server-nexe.org
────────────────────────────────────
"""

import asyncio
import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from core.endpoints.chat_engines import _streaming
from core.endpoints.chat_engines._streaming import TokenBridge, format_sse_done


def _chunk(frame: str) -> dict:
    return json.loads(frame.removeprefix("data: ").strip())


def _final_chunk(chunks: list) -> dict:
    """The close the client will see. The generator ends with a sentinel
    (C4.6-b); `format_sse_done` is what `emit` turns it into."""
    from core.endpoints.chat_engines._streaming import NEXE_END, format_sse_done

    ends = [c[NEXE_END] for c in chunks if isinstance(c, dict) and NEXE_END in c]
    if ends:
        end = ends[-1]
        frame = format_sse_done(
            "m", "mlx",
            truncated=bool(end.get("truncated")),
            finish_reason=end.get("finish_reason"),
        )
        return json.loads(frame.removeprefix("data: ").strip())
    payloads = [
        c for c in chunks
        if isinstance(c, str) and c.startswith("data: ") and "[DONE]" not in c
    ]
    return json.loads(payloads[-1].removeprefix("data: ").strip())


async def _collect(gen) -> list:
    return [c async for c in gen]


async def _async_iter(items):
    for it in items:
        yield it


class TestTheCauseIsReadable:
    """The formatter names the cut instead of leaving the client to guess."""

    def test_a_ceiling_cut_is_named_ceiling(self):
        chunk = _chunk(format_sse_done("m", "mlx", truncated=False, finish_reason="length"))
        assert chunk["x_nexe_truncation"] == "ceiling"

    def test_a_queue_overflow_is_named_overflow(self):
        chunk = _chunk(format_sse_done("m", "mlx", truncated=True, finish_reason="stop"))
        assert chunk["x_nexe_truncation"] == "overflow"

    def test_overflow_wins_when_both_happened(self):
        """An internal hole is the damage a client must not paper over."""
        chunk = _chunk(format_sse_done("m", "mlx", truncated=True, finish_reason="length"))
        assert chunk["x_nexe_truncation"] == "overflow"

    def test_a_clean_stop_carries_no_cause_at_all(self):
        """Absence is the signal: nothing was cut, so there is nothing to name."""
        chunk = _chunk(format_sse_done("m", "mlx", truncated=False, finish_reason="stop"))
        assert "x_nexe_truncation" not in chunk

    def test_an_engine_that_reports_nothing_carries_no_cause(self):
        chunk = _chunk(format_sse_done("m", "mlx", truncated=False, finish_reason=None))
        assert "x_nexe_truncation" not in chunk


class TestTheOpenAiContractIsUntouched:
    """The extension must not leak into the shape a strict client validates."""

    @pytest.mark.parametrize("truncated,reason", [(True, "stop"), (False, "length")])
    def test_the_cause_lives_at_the_root_not_inside_choices(self, truncated, reason):
        chunk = _chunk(format_sse_done("m", "mlx", truncated=truncated, finish_reason=reason))
        assert "x_nexe_truncation" in chunk
        assert "x_nexe_truncation" not in chunk["choices"][0]
        assert set(chunk["choices"][0]) == {"index", "delta", "finish_reason"}

    def test_finish_reason_keeps_its_canonical_value(self):
        """A client that ignores the extension behaves exactly as before."""
        for truncated, reason in [(True, "stop"), (False, "length"), (True, "length")]:
            chunk = _chunk(format_sse_done("m", "mlx", truncated=truncated, finish_reason=reason))
            assert chunk["choices"][0]["finish_reason"] == "length"


def _fake_engine_module(finish_reason, tokens=("tallat a mig",)):
    module = MagicMock()

    async def _chat(*, stream_callback, **kwargs):
        for t in tokens:
            stream_callback(t)
        result = {"response": "".join(tokens), "tokens": 40}
        if finish_reason is not None:
            result["finish_reason"] = finish_reason
        return result

    module.chat = _chat
    return module


class TestMlxStreamNamesTheCause:
    """Driving the real generator, not the formatter alone."""

    def test_a_ceiling_cut_reaches_the_client_as_ceiling(self):
        from core.endpoints.chat_engines.mlx import _mlx_stream_generator

        gen = _mlx_stream_generator(
            _fake_engine_module("length"), [{"role": "user", "content": "hola"}],
            "sys", "some-model",
        )
        chunks = asyncio.run(_collect(gen))
        assert _final_chunk(chunks)["x_nexe_truncation"] == "ceiling"

    def test_a_real_queue_overflow_reaches_the_client_as_overflow(self, monkeypatch):
        """A bridge too small for the engine's output: the B216 drop path itself."""
        from core.endpoints.chat_engines import mlx as mlx_mod

        class TinyBridge(TokenBridge):
            def __init__(self, maxsize=1, **kwargs):
                super().__init__(maxsize=1, **kwargs)

        monkeypatch.setattr(mlx_mod, "TokenBridge", TinyBridge)
        monkeypatch.setattr(_streaming, "MAX_STREAM_BYTES", 1024 * 1024 * 1024)

        gen = mlx_mod._mlx_stream_generator(
            _fake_engine_module("stop", tokens=tuple(f"t{i}" for i in range(50))),
            [{"role": "user", "content": "hola"}], "sys", "some-model",
        )
        chunks = asyncio.run(_collect(gen))
        final = _final_chunk(chunks)

        assert final["x_nexe_truncation"] == "overflow", (
            "the engine stopped cleanly but tokens were dropped mid-stream: "
            "the client must not be told to resume"
        )
        assert final["choices"][0]["finish_reason"] == "length"

    def test_a_complete_answer_names_nothing(self):
        from core.endpoints.chat_engines.mlx import _mlx_stream_generator

        gen = _mlx_stream_generator(
            _fake_engine_module("stop", tokens=("sencer",)),
            [{"role": "user", "content": "hola"}], "sys", "some-model",
        )
        chunks = asyncio.run(_collect(gen))
        assert "x_nexe_truncation" not in _final_chunk(chunks)


def _ollama_client(lines):
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


class TestOllamaStreamNamesTheCause:
    """Ollama has no TokenBridge, so its only cut is the ceiling."""

    def test_a_ceiling_cut_reaches_the_client_as_ceiling(self):
        from core.endpoints.chat_engines.ollama import _ollama_stream_generator

        lines = [json.dumps({"message": {"content": "tallat"}, "done": True, "done_reason": "length"})]
        with patch("httpx.AsyncClient", return_value=_ollama_client(lines)):
            gen = _ollama_stream_generator("http://localhost/api/chat", {"model": "qwen"}, None, None)
            chunks = asyncio.run(_collect(gen))

        assert _final_chunk(chunks)["x_nexe_truncation"] == "ceiling"

    def test_a_clean_stop_names_nothing(self):
        from core.endpoints.chat_engines.ollama import _ollama_stream_generator

        lines = [json.dumps({"message": {"content": "sencer"}, "done": True, "done_reason": "stop"})]
        with patch("httpx.AsyncClient", return_value=_ollama_client(lines)):
            gen = _ollama_stream_generator("http://localhost/api/chat", {"model": "qwen"}, None, None)
            chunks = asyncio.run(_collect(gen))

        assert "x_nexe_truncation" not in _final_chunk(chunks)
