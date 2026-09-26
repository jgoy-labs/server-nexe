"""
────────────────────────────────────
Server Nexe
Author: Jordi Goy
Location: tests/core/turn/text/test_v1_stream_is_clean.py
Description: C4.4-b — /v1 streaming no longer ships the model's format.

The engine forwarders write SSE straight from the model's tokens; the core
cleans it on the one seam they share (the `generate` adapter's body wrapper).
The end-to-end test drives the REAL /chat/completions route with a fake MLX
stream whose tags are SPLIT across chunks — the case a per-chunk regex
would miss.

www.jgoy.net · https://server-nexe.org
────────────────────────────────────
"""
import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from core.endpoints.chat_engines._streaming import format_sse_chunk, format_sse_done
from core.turn.text.sse import MemTagStreamFilter, SseCleaner, ThinkTagStreamFilter
from tests.core.endpoints.test_chat_http import API_KEY, make_app

THINKING_REPLY = [
    "Hola <thi", "nk>raonament secret</th", "ink>món. [MEM_SA",
    "VE: L'usuari viu a Vic] Adéu.",
]


def _content(lines) -> str:
    out = []
    for line in lines:
        if not line.startswith("data: ") or line.strip() == "data: [DONE]":
            continue
        delta = json.loads(line[len("data: "):])["choices"][0].get("delta") or {}
        out.append(delta.get("content") or "")
    return "".join(out)


@pytest.fixture(autouse=True)
def _api_key(monkeypatch):
    monkeypatch.setenv("NEXE_PRIMARY_API_KEY", API_KEY)
    monkeypatch.delenv("NEXE_MODEL_ENGINE", raising=False)


def _stream_v1(tokens, model_path="/m/Qwen3-4B-MLX"):
    from fastapi.testclient import TestClient

    mlx_module = AsyncMock()
    mlx_module._node = MagicMock()
    mlx_module._node.config.model_path = model_path

    async def fake_gen(module, user_messages, system_msg, model_name, **kwargs):
        for t in tokens:
            yield format_sse_chunk(t, model_name, "mlx")
        yield format_sse_done(model_name, "mlx")

    with patch("core.endpoints.chat_engines.mlx._mlx_stream_generator", side_effect=fake_gen), \
         patch("memory.memory.api.v1.get_memory_api", side_effect=Exception("no")):
        client = TestClient(make_app(modules={"mlx_module": mlx_module}), raise_server_exceptions=False)
        resp = client.post(
            "/chat/completions",
            json={"messages": [{"role": "user", "content": "Hola"}], "engine": "mlx",
                  "stream": True, "use_rag": False},
            headers={"X-Api-Key": API_KEY},
        )
        return resp.status_code, list(resp.iter_lines())


def test_think_and_mem_tags_never_reach_the_sse_client():
    status, lines = _stream_v1(THINKING_REPLY)
    assert status == 200
    text = _content(lines)
    assert "raonament" not in text and "<think" not in text and "think>" not in text
    assert "MEM_SAVE" not in text and "Vic" not in text
    assert text.startswith("Hola ") and "món." in text and text.endswith("Adéu.")
    last = [ln for ln in lines if ln.startswith("data: ")][-1]
    assert json.loads(last[len("data: "):])["choices"][0]["finish_reason"] == "stop"


def test_a_harmony_stream_keeps_only_the_final_channel():
    tokens = ["<|channel|>analysis<|message|>pensa en ", "el final<|end|>",
              "<|start|>assistant<|channel|>final<|message|>Respo", "sta."]
    status, lines = _stream_v1(tokens, model_path="/m/gpt-oss-20b-MLX")
    assert status == 200
    assert _content(lines) == "Resposta."


class TestMemTagStreamFilter:
    def test_brackets_that_cannot_be_tags_pass_at_once(self):
        f = MemTagStreamFilter()
        assert f.feed("Vegeu [1] i [x") == "Vegeu [1] i [x"
        assert f.flush() == ""

    def test_a_tag_split_anywhere_is_dropped(self):
        tag = "[MEMORIA: L'usuari viu a Vic]"
        for cut in range(1, len(tag)):
            f = MemTagStreamFilter()
            assert f.feed("a " + tag[:cut]) + f.feed(tag[cut:] + " b") + f.flush() == "a  b"

    def test_an_unclosed_prefix_is_released_at_the_end(self):
        f = MemTagStreamFilter()
        assert f.feed("text [MEM") == "text "
        assert f.flush() == "[MEM"


class TestThinkTagStreamFilter:
    def test_a_block_split_anywhere_is_dropped(self):
        text = "abans <think>raonament</think> després"
        for cut in range(1, len(text)):
            f = ThinkTagStreamFilter()
            # ADR-010: the whitespace between a block and the answer goes with
            # the block (as clean_model_text has always done)
            assert f.feed(text[:cut]) + f.feed(text[cut:]) + f.flush() == "abans després"

    def test_a_lone_angle_bracket_is_text(self):
        f = ThinkTagStreamFilter()
        assert f.feed("a < b i c <th") + f.flush() == "a < b i c <th"


def test_the_cleaner_passes_non_content_events_untouched():
    c = SseCleaner("qwen3")
    assert c.rewrite(": keep-alive\n\n") == [": keep-alive\n\n"]
    assert c.rewrite(b"data: [DONE]\n\n") == [b"data: [DONE]\n\n"]


class TestV1HistoryIsSavedClean:
    """persist_v1_turn saves the model's ANSWER, like the web door does."""

    def _saved(self, text):
        from core.endpoints.chat_engines._common import persist_v1_turn

        session = MagicMock()
        state = MagicMock()
        state.session_manager.get_or_create_session.return_value = session
        persist_v1_turn(state, "s-1", text)
        return session.add_message.call_args.args[1]

    def test_think_and_tags_are_not_saved(self):
        saved = self._saved("<think>raonament</think>Resposta. [MEM_SAVE: L'usuari viu a Vic]")
        assert saved == "Resposta."

    def test_a_think_only_reply_keeps_its_turn(self):
        assert self._saved("<think>només pensa</think>") == "…"


def test_nested_blocks_split_anywhere_are_dropped_whole():
    text = "<think>repeteix <think>SECRET</think> i adéu</think>\n\nHola món"
    for cut in range(1, len(text)):
        f = ThinkTagStreamFilter()
        assert f.feed(text[:cut]) + f.feed(text[cut:]) + f.flush() == "Hola món"
