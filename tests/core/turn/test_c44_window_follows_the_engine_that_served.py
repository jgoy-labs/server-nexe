"""
────────────────────────────────────
Server Nexe
Author: Jordi Goy
Location: tests/core/turn/test_c44_window_follows_the_engine_that_served.py
Description: C4.4 — `ctx.context_window` is the SERVING engine's window
             (core/turn/context.py). It was set at `engine` against the first
             candidate and never refreshed when a fallback engine answered.

www.jgoy.net · https://server-nexe.org
────────────────────────────────────
"""
from unittest.mock import MagicMock, patch

import pytest

from core.turn.context import TurnContext
from plugins.web_ui_module.api.turn_adapters import _serve_with

WINDOWS = {"ollama": 32768, "llama_cpp": 4096}


async def test_v1_fallback_refreshes_the_window(turn_lab):
    from core.endpoints.chat_engines._common import build_openai_response

    reply = build_openai_response({"response": "hola"}, "m", "llama_cpp")

    async def _cascade(*_a, **_k):
        return reply, "llama_cpp", "ollama", "unavailable", "m"

    with patch("core.endpoints.chat._dispatch_through_cascade", _cascade), \
         patch("core.endpoints.chat.get_effective_context_window",
               lambda engine, _state: WINDOWS.get(engine, 1)):
        ctx = await turn_lab.api(session_id="s-c44-window")

    assert ctx.engine == "llama_cpp"
    assert ctx.context_window == WINDOWS["llama_cpp"]


class TestWebDoor:
    def _ctx(self):
        ctx = TurnContext(turn_id="t", entry="ui")
        ctx.context_window = WINDOWS["ollama"]
        return ctx

    def test_a_fallback_engine_brings_its_window(self):
        first, fallback = MagicMock(name="mlx"), MagicMock(name="ollama")
        ctx = self._ctx()
        with patch("core.context_window.ask_engine_window", lambda e: 4096 if e is fallback else 1):
            _serve_with(ctx, fallback, {"candidates": [("mlx", first), ("ollama", fallback)]})
        assert ctx.engine is fallback
        assert ctx.context_window == 4096

    def test_the_first_candidate_keeps_the_window_already_asked(self):
        first = MagicMock(name="mlx")
        ctx = self._ctx()
        with patch("core.context_window.ask_engine_window", side_effect=AssertionError("asked twice")):
            _serve_with(ctx, first, {"candidates": [("mlx", first)]})
        assert ctx.context_window == WINDOWS["ollama"]


pytestmark = pytest.mark.filterwarnings("ignore::DeprecationWarning")
