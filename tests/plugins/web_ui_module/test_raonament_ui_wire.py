"""
────────────────────────────────────
Server Nexe
Author: Jordi Goy
Location: tests/plugins/web_ui_module/test_raonament_ui_wire.py
Description: The web UI's reasoning design rests on ONE contract: the wire.

`nexe-chat.js` turns `<think>…</think>` on the wire into the collapsible
`.think-block` with its token counter, the animated "Thinking" badge and the
`data-ai-state="thinking"` frame; `_parseThinkingChannels` finds it again in
saved messages. ADR-010 moves WHERE reasoning is separated (the engine
plugins) — this pins the bytes the browser receives, captured on main
ce22b613 before any of it moved, so that design is never lost by accident.

The engine shapes:
- `field`: reasoning in its own field (Ollama's `message.thinking`) — the
  shape every engine returns after ADR-010. Shown in the block. MUST NOT CHANGE.
- `inline` / `harmony`: reasoning mixed into the content. Today the server
  drops it from the wire (only the answer is shown). After ADR-010 no engine
  should return this shape; if one does, what the UI gets is pinned here.

www.jgoy.net · https://server-nexe.org
────────────────────────────────────
"""
from unittest.mock import patch

import pytest

from tests.plugins.web_ui_module.test_mc027_response_generator_characterization import (
    _connected_request,
    _Harness,
    _join_stream,
    _make_server_state,
)


class _Engine:
    """Ollama-signature engine streaming the given raw chunks."""

    def __init__(self, chunks):
        self.chunks = chunks
        self.thinking_enabled = None

    def chat(self, model, messages, stream=False, images=None, thinking_enabled=False):
        self.thinking_enabled = thinking_enabled
        return self._stream()

    async def _stream(self):
        for c in self.chunks:
            yield c

    async def is_model_loaded(self, model_name):
        return True


def _msg(content="", thinking=None):
    m = {"content": content}
    if thinking is not None:
        m["thinking"] = thinking
    return {"message": m}


WIRE = {
    "field": (
        [_msg(thinking="raonant "), _msg(thinking="pel meu compte"), _msg("Resposta visible")],
        None,
        "\x00[MODEL_READY]\x00<think>raonant pel meu compte</think>Resposta visible",
    ),
    "inline": (
        [_msg("<think>raonament intern</think>Resposta visible")],
        None,
        "\x00[MODEL_READY]\x00Resposta visible",
    ),
    "harmony": (
        [_msg("<|channel|>analysis<|message|>pensa "),
         _msg("un moment<|end|><|start|>assistant<|channel|>final<|message|>Resposta"),
         _msg(" visible")],
        "gpt-oss:20b",
        "\x00[MODEL_READY]\x00Resposta visible",
    ),
}


async def _wire(chunks, model):
    with patch("tests.plugins.web_ui_module.test_chat_inner_behavior._mock_request", new=_connected_request):
        h = _Harness(intent="chat")
        engine = _Engine(chunks)
        body = {"message": "Pensa", "stream": True}
        if model:
            body["model"] = model
        out = await _join_stream(await h.call(body, server_state=_make_server_state(engine=engine)))
    # the MODEL header names whatever the env resolves; the rest is the contract
    return out[out.index("\x00[MODEL_READY]"):], h, engine


@pytest.mark.asyncio
@pytest.mark.parametrize("shape", list(WIRE))
async def test_the_ui_wire_for_reasoning_is_pinned(shape):
    chunks, model, expected = WIRE[shape]
    wire, _h, _e = await _wire(chunks, model)
    assert wire == expected


@pytest.mark.asyncio
async def test_the_saved_turn_keeps_only_the_answer():
    chunks, model, _expected = WIRE["field"]
    _wire_out, h, _e = await _wire(chunks, model)
    saved = [m for m in h.session.messages if m["role"] == "assistant"]
    assert saved[-1]["content"] == "Resposta visible"
