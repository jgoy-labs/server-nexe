"""
────────────────────────────────────
Server Nexe
Author: Jordi Goy
Location: tests/core/turn/test_c46_a2_ollama_door.py
Description: C4.6-a2 — a web Continue against an Ollama-shaped engine passes
             continue_final and merges the tail. An unmeasured model is a 400,
             not a new answer glued onto the cut one.

www.jgoy.net · https://server-nexe.org
────────────────────────────────────
"""
import json
from pathlib import Path

import pytest
from fastapi import HTTPException

from plugins.ollama_module.core.chat import model_can_continue

PARTIAL = "Una resposta tall"
USER_TEXT = "Explica'm una història curta, sisplau."


class _OllamaShaped:
    """`chat(model, messages, …, continue_final=)` like OllamaModule.

    `can_continue` is the real family check, so a name that was not measured
    never reaches `chat`.
    """

    def __init__(self, tail="cua"):
        self.tail = tail
        self.calls: list[dict] = []

    def can_continue(self, model_name=None):
        return model_can_continue(model_name)

    async def chat(self, model, messages, stream=True, images=None, thinking_enabled=False,
                   top_p=None, continue_final=False):
        self.calls.append({
            "model": model, "messages": [dict(m) for m in messages],
            "continue_final": continue_final,
        })
        yield {"message": {"content": self.tail}}
        yield {"done": True, "done_reason": "stop"}

    async def is_model_loaded(self, model_name):
        return True


@pytest.fixture
def ollama(app_state):
    engine = _OllamaShaped()
    app_state.modules = {"ollama_module": engine}
    return engine


def _cut_session(session_manager, sid):
    session = session_manager.get_or_create_session(sid)
    session.add_message("user", USER_TEXT)
    session.add_message("assistant", PARTIAL)
    session.messages[-1]["gen_raw"] = PARTIAL
    session_manager._save_session_to_disk(session)
    return session


def _on_disk(session_manager, sid) -> dict:
    return json.loads((Path(session_manager._storage_path) / f"{sid}.json").read_text(encoding="utf-8"))


@pytest.mark.parametrize("streaming", [True, False])
async def test_a_web_continue_merges_the_tail_and_asks_ollama_to_resume(
        turn_lab, session_manager, ollama, streaming):
    sid = f"c46-a2-{int(streaming)}"
    _cut_session(session_manager, sid)
    await turn_lab.ui(
        streaming=streaming, session_id=sid, message="",
        body_extra={"continue": True, "backend": "ollama", "model": "qwen3.5:4b"},
    )
    call = ollama.calls[-1]
    assert call["continue_final"] is True
    assert call["model"] == "qwen3.5:4b"
    assert call["messages"][-1]["role"] == "assistant"
    assert call["messages"][-1]["content"] == PARTIAL
    messages = _on_disk(session_manager, sid)["messages"]
    assert [m["role"] for m in messages] == ["user", "assistant"]
    assert messages[-1]["content"] == PARTIAL + "cua"


async def test_an_unmeasured_ollama_model_is_a_400_and_is_not_called(
        turn_lab, session_manager, ollama):
    _cut_session(session_manager, "c46-a2-no")
    with pytest.raises(HTTPException) as exc:
        await turn_lab.ui(
            streaming=True, session_id="c46-a2-no", message="",
            body_extra={"continue": True, "backend": "ollama", "model": "qwen3-coder-next"},
        )
    assert exc.value.status_code == 400
    assert ollama.calls == []
