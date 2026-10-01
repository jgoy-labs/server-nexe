"""
────────────────────────────────────
Server Nexe
Author: Jordi Goy
Location: tests/core/turn/test_continue_is_a_turn.py
Description: C4.6 — the web door's Continue (FD-S6) is a turn, not a second
             pipeline. It walks TURN_STEPS with `resume` set: `intent`,
             `recall` and `compact` skipped by policy, the lease taken, the
             engine gate and the I8 accounting like any turn, the tail merged
             into the answer it continues, disk before memory.

Real adapter tables through `turn_lab`; the engine is an MLX-shaped double
(queue + stream_callback) that records what it was asked, because only an
engine that declares `can_continue` is offered a resume.

www.jgoy.net · https://server-nexe.org
────────────────────────────────────
"""
import json
from pathlib import Path

import pytest
from fastapi import HTTPException

from .conftest import LAB_PRINCIPAL, door_patches, make_request

PARTIAL = "Una resposta tall"
USER_TEXT = "Explica'm una història curta, sisplau."


class _MlxShaped:
    """`chat(messages, system=…, stream_callback=…)` like the MLX module: the
    tokens go through the callback, the result dict comes back at the end."""

    def __init__(self, tokens=("ada", " i acabada."), result=None, resumable=True):
        self.tokens = tuple(tokens)
        self.result = result or {"finish_reason": "stop"}
        self.resumable = resumable
        self.calls: list[dict] = []
        self._node = object()  # a serviceable mlx module has a live node

    async def chat(self, messages, system="", session_id="default", stream_callback=None, **kwargs):
        self.calls.append({"messages": list(messages), "system": system, **kwargs})
        for token in self.tokens:
            if callable(stream_callback):
                stream_callback(token)
        return dict(self.result)

    async def is_model_loaded(self, model_name):
        return True

    def can_continue(self, model_name=None):
        return self.resumable


@pytest.fixture
def mlx(app_state):
    engine = _MlxShaped()
    app_state.modules = {"mlx_module": engine}
    return engine


def _cut_session(session_manager, sid, *, stats=None, lang=None, earlier=False, image=None):
    """A conversation whose last answer was cut by the token ceiling.

    `earlier` puts one exchange before it: memory treats a conversation's
    first turn apart (only facts grounded in the user's own words, #831), and
    a resume adds no user message — so a one-exchange session is still turn 1.
    """
    session = session_manager.get_or_create_session(sid)
    if earlier:
        session.add_message("user", "Hola!")
        session.add_message("assistant", "Hola! En què et puc ajudar?")
    session.add_message("user", USER_TEXT, image_b64=image, image_type="image/png" if image else None)
    session.add_message("assistant", PARTIAL, stats=stats or {})
    session.messages[-1]["gen_raw"] = PARTIAL
    if lang:
        session.lang = lang
    session_manager._save_session_to_disk(session)
    return session


def _on_disk(session_manager, sid) -> dict:
    return json.loads((Path(session_manager._storage_path) / f"{sid}.json").read_text(encoding="utf-8"))


RESUME = {"continue": True, "backend": "mlx"}


async def _resume(turn_lab, sid, *, streaming=True):
    return await turn_lab.ui(streaming=streaming, session_id=sid, message="", body_extra=RESUME)


# ── the walk ────────────────────────────────────────────────────────────────


@pytest.mark.parametrize("streaming", [True, False])
async def test_a_resume_walks_the_turn_with_three_steps_skipped_and_none_folded(
        turn_lab, session_manager, mlx, streaming):
    sid = f"c46-walk-{int(streaming)}"
    _cut_session(session_manager, sid)
    ctx = await _resume(turn_lab, sid, streaming=streaming)

    assert {s: ctx.outcomes[s] for s in ("intent", "recall", "compact")} == dict.fromkeys(
        ("intent", "recall", "compact"), "skipped")
    others = {s: o for s, o in ctx.outcomes.items() if s not in ("intent", "recall", "compact", "memory.write")}
    assert set(others.values()) == {"ok"}, others
    assert not ctx.usage.get("folded"), ctx.usage.get("folded")


async def test_the_engine_is_asked_to_continue_from_the_exact_cut(turn_lab, session_manager, mlx):
    _cut_session(session_manager, "c46-cut")
    await _resume(turn_lab, "c46-cut")
    call = mlx.calls[-1]
    assert call.get("continue_final") is True
    assert call["messages"][-1] == {"role": "assistant", "content": PARTIAL}


async def test_llama_cpp_is_asked_to_continue_from_the_exact_cut(turn_lab, session_manager, app_state):
    """#1107: the web door no longer refuses llama.cpp. The cascade offers it
    because the double declares `can_continue`, and the kwarg arrives."""
    engine = _MlxShaped()
    app_state.modules = {"llama_cpp_module": engine}
    _cut_session(session_manager, "c46-llama")
    await turn_lab.ui(
        streaming=True, session_id="c46-llama", message="",
        body_extra={"continue": True, "backend": "llama_cpp"},
    )
    call = engine.calls[-1]
    assert call.get("continue_final") is True
    assert call["messages"][-1] == {"role": "assistant", "content": PARTIAL}


@pytest.mark.parametrize("streaming", [True, False])
async def test_the_tail_merges_into_the_answer_it_continues_and_reaches_disk(
        turn_lab, session_manager, mlx, streaming):
    sid = f"c46-merge-{int(streaming)}"
    _cut_session(session_manager, sid)
    await _resume(turn_lab, sid, streaming=streaming)
    messages = _on_disk(session_manager, sid)["messages"]
    assert [m["role"] for m in messages] == ["user", "assistant"], "no new turn, no new user message"
    assert messages[-1]["content"] == PARTIAL + "ada i acabada."


async def test_the_json_tail_is_cleaned_before_it_merges(turn_lab, session_manager, mlx):
    mlx.tokens = ("<think>pensa</think>", "ada.")
    _cut_session(session_manager, "c46-clean")
    await _resume(turn_lab, "c46-clean", streaming=False)
    assert _on_disk(session_manager, "c46-clean")["messages"][-1]["content"] == PARTIAL + "ada."


# ── what a turn gets that the legacy path skipped ─────────────────────────


async def test_a_resume_takes_the_lease(turn_lab, session_manager, mlx):
    _cut_session(session_manager, "c46-lease")
    session_manager.acquire_lease("c46-lease", holder="api", turn_id="another-device", where="API")
    with pytest.raises(HTTPException) as exc:
        await _resume(turn_lab, "c46-lease")
    assert exc.value.status_code == 409


async def test_a_resume_is_counted_in_the_turns_budget(turn_lab, session_manager, mlx):
    _cut_session(session_manager, "c46-i8")
    ctx = await _resume(turn_lab, "c46-i8")
    assert [c["step"] for c in ctx.usage["llm"]["calls"]] == ["generate"]


async def test_a_resume_writes_disk_before_memory(turn_lab, session_manager, memory_helper, mlx):
    """I3 with resume=True: when memory stores the tail's fact, the merged
    answer is already on disk (the legacy path wrote memory first)."""
    mlx.tokens = ("ada. [MEM_SAVE: a l'usuari li agrada el te verd]",)
    _cut_session(session_manager, "c46-i3", earlier=True)
    seen_on_disk = []

    async def _save(*_args, **_kwargs):
        seen_on_disk.append(_on_disk(session_manager, "c46-i3")["messages"][-1]["content"])
        return {"success": True, "document_id": "doc-1"}

    memory_helper.save_to_memory.side_effect = _save
    await _resume(turn_lab, "c46-i3")
    assert seen_on_disk, "the tail's fact must reach memory"
    assert seen_on_disk[0].startswith(PARTIAL + "ada.")


async def test_what_the_tail_keeps_adds_to_what_the_answer_kept(turn_lab, session_manager, memory_helper, mlx):
    mlx.tokens = ("ada. [MEM_SAVE: a l'usuari li agrada el te verd]",)
    _cut_session(session_manager, "c46-stats", stats={"mem_saved": 1, "mem_facts": ["l'usuari viu a Girona"]},
                 earlier=True)
    await _resume(turn_lab, "c46-stats")
    stats = _on_disk(session_manager, "c46-stats")["messages"][-1]["stats"]
    assert stats["mem_saved"] == 2
    assert stats["mem_facts"][0] == "l'usuari viu a Girona" and len(stats["mem_facts"]) == 2


# ── refusals ──────────────────────────────────────────────────────────────


async def test_nothing_to_resume_is_a_400_before_the_lease(turn_lab, session_manager, mlx):
    session = session_manager.get_or_create_session("c46-nothing")
    session.add_message("user", USER_TEXT)
    with pytest.raises(HTTPException) as exc:
        await _resume(turn_lab, "c46-nothing")
    assert exc.value.status_code == 400 and "assistant" in exc.value.detail
    granted = session_manager.acquire_lease("c46-nothing", holder="ui", turn_id="next", where="t").granted
    assert granted, "a refused Continue must not hold the session"


async def test_an_engine_that_cannot_resume_is_a_400_not_a_new_answer(turn_lab, session_manager, fake_engine):
    """The generic double declares no `can_continue`: before C4.6 it would have
    been sent the Continue and answered from scratch, glued onto the cut."""
    _cut_session(session_manager, "c46-cannot")
    with pytest.raises(HTTPException) as exc:
        await turn_lab.ui(streaming=True, session_id="c46-cannot", message="",
                          body_extra={"continue": True, "backend": "ollama"})
    assert exc.value.status_code == 400 and "not supported" in exc.value.detail
    assert fake_engine.calls == 0


# ── what a resume must not do ─────────────────────────────────────────────


async def test_a_tail_of_only_tags_merges_nothing_and_asks_nothing_more(turn_lab, session_manager, mlx):
    mlx.tokens = ("[MEM_SAVE: a l'usuari li agrada el te verd]",)
    _cut_session(session_manager, "c46-tags")
    ctx = await _resume(turn_lab, "c46-tags")
    assert len(mlx.calls) == 1, "no second generation inside a sentence being resumed"
    assert _on_disk(session_manager, "c46-tags")["messages"][-1]["content"] == PARTIAL
    assert "D'acord" not in "".join(c for c in ctx.lab_wire_chunks if isinstance(c, str))


async def test_a_resume_does_not_re_detect_the_language(turn_lab, session_manager, mlx):
    _cut_session(session_manager, "c46-lang", lang="en")  # the last user text is Catalan
    ctx = await _resume(turn_lab, "c46-lang")
    assert ctx.lang == "en"
    assert session_manager.get_or_create_session("c46-lang").lang == "en"


async def test_stop_mid_resume_keeps_the_merged_tail_on_disk(app_state, session_manager, memory_helper,
                                                             server_state, mlx):
    """#1106: the merge branch of an interrupted Continue now saves to disk."""
    from core.turn.context import TurnContext
    from core.turn.run import stream_turn
    from plugins.web_ui_module.api.turn_adapters import ui_adapters

    mlx.tokens = ("ada", " i", " més", " coses")
    _cut_session(session_manager, "c46-stop")
    ctx = TurnContext(
        turn_id="turn-c46-stop", entry="ui", principal=LAB_PRINCIPAL, resume=True,
        body={"message": "", "session_id": "c46-stop", "stream": True, **RESUME},
        request=make_request(app_state), app_state=app_state,
    )
    with door_patches(server_state, memory_helper):
        body = await stream_turn(ctx, ui_adapters(session_manager, streaming=True))
        async for chunk in body:
            if isinstance(chunk, str) and chunk and not chunk.startswith("\x00"):
                break  # the user clicks Stop after the first word of the tail
        await body.aclose()

    messages = _on_disk(session_manager, "c46-stop")["messages"]
    assert [m["role"] for m in messages] == ["user", "assistant"]
    assert messages[-1]["content"].startswith(PARTIAL + "ada")
    # The raw prefix survives the Stop: the next Continue still ends inside
    # the cut answer, not inside its cleaned re-render.
    assert messages[-1]["gen_raw"].startswith(PARTIAL + "ada")


async def test_both_wire_shapes_of_a_resume_walk_the_same_sequence(turn_lab, session_manager, mlx):
    """I1 for resume: streaming and JSON are one turn, only `emit` differs."""
    _cut_session(session_manager, "c46-i1-s")
    _cut_session(session_manager, "c46-i1-j")
    stream = await _resume(turn_lab, "c46-i1-s", streaming=True)
    json_ = await _resume(turn_lab, "c46-i1-j", streaming=False)
    seq = lambda c: [(s, v["outcome"]) for s, v in c.usage["steps"].items()]  # noqa: E731
    assert seq(stream) == seq(json_)


# ── a failure before the first byte still has a cascade ───────────────────


class _RefusesImageContinue(_MlxShaped):
    """llama.cpp: an image already on the cut turn cannot be resumed here."""

    async def chat(self, messages, system="", session_id="default", stream_callback=None, **kwargs):
        self.calls.append({"messages": list(messages), "system": system, **kwargs})
        if kwargs.get("continue_final") and kwargs.get("images"):
            raise RuntimeError("continue with images is not supported by llama.cpp")
        return await super().chat(messages, system, session_id, stream_callback, **kwargs)


def _visible(ctx) -> str:
    return "".join(c for c in ctx.lab_wire_chunks if isinstance(c, str) and not c.startswith("\x00"))


async def test_an_image_continue_on_llama_is_offered_to_mlx_before_any_byte(
        turn_lab, session_manager, app_state, mlx):
    """The refusal used to land inside an already-open stream, so the client
    saw the generic error and MLX was never asked."""
    llama = _RefusesImageContinue()
    app_state.modules = {"llama_cpp_module": llama, "mlx_module": mlx}
    _cut_session(session_manager, "c46-img", image="aGVsbG8=")
    ctx = await turn_lab.ui(
        streaming=True, session_id="c46-img", message="",
        body_extra={"continue": True, "backend": "llama_cpp"},
    )
    assert llama.calls and llama.calls[0].get("continue_final") is True
    assert llama.calls[0].get("images")
    assert mlx.calls and mlx.calls[0].get("continue_final") is True
    visible = _visible(ctx)
    assert "ada" in visible
    assert "error en generar" not in visible
    assert ctx.usage["llm"]["calls"][-1]["engine"] == "mlx"


class _DiesBeforeAByte:
    """Ollama's shape: `chat(model, …)` returns a generator that fails on pull."""

    def __init__(self):
        self.calls = 0

    def chat(self, model, messages, stream=False, **kwargs):
        self.calls += 1

        async def _gen():
            raise RuntimeError("model gone")
            yield ""  # pragma: no cover — makes this an async generator

        return _gen()


class _DiesAfterAToken(_DiesBeforeAByte):
    def chat(self, model, messages, stream=False, **kwargs):
        self.calls += 1

        async def _gen():
            yield "mig"
            raise RuntimeError("died mid-answer")

        return _gen()


async def test_a_generator_that_fails_before_a_byte_is_offered_to_the_next_engine(
        turn_lab, session_manager, app_state, mlx):
    dead = _DiesBeforeAByte()
    app_state.modules = {"ollama_module": dead, "mlx_module": mlx}
    ctx = await turn_lab.ui(
        streaming=True, session_id="c4-prebyte", message="hola",
        body_extra={"backend": "ollama"},
    )
    assert dead.calls == 1
    assert mlx.calls
    assert "ada" in _visible(ctx)
    assert "error en generar" not in _visible(ctx)
    assert ctx.usage["llm"]["calls"][-1]["engine"] == "mlx"


async def test_a_generator_that_fails_after_a_token_keeps_the_stream(
        turn_lab, session_manager, app_state, mlx):
    """Once a byte is out, the turn is that engine's. The next one stays quiet."""
    dead = _DiesAfterAToken()
    app_state.modules = {"ollama_module": dead, "mlx_module": mlx}
    ctx = await turn_lab.ui(
        streaming=True, session_id="c4-midbyte", message="hola",
        body_extra={"backend": "ollama"},
    )
    assert dead.calls == 1
    assert mlx.calls == []
    visible = _visible(ctx)
    assert "mig" in visible
    assert "error en generar" in visible


async def test_a_resumed_answer_about_an_image_is_resumed_with_that_image(turn_lab, session_manager, mlx):
    """C4.6-a-vlm: a vision model continuing without the image would be
    describing from memory — and its prompt would not be the one it was cut from."""
    _cut_session(session_manager, "c46-img", image="aW1hdGdl")
    await _resume(turn_lab, "c46-img")
    assert mlx.calls[-1].get("images") == ["aW1hdGdl"]


async def test_a_resume_without_an_image_sends_none(turn_lab, session_manager, mlx):
    _cut_session(session_manager, "c46-noimg")
    await _resume(turn_lab, "c46-noimg")
    assert not mlx.calls[-1].get("images")
