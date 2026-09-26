"""
────────────────────────────────────
Server Nexe
Author: Jordi Goy
Location: tests/core/endpoints/test_adr010_v1_reasoning.py
Description: ADR-010 at /v1 — the model reasons only when the request asks
             (`reasoning_effort` / `reasoning.effort`), and its reasoning
             comes back as `reasoning`, apart from `content`. Absent = off,
             like the web UI (decision of 25/09).

www.jgoy.net · https://server-nexe.org
────────────────────────────────────
"""
import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import BackgroundTasks

from core.endpoints.chat_engines._streaming import format_engine_token, format_sse_done
from core.endpoints.chat_schemas import ChatCompletionRequest
from core.turn.adapters_api import api_adapters
from core.turn.context import TurnContext
from core.turn.reasoning import structured_chunk
from tests.core.endpoints.test_chat_http import API_KEY, make_app


def _req(**extra):
    return ChatCompletionRequest(messages=[{"role": "user", "content": "hola"}], **extra)


@pytest.mark.parametrize("extra,wanted", [
    ({}, False),
    ({"reasoning_effort": "none"}, False),
    ({"reasoning_effort": "low"}, True),
    ({"reasoning_effort": "HIGH"}, True),
    ({"reasoning": {"effort": "medium"}}, True),
    ({"reasoning": {"effort": "none"}}, False),
])
def test_the_request_decides_and_absent_is_off(extra, wanted):
    assert _req(**extra).wants_reasoning() is wanted


# ── streaming, end to end through the real route ────────────────────────────

@pytest.fixture(autouse=True)
def _api_key(monkeypatch):
    monkeypatch.setenv("NEXE_PRIMARY_API_KEY", API_KEY)
    monkeypatch.delenv("NEXE_MODEL_ENGINE", raising=False)
    monkeypatch.delenv("NEXE_OLLAMA_THINK", raising=False)


CHUNKS = [
    structured_chunk("", "pensa ", raw="pensa "),
    structured_chunk("", "un moment", raw="un moment</think>"),
    structured_chunk("Resposta", "", raw="Resposta"),
    structured_chunk(" final.", "", raw=" final."),
]


def _stream(extra):
    from fastapi.testclient import TestClient

    mlx_module = AsyncMock()
    mlx_module._node = MagicMock()
    mlx_module._node.config.model_path = "/m/Qwen3.5-9B-MLX"
    seen = {}

    async def fake_gen(module, user_messages, system_msg, model_name, **kwargs):
        seen["thinking_enabled"] = kwargs.get("thinking_enabled")
        for c in CHUNKS:
            sse = format_engine_token(c, model_name, "mlx")
            if sse:
                yield sse
        yield format_sse_done(model_name, "mlx")

    with patch("core.endpoints.chat_engines.mlx._mlx_stream_generator", side_effect=fake_gen), \
         patch("memory.memory.api.v1.get_memory_api", side_effect=Exception("no")):
        client = TestClient(make_app(modules={"mlx_module": mlx_module}), raise_server_exceptions=False)
        resp = client.post("/chat/completions", headers={"X-Api-Key": API_KEY}, json={
            "messages": [{"role": "user", "content": "hola"}], "engine": "mlx",
            "stream": True, "use_rag": False, **extra,
        })
    content, reasoning = "", ""
    for line in resp.iter_lines():
        if line.startswith("data: ") and line.strip() != "data: [DONE]":
            delta = json.loads(line[6:])["choices"][0].get("delta") or {}
            content += delta.get("content") or ""
            reasoning += delta.get("reasoning") or ""
    return content, reasoning, seen


def test_asked_the_reasoning_streams_apart_from_the_answer():
    content, reasoning, seen = _stream({"reasoning_effort": "medium"})
    assert seen["thinking_enabled"] is True
    assert (reasoning, content) == ("pensa un moment", "Resposta final.")


def test_not_asked_the_model_is_told_not_to_and_nothing_comes_back():
    content, reasoning, seen = _stream({})
    assert seen["thinking_enabled"] is False
    assert (reasoning, content) == ("", "Resposta final.")


# ── JSON: the postprocess step ──────────────────────────────────────────────

def _wire(message):
    return {"choices": [{"index": 0, "message": message, "finish_reason": "stop"}]}


@pytest.mark.parametrize("wanted", [True, False])
async def test_json_reasoning_is_kept_only_when_asked(wanted):
    table = api_adapters(BackgroundTasks())
    ctx = TurnContext(turn_id="t", entry="api")
    ctx.body = _req(**({"reasoning_effort": "low"} if wanted else {}))
    ctx.wire = _wire({"role": "assistant", "content": "<think>inline</think>Resposta.",
                      "reasoning": "del motor. "})
    await table["postprocess"](ctx)
    message = ctx.wire["choices"][0]["message"]
    assert message["content"] == "Resposta."
    if wanted:
        assert message["reasoning"] == "del motor. inline"
    else:
        assert "reasoning" not in message


# ── Ollama: its native `thinking`, and a model that refuses to reason ──────

def test_ollama_thinking_becomes_reasoning():
    from core.endpoints.chat_engines.ollama import _openai_message

    out = _openai_message({"role": "assistant", "content": "Hola", "thinking": "raona"})
    assert out == {"role": "assistant", "content": "Hola", "reasoning": "raona"}


def test_ollama_think_follows_the_request_unless_the_env_says(monkeypatch):
    from core.endpoints.chat_engines.ollama import _think_for

    assert _think_for(_req()) is False
    assert _think_for(_req(reasoning_effort="low")) is True
    monkeypatch.setenv("NEXE_OLLAMA_THINK", "false")
    assert _think_for(_req(reasoning_effort="low")) is False


async def test_ollama_retries_without_thinking_when_the_model_refuses():
    from core.endpoints.chat_engines.ollama import _ollama_blocking_response

    posted = []

    def _resp(status, body):
        r = MagicMock(status_code=status)
        r.json.return_value = body
        return r

    async def post(url, json=None, timeout=None):
        posted.append(json["think"])
        if json["think"]:
            return _resp(400, {"error": "model does not support thinking"})
        return _resp(200, {"model": "gemma3:4b", "message": {"role": "assistant", "content": "Hola"},
                           "done_reason": "stop"})

    client = MagicMock()
    client.post = post
    client.__aenter__ = AsyncMock(return_value=client)
    client.__aexit__ = AsyncMock(return_value=False)
    with patch("httpx.AsyncClient", return_value=client):
        out = await _ollama_blocking_response("http://x/api/chat", {"model": "gemma3:4b", "think": True}, None, None)
    assert posted == [True, False]
    assert out["choices"][0]["message"]["content"] == "Hola"
