"""C4.6-c: `/v1` resume is the same Continue the web door already walks.

The client resends the conversation ending on the cut assistant message and
sets `resume: true`. The turn skips intent, recall and compact, the tail
merges into that message, and the client receives only the tail.
"""
from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import HTTPException

from .conftest import FAKE_ANSWER
from .test_continue_is_a_turn import PARTIAL, USER_TEXT, _MlxShaped, _cut_session

HISTORY = [
    {"role": "user", "content": USER_TEXT},
    {"role": "assistant", "content": "1 < 2"},
    {"role": "user", "content": "segueix"},
    {"role": "assistant", "content": PARTIAL + " 2 < 3 & 4"},
]


def _able(fake_engine) -> None:
    fake_engine.can_continue = lambda model_name=None: True


def _outcomes(ctx) -> list:
    return [(step, info["outcome"]) for step, info in ctx.usage["steps"].items()]


def _saved(session_manager, sid) -> list:
    session = session_manager.get_session(sid)
    return list(session.messages)


# ── the walk, and I1 ────────────────────────────────────────────────────────


async def test_a_resume_skips_the_three_steps_the_web_resume_skips(
        turn_lab, session_manager, fake_engine):
    _able(fake_engine)
    ctx = await turn_lab.api(session_id="c-walk", messages=HISTORY, resume=True)
    assert {step: outcome for step, outcome in _outcomes(ctx) if step in ("intent", "recall", "compact")} == {
        "intent": "skipped", "recall": "skipped", "compact": "skipped",
    }


async def test_api_resume_and_ui_resume_walk_the_same_sequence(
        turn_lab, session_manager, app_state, fake_engine):
    """I1 for resume: the door is a label. Same ordered outcomes."""
    _able(fake_engine)
    app_state.modules["mlx_module"] = _MlxShaped()
    _cut_session(session_manager, "c-i1-ui")
    ui = await turn_lab.ui(
        streaming=False, session_id="c-i1-ui", message="",
        body_extra={"continue": True, "backend": "mlx"},
    )
    api = await turn_lab.api(session_id="c-i1-api", messages=HISTORY, resume=True)
    assert _outcomes(api) == _outcomes(ui)


# ── what the client sees, and what the session keeps ───────────────────────


@pytest.mark.parametrize("streaming", [False, True])
async def test_the_tail_merges_and_the_client_receives_only_the_tail(
        turn_lab, session_manager, fake_engine, streaming):
    _able(fake_engine)
    sid = f"c-merge-{int(streaming)}"
    ctx = await turn_lab.api(
        session_id=sid, messages=HISTORY, resume=True, streaming=streaming,
    )
    saved = _saved(session_manager, sid)
    assert [m["role"] for m in saved] == ["user", "assistant", "user", "assistant"]
    assert saved[-1]["content"] == PARTIAL + " 2 < 3 & 4" + FAKE_ANSWER
    assert ctx.response == FAKE_ANSWER
    if not streaming:
        assert ctx.wire["choices"][0]["message"]["content"] == FAKE_ANSWER


async def test_a_tail_of_only_tags_leaves_the_partial_as_it_was(
        turn_lab, session_manager, fake_engine):
    _able(fake_engine)
    turn_lab.api_answers = ["[MEM_SAVE: a l'usuari li agrada el te verd]"]
    ctx = await turn_lab.api(session_id="c-tags", messages=HISTORY, resume=True)
    assert _saved(session_manager, "c-tags")[-1]["content"] == PARTIAL + " 2 < 3 & 4"
    assert ctx.response == ""


# ── the three mutations ─────────────────────────────────────────────────────


async def test_the_partial_is_not_escaped_and_an_older_assistant_message_is(
        turn_lab, fake_engine):
    """Mutation: escaping the partial again puts `&lt;` in the prefix."""
    _able(fake_engine)
    ctx = await turn_lab.api(session_id="c-escape", messages=HISTORY, resume=True)
    assert ctx.prompt[-1]["content"].endswith("2 < 3 & 4")
    older = next(m["content"] for m in ctx.prompt if m["content"].startswith("1 "))
    assert older == "1 &lt; 2"


async def test_a_resume_an_engine_cannot_do_is_a_400(turn_lab, session_manager, fake_engine):
    """Mutation: dropping the filter lets this engine answer and glue a tail on."""
    assert not hasattr(fake_engine, "can_continue")
    with pytest.raises(HTTPException) as exc:
        await turn_lab.api(session_id="c-unable", messages=HISTORY, resume=True)
    assert exc.value.status_code == 400
    assert "not supported" in exc.value.detail
    assert _saved(session_manager, "c-unable")[-1]["content"] == PARTIAL + " 2 < 3 & 4"


async def test_the_last_message_must_be_the_assistant_and_the_lease_stays_free(
        turn_lab, session_manager):
    with pytest.raises(HTTPException) as exc:
        await turn_lab.api(
            session_id="c-last",
            messages=[{"role": "user", "content": USER_TEXT}],
            resume=True,
        )
    assert exc.value.status_code == 400
    assert "assistant" in exc.value.detail
    session = session_manager.get_session("c-last")
    assert session is None or session.lease is None


async def test_a_resume_that_carries_an_image_is_a_400(turn_lab, session_manager):
    messages = [
        {"role": "user", "content": [
            {"type": "text", "text": "què hi ha?"},
            {"type": "image_url", "image_url": {"url": "data:image/png;base64,aGVsbG8="}},
        ]},
        {"role": "assistant", "content": PARTIAL},
    ]
    with pytest.raises(HTTPException) as exc:
        await turn_lab.api(session_id="c-image", messages=messages, resume=True)
    assert exc.value.status_code == 400
    assert exc.value.detail == "continue does not take an attachment"
    session = session_manager.get_session("c-image")
    assert session is None or session.lease is None


# ── what a resume must not insert ──────────────────────────────────────────


async def test_a_resume_does_not_inject_the_attached_document(
        turn_lab, session_manager, fake_engine):
    _able(fake_engine)
    session = session_manager.get_or_create_session("c-doc")
    session.attach_document("secret.txt", "the password is PINYA-COLADA-42")
    ctx = await turn_lab.api(session_id="c-doc", messages=HISTORY, resume=True)
    assert "PINYA-COLADA-42" not in "\n".join(m["content"] for m in ctx.prompt)


async def test_a_resume_does_not_re_detect_the_language(
        turn_lab, session_manager, fake_engine, monkeypatch):
    _able(fake_engine)
    monkeypatch.setenv("NEXE_LANG", "ca")
    session = session_manager.get_or_create_session("c-lang")
    session.lang = "en"
    ctx = await turn_lab.api(session_id="c-lang", messages=HISTORY, resume=True)
    assert ctx.lang == "en"
    assert session_manager.get_session("c-lang").lang == "en"


# ── the three engines ───────────────────────────────────────────────────────


def test_a_resume_forces_ollama_think_off(monkeypatch):
    from core.endpoints.chat_engines.ollama import _build_ollama_payload
    from core.endpoints.chat_schemas import ChatCompletionRequest

    monkeypatch.setenv("NEXE_OLLAMA_THINK", "true")
    body = ChatCompletionRequest(
        messages=[{"role": "user", "content": "hola"}, {"role": "assistant", "content": PARTIAL}],
        resume=True, reasoning_effort="high",
    )
    payload = _build_ollama_payload(body, [
        {"role": "user", "content": "hola"}, {"role": "assistant", "content": PARTIAL},
    ], "qwen3.5:9b")
    assert payload["think"] is False


async def test_mlx_resume_continues_with_thinking_off():
    from core.endpoints.chat_engines.mlx import _forward_to_mlx
    from core.endpoints.chat_schemas import ChatCompletionRequest

    module = MagicMock()
    module.chat = AsyncMock(return_value={"response": "cua", "finish_reason": "stop"})
    module._node = MagicMock()
    module._node.config.model_path = "/models/gemma-4"
    req = MagicMock()
    req.app.state.modules = {"mlx_module": module}
    body = ChatCompletionRequest(
        messages=[{"role": "user", "content": "hola"}, {"role": "assistant", "content": PARTIAL}],
        resume=True, reasoning_effort="high", stream=False,
    )
    with patch("core.endpoints.chat_engines.mlx.derive_session_id", return_value="sid"):
        await _forward_to_mlx(
            [{"role": "user", "content": "hola"}, {"role": "assistant", "content": PARTIAL}],
            body, req,
        )
    kwargs = module.chat.await_args.kwargs
    assert kwargs["continue_final"] is True
    assert kwargs["thinking_enabled"] is False


async def test_llama_cpp_resume_passes_continue_final():
    from core.endpoints.chat_engines.llama_cpp import _forward_to_llama_cpp
    from core.endpoints.chat_schemas import ChatCompletionRequest

    module = MagicMock()
    module.chat = AsyncMock(return_value={"response": "cua", "finish_reason": "stop"})
    module._node = MagicMock()
    module._node.config.model_path = "/models/model.gguf"
    req = MagicMock()
    req.app.state.modules = {"llama_cpp_module": module}
    body = ChatCompletionRequest(
        messages=[{"role": "user", "content": "hola"}, {"role": "assistant", "content": PARTIAL}],
        resume=True, stream=False,
    )
    with patch("core.endpoints.chat_engines.llama_cpp.derive_session_id", return_value="sid"):
        await _forward_to_llama_cpp(
            [{"role": "user", "content": "hola"}, {"role": "assistant", "content": PARTIAL}],
            body, req,
        )
    assert module.chat.await_args.kwargs["continue_final"] is True
