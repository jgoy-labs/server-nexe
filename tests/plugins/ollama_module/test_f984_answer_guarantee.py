"""
────────────────────────────────────
Server Nexe
Author: Jordi Goy
Location: tests/plugins/ollama_module/test_f984_answer_guarantee.py
Description: #984 for Ollama — a turn that spends the whole ceiling in
    `message.thinking` and never fills `message.content` is retried once with
    think:false. Measured on qwen3.5:4b: a trivial question reasons for ~3100
    tokens and answers in 25, so any ceiling below ~4300 delivers nothing.

www.jgoy.net · https://server-nexe.org
────────────────────────────────────
"""

import asyncio
from unittest.mock import AsyncMock, MagicMock

import pytest

from plugins.ollama_module.core.chat import OllamaChat


def _chunk(content="", thinking="", done=False, done_reason=None):
    out = {"message": {"role": "assistant", "content": content, "thinking": thinking}}
    if done:
        out["done"] = True
        out["done_reason"] = done_reason
    return out


STARVED_STREAM = [
    _chunk(thinking="Let me work through"),
    _chunk(thinking=" this problem step"),
    _chunk(done=True, done_reason="length"),
]
ANSWER_STREAM = [_chunk(content="Reben 5, 11 i 31."), _chunk(done=True, done_reason="stop")]


def _chat(first, second, *, retry_raises=None):
    """Build an OllamaChat whose transport replays `first` then `second`."""
    chat = OllamaChat.__new__(OllamaChat)
    calls = []

    async def _source(_httpx, _breaker, _url, payload):
        calls.append(payload.get("think"))
        if len(calls) == 2:
            if retry_raises is not None:
                raise retry_raises
            batch = second
        else:
            batch = first
        for c in batch:
            yield c

    chat._stream_request = _source
    chat._direct_request = _source
    return chat, calls


def _drain(chat, breaker, *, stream=True):
    async def _run():
        return [
            c async for c in chat._generate_with_answer_guarantee(
                MagicMock(), breaker, "http://x/api/chat",
                {"think": True, "model": "m"}, stream, "m",
            )
        ]
    return asyncio.run(_run())


class TestAnswerGuarantee:
    def test_a_reasoning_only_turn_is_retried_without_thinking(self):
        chat, calls = _chat(STARVED_STREAM, ANSWER_STREAM)
        out = _drain(chat, MagicMock(record_failure=AsyncMock()))

        assert calls == [True, False], "the retry must ask with thinking off"
        assert any(c["message"].get("content") for c in out), "an answer must reach the client"

    def test_the_starved_done_chunk_is_not_forwarded(self):
        """It carries `done`; a consumer that sees it stops listening, and the
        retry's answer would arrive after the client already gave up."""
        chat, _ = _chat(STARVED_STREAM, ANSWER_STREAM)
        out = _drain(chat, MagicMock(record_failure=AsyncMock()))

        terminators = [c for c in out if c.get("done")]
        assert len(terminators) == 1, terminators
        assert terminators[0]["done_reason"] == "stop", "the retry's terminator, not the starved one"

    def test_a_turn_that_answered_is_never_retried(self):
        chat, calls = _chat(ANSWER_STREAM, ANSWER_STREAM)
        _drain(chat, MagicMock(record_failure=AsyncMock()))
        assert calls == [True], "one generation is enough when there is an answer"

    def test_a_turn_cut_while_answering_is_never_retried(self):
        """Content started, then the ceiling hit: that is what Continue is for,
        and a retry would throw the started answer away."""
        cut = [_chunk(thinking="brief"), _chunk(content="Reben 5, 11 i"),
               _chunk(done=True, done_reason="length")]
        chat, calls = _chat(cut, ANSWER_STREAM)
        _drain(chat, MagicMock(record_failure=AsyncMock()))
        assert calls == [True]

    def test_a_natural_stop_without_content_is_not_starvation(self):
        """No ceiling involved — retrying would not change the outcome."""
        quiet = [_chunk(thinking="hmm"), _chunk(done=True, done_reason="stop")]
        chat, calls = _chat(quiet, ANSWER_STREAM)
        _drain(chat, MagicMock(record_failure=AsyncMock()))
        assert calls == [True]

    def test_a_failing_retry_releases_the_held_chunk(self):
        """Degrade to the old behaviour, never hang: the consumer still gets a
        terminator, and the breaker still hears about the failure."""
        breaker = MagicMock(record_failure=AsyncMock())
        chat, _ = _chat(STARVED_STREAM, ANSWER_STREAM, retry_raises=RuntimeError("boom"))
        out = _drain(chat, breaker)

        assert out[-1].get("done") is True, "the turn must still terminate"
        assert out[-1]["done_reason"] == "length"
        breaker.record_failure.assert_awaited_once()


@pytest.mark.parametrize("stream", [True, False])
def test_both_transports_are_guarded(stream):
    """The blocking path starves the same way — one chunk, done, length."""
    chat, calls = _chat(STARVED_STREAM, ANSWER_STREAM)
    out = _drain(chat, MagicMock(record_failure=AsyncMock()), stream=stream)
    assert calls == [True, False]
    assert any(c["message"].get("content") for c in out)
