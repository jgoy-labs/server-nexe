"""#1123: the web door marks where this turn's own messages start.

The recalled context and the image note are turns of their own, placed before
the user's message, and the session keeps only the bare message: none of it is
rendered next turn. An engine that keeps its prompt cache across turns
(MLX, `plugins/mlx_module/core/vlm_runner.py`) keeps it up to the mark.
"""
from __future__ import annotations

from types import SimpleNamespace


async def test_the_web_door_marks_where_the_turn_starts(turn_lab, app_state):
    from core.turn.assemble import TURN_START_KEY

    seen = {}

    class _Engine:
        _node = SimpleNamespace(config=SimpleNamespace(model_path="/models/Qwen3.5-4B-MLX-4bit"))

        async def chat(self, messages, system="", session_id="default", stream_callback=None, **kwargs):
            seen["messages"] = messages
            stream_callback("ok")
            return {"finish_reason": "stop"}

        async def is_model_loaded(self, model_name=""):
            return True

        def can_continue(self, model_name=None):
            return True

        def can_see_images(self):
            return True

    app_state.modules = {"mlx_module": _Engine()}
    await turn_lab.ui(streaming=True, session_id="r1123-mark", message="hola")
    marked = [i for i, m in enumerate(seen["messages"]) if m.get(TURN_START_KEY)]
    assert len(marked) == 1
    assert seen["messages"][marked[0]]["role"] == "user"
    assert all(m["role"] in ("user", "assistant") for m in seen["messages"][marked[0]:])



def test_with_recalled_context_the_mark_is_on_the_context_turn():
    """The context turn and its acknowledgement come before the user's message:
    the turn starts there, not at the message."""
    from core.turn.assemble import TURN_START_KEY, PromptParts, _assemble_engine_messages

    parts = PromptParts(
        context_messages=[{"role": "user", "content": "hola"}, {"role": "assistant", "content": "Hola!"}],
        document_context="", rag_context="[MEMORIA DE L'USUARI]\nL'usuari viu a Vic.", rag_count=1, rag_items=[],
    )
    messages, _pct = _assemble_engine_messages(
        parts, "sys", "ca", "on visc?", SimpleNamespace(messages=[]), False,
    )
    marked = [i for i, m in enumerate(messages) if m.get(TURN_START_KEY)]
    assert marked == [2], [(m["role"], m["content"][:30]) for m in messages]
    assert messages[2]["role"] == "user" and "MEMORIA" in messages[2]["content"]
    assert messages[-1]["content"].endswith("on visc?")
