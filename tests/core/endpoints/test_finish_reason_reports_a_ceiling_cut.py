"""
────────────────────────────────────
Server Nexe
Author: Jordi Goy
Location: tests/core/endpoints/test_finish_reason_reports_a_ceiling_cut.py
Description: /v1 must report finish_reason="length" when the answer was cut by
    the token ceiling. Both builders used to answer "stop" unconditionally —
    the Ollama one because a blocking call always has done=True (the reason
    lives in done_reason), the shared one because it hardcoded the string. An
    OpenAI client reads finish_reason to decide whether to ask for the tail, so
    "stop" on a truncated answer loses it silently.

www.jgoy.net · https://server-nexe.org
────────────────────────────────────
"""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from core.endpoints.chat_engines._common import build_openai_response


async def _finish_reason_from(raw: dict) -> str:
    """Drive the real _ollama_blocking_response and read what it reported.

    Deliberately not a local copy of the expression: a copy passes while the
    production line is reverted to the bug, which is how this file first
    shipped.
    """
    from core.endpoints.chat_engines.ollama import _ollama_blocking_response

    response = MagicMock(status_code=200)
    response.json.return_value = {
        "model": "m", "created_at": "2026",
        "message": {"role": "assistant", "content": "…"},
        **raw,
    }
    client = AsyncMock()
    client.__aenter__.return_value.post = AsyncMock(return_value=response)
    client.__aexit__ = AsyncMock(return_value=False)

    with patch("core.endpoints.chat_engines.ollama.httpx.AsyncClient", return_value=client):
        out = await _ollama_blocking_response("http://x/api/chat", {}, None, None)
    return out["choices"][0]["finish_reason"]


@pytest.mark.asyncio
class TestOllamaBlockingFinishReason:
    async def test_a_ceiling_cut_is_reported_as_length(self):
        """Ollama sets done=True and done_reason='length' on a num_predict cut.

        `done` alone cannot tell why: a blocking call only returns once
        generation is over, so it is always True.
        """
        assert await _finish_reason_from(
            {"done": True, "done_reason": "length", "eval_count": 40}
        ) == "length"

    async def test_a_natural_stop_is_reported_as_stop(self):
        assert await _finish_reason_from(
            {"done": True, "done_reason": "stop", "eval_count": 128}
        ) == "stop"

    async def test_a_missing_done_reason_degrades_to_stop(self):
        """Older Ollama builds omit done_reason — never invent a truncation."""
        assert await _finish_reason_from({"done": True}) == "stop"


class TestSharedBuilderFinishReason:
    def test_engine_reported_length_survives_into_the_response(self):
        out = build_openai_response(
            {"response": "tallat a mig", "finish_reason": "length", "tokens": 40},
            "some-model", "mlx",
        )
        assert out["choices"][0]["finish_reason"] == "length"

    def test_a_complete_answer_stays_stop(self):
        out = build_openai_response(
            {"response": "sencer", "finish_reason": "stop", "tokens": 12},
            "some-model", "mlx",
        )
        assert out["choices"][0]["finish_reason"] == "stop"

    def test_an_engine_that_reports_nothing_degrades_to_stop(self):
        """llama.cpp does not fill the field; absence is not a truncation."""
        out = build_openai_response({"response": "sencer"}, "some-model", "llama_cpp")
        assert out["choices"][0]["finish_reason"] == "stop"

    def test_the_vlm_guess_never_becomes_a_contract_signal(self):
        """A VLM result must not report "length", however it guessed.

        mlx_vlm gives no finish_reason, so vlm_runner infers one from hitting
        the ceiling exactly — false-positive on an EOS that lands there, and
        only ever meant as an informative marker. Loading a VLM model routes
        EVERY turn through that path (the dispatch keys on model capability,
        not on the request carrying an image), so without this gate a plain
        text answer could tell a client to resume a complete reply.
        """
        out = build_openai_response(
            {"response": "descripcio", "finish_reason": "length", "vlm": True},
            "Qwen3-VL-4B-Instruct-4bit", "mlx",
        )
        assert out["choices"][0]["finish_reason"] == "stop"
