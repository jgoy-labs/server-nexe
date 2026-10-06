"""C4.8 part 0 — the rows: each difference between the two doors, written as one.

`test_c48_p0_matrix.py` pins the grid. This file pins what the grid cannot say
in one line, one test per row of the review of 04/10
(`revisio-pla-c4-8-contra-main-20261004.md`), and the rows that review added in
§E: the re-prompt, `describe_image` (#1144), `compact` against the engine that
failed, `[MODEL:]` / `[ENGINE:]`, and an image at `/v1` that skips the engines
that cannot see it.

Every test says which row it is. Each states what the doors do TODAY, door by
door, so a later part of C4.8 changes exactly the test whose row Jordi decided:
B1-B7 (the body of the loop), R1-R4 (re-prompt, `/v1` 404, empty answer,
`/v1` without live engines), Q (no engine answers), D2/D3 (what is shown).

The engines and the doors are the lab's (`_c48_p0_lab.py`).
"""
from __future__ import annotations

import asyncio
from pathlib import Path
from unittest.mock import patch

import pytest
from fastapi import FastAPI, Request
from fastapi.testclient import TestClient

from core.metrics.registry import REGISTRY
from core.turn import image_memory, policy

from plugins.web_ui_module.api.wire import _stream_error_notice

from ._c48_p0_lab import (
    DOORS, LLAMA_MODEL, MLX_MODEL, OOM, FakeOllamaDaemon, InProc, OllamaModule, World, build_world, run_door,
)
from .conftest import door_patches
from .test_1144_image_memory import _image_part, _is_description, _png
from .test_continue_is_a_turn import PARTIAL, USER_TEXT, _cut_session

V1 = ("v1_json", "v1_stream")
UI = ("ui_json", "ui_stream")

MLX_NAME = MLX_MODEL
GGUF_NAME = LLAMA_MODEL


def _prompt_chars(prompt: list) -> int:
    return sum(len(m.get("content") or "") for m in prompt)


# ───────────────────────────────────────────────────────────────────── B1 ──

def _long_history(pairs: int = 40) -> list:
    history = []
    for number in range(pairs):
        history.append({"role": "user", "content": f"pregunta {number} " + "x" * 1000})
        history.append({"role": "assistant", "content": f"resposta {number} " + "y" * 1000})
    return history


async def _fallback_prompt(lab, door: str, max_tokens: int | None) -> int:
    """Characters the 2048-token fallback is given when the 32k engine in front fails."""
    world = build_world({"mlx": "pre_byte"}, live=["mlx", "llama_cpp"])
    world.engines["mlx"].get_context_window = lambda: 32768
    world.engines["llama_cpp"].get_context_window = lambda: 2048
    sid = f"b1-{door}-{max_tokens}"
    if door.startswith("v1"):
        extra = {"max_tokens": max_tokens} if max_tokens else None
        messages = _long_history() + [{"role": "user", "content": "i ara?"}]
        await run_door(lab, world, door, backend="mlx", sid=sid, messages=messages, extra=extra)
    else:
        session = lab.session_manager.get_or_create_session(sid)
        for message in _long_history():
            session.add_message(message["role"], message["content"])
        lab.session_manager._save_session_to_disk(session)
        await run_door(lab, world, door, backend="mlx", sid=sid, message="i ara?")
    return _prompt_chars(world.engines["llama_cpp"].prompts[0])


@pytest.mark.parametrize("door", V1)
async def test_b1_v1_refits_a_fallback_with_a_reserve_of_max_tokens(turn_lab, door):
    """ROW B1. `/v1`: the reply reserve is what the client asked for."""
    unbounded = await _fallback_prompt(turn_lab, door, None)
    asked_1000 = await _fallback_prompt(turn_lab, door, 1000)
    assert unbounded <= 2048 * 4
    # 1000 tokens held back for the reply, ~4 chars each, come out of the prompt
    assert unbounded - asked_1000 >= 3500


@pytest.mark.parametrize("door", UI)
async def test_b1_web_refits_a_fallback_with_a_fixed_reserve_of_125_tokens(turn_lab, door):
    """ROW B1. Web: `_refit_for` holds back 500 chars (125 tokens) whatever the
    reply may need, and only fallbacks are refitted (the first engine's prompt
    was fitted by `budget`). Between the two `/v1` cases above: more than the one
    that reserves 1000 tokens, and it still fits the window."""
    web = await _fallback_prompt(turn_lab, door, None)
    v1_reserving_1000 = await _fallback_prompt(turn_lab, "v1_json", 1000)
    assert web <= 2048 * 4
    assert web > v1_reserving_1000


async def _reserves_at_2048(lab, door: str, max_tokens: int | None) -> list:
    """The reply reserve (tokens) each refit of the 2048-token fallback asked for."""
    import core.context_budget as budget

    real, reserves = budget.fit_prompt_to_window, []

    def _spy(system, turns, window_tokens, *args, **kwargs):
        if window_tokens == 2048:
            reserves.append(kwargs.get("reply_budget_tokens"))
        return real(system, turns, window_tokens, *args, **kwargs)

    with patch.object(budget, "fit_prompt_to_window", _spy):
        await _fallback_prompt(lab, door, max_tokens)
    return reserves


@pytest.mark.parametrize("door,max_tokens,reserve", [
    ("v1_json", None, 0), ("v1_json", 1000, 1000), ("v1_stream", 1000, 1000),
    ("ui_json", None, 125), ("ui_stream", None, 125),
])
async def test_b1_the_reserve_each_door_holds_back_for_the_reply(turn_lab, door, max_tokens, reserve):
    """ROW B1, in tokens. `/v1` holds back what the client asked for (`max_tokens`, 0
    when it did not); the web holds back 500 // 4 = 125, always."""
    assert await _reserves_at_2048(turn_lab, door, max_tokens) == [reserve]


# ───────────────────────────────────────────────────────────────────── B2 ──

@pytest.mark.parametrize("door", DOORS)
async def test_b2_the_first_engine_is_switched_to_the_requested_model_only_on_the_web(turn_lab, door):
    """ROW B2 (candidate 0, still open in D1). The web loads the model the body
    names into the engine it asked for; `/v1` never switches (B075-C3)."""
    world = build_world(live=["mlx"])
    await run_door(turn_lab, world, door, backend="mlx", sid=f"b2a-{door}", extra={"model": MLX_NAME})
    switched = world.engines["mlx"].switched_to
    if door.startswith("ui"):
        assert Path(switched).name == MLX_NAME
    else:
        assert switched is None


@pytest.mark.parametrize("door", DOORS)
async def test_b2_a_fallback_keeps_its_own_loaded_model_at_both_doors(turn_lab, door):
    """ROW B2 (#1035, decided 02/10): the engine behind answers with the model it
    has loaded, and is never asked to load the one picked for the engine in front."""
    world = build_world({"llama_cpp": "pre_byte"}, live=["llama_cpp", "mlx"])
    await run_door(turn_lab, world, door, backend="llama_cpp", sid=f"b2b-{door}",
                   extra={"model": GGUF_NAME})
    assert world.engines["mlx"].switched_to is None
    assert world.engines["mlx"].calls, "the fallback did answer"


@pytest.mark.parametrize("door", DOORS)
async def test_b2_ollama_as_a_fallback_is_asked_for_the_requested_name_at_both_doors(turn_lab, door):
    """ROW B2 (D1-x, still open): Ollama picks its model per request, so as a
    fallback it gets the name the client asked for — through the module on the
    web, in the daemon's payload on `/v1`."""
    world = build_world({"mlx": "pre_byte"}, live=["mlx", "ollama"])
    world.daemon.models = [MLX_NAME]
    await run_door(turn_lab, world, door, backend="mlx", sid=f"b2c-{door}", extra={"model": MLX_NAME})
    if door.startswith("ui"):
        assert world.engines["ollama"].models == [MLX_NAME]
    else:
        assert [p["model"] for p in world.daemon.payloads if p] == [MLX_NAME]


# ───────────────────────────────────────────────────────────────────── B3 ──

def _resume(session_manager, door: str, sid: str) -> dict:
    """What a Continue is at each door: the web's session ends on the cut answer
    and the body says `continue`; the client of `/v1` resends it with `resume`."""
    if door.startswith("ui"):
        _cut_session(session_manager, sid)
        return {"message": "", "extra": {"continue": True}}
    history = [{"role": "user", "content": USER_TEXT}, {"role": "assistant", "content": PARTIAL}]
    return {"message": "", "extra": {"resume": True}, "messages": history}


def _able(engine, yes: bool) -> None:
    engine.can_continue = lambda model_name=None: yes


@pytest.mark.parametrize("door", DOORS)
async def test_b3_an_engine_that_cannot_continue_is_not_asked_and_the_next_one_answers(
        turn_lab, session_manager, door):
    """ROW B3. Both doors drop the engines that cannot resume (the web at its
    `engine` step, `/v1` inside the loop) and the next answers. DIFFERENCE (N6) in what
    the client is told: `/v1` calls it a fallback from the engine that was never
    asked (`preferred_unavailable`); the web says nothing of it (no header, no field)."""
    world = build_world(live=["mlx", "llama_cpp"])
    _able(world.engines["mlx"], False)
    _able(world.engines["llama_cpp"], True)
    sid = f"b3a-{door}"
    seen = await run_door(turn_lab, world, door, backend="mlx", sid=sid, **_resume(session_manager, door, sid))
    assert (seen.status, seen.answered, seen.asked) == (200, "llama_cpp", ("llama_cpp",))
    if door.startswith("v1"):
        assert seen.fallback == ("mlx", "preferred_unavailable")
    else:
        assert seen.fallback == (None, None)


@pytest.mark.parametrize("door", DOORS)
async def test_b3_no_engine_that_can_continue_is_a_400_at_both_doors(turn_lab, session_manager, door):
    world = build_world(live=["mlx", "llama_cpp"])
    _able(world.engines["mlx"], False)
    _able(world.engines["llama_cpp"], False)
    sid = f"b3b-{door}"
    seen = await run_door(turn_lab, world, door, backend="mlx", sid=sid, **_resume(session_manager, door, sid))
    assert (seen.status, seen.detail, seen.asked) == (
        400, "continue is not supported by the available engines", (),
    )


# ──────────────────────────────────── B4 / Q: no engine answers (the review's matrix) ──

def _bare_http_app(app_state, world: World) -> FastAPI:
    """`/v1` mounted the way the server mounts it, authenticated by a stand-in
    that leaves the same trace the real dependency does (the principal)."""
    import core.endpoints.chat as chat_mod
    from core.security.auth_dependencies import require_api_key

    app = FastAPI()
    app.include_router(chat_mod.router, prefix="/v1")

    def _auth(request: Request) -> None:
        request.state.principal = "test-key"

    app.dependency_overrides[require_api_key] = _auth
    app.state = app_state
    app_state.modules = world.modules
    return app


@pytest.mark.parametrize("stream", [False, True])
def test_q_v1_with_every_engine_retryable_answers_a_503_with_the_first_error_curated(turn_lab, app_state, stream):
    """ROW Q / D3 (decided provisionally 06/10: «show the FIRST error, curated, at every
    door»). It was the only cell of the review's matrix verified by reading, `chat.py`
    `raise last_exc`: MLX then llama.cpp, both failing in a way the cascade retries, and the
    last exception left the route as the framework's 500 — plain text, no engine message,
    no SSE even when it asked for a stream. It is now a 503 in JSON (also when a stream was
    asked: nothing is committed yet) whose text is the curated one of the FIRST engine, and
    never the engine's own words."""
    world = build_world({"mlx": "pre_byte", "llama_cpp": "pre_byte"}, live=["mlx", "llama_cpp"])
    app = _bare_http_app(app_state, world)
    with door_patches(turn_lab.server_state, turn_lab.memory_helper):
        client = TestClient(app, raise_server_exceptions=False)
        response = client.post(
            "/v1/chat/completions", headers={"x-session-id": f"q-{stream}"},
            json={"messages": [{"role": "user", "content": "hola"}], "engine": "mlx", "stream": stream},
        )
    assert response.status_code == 503
    assert response.headers["content-type"].startswith("application/json")
    assert response.json()["detail"] in {
        "S'ha produït un error en generar la resposta. Torna-ho a provar.",
        "Se ha producido un error al generar la respuesta. Inténtalo de nuevo.",
        "An error occurred while generating the response. Please try again.",
    }
    assert "worker died" not in response.text


@pytest.mark.parametrize("engine", ["mlx", "llama_cpp"])
async def test_q_the_web_json_tells_the_curated_text_of_the_first_engine_like_the_stream(turn_lab, engine):
    """ROW Q / D2 (decided provisionally 06/10: «503 with the curated text of the
    first error»; it was a generic «No AI engine available» that lost the notice).
    Every engine runs out of memory: the web stream writes the OOM notice of the
    FIRST engine inside the chat (#1117); the web JSON answers a 503 with the same
    words, without the chat's decoration."""
    world = build_world({e: "oom" for e in ("mlx", "llama_cpp", "ollama")})
    stream = await run_door(turn_lab, world, "ui_stream", backend=engine, sid=f"q1-{engine}")
    world = build_world({e: "oom" for e in ("mlx", "llama_cpp", "ollama")})
    plain = await run_door(turn_lab, world, "ui_json", backend=engine, sid=f"q2-{engine}")
    assert (stream.status, stream.notice) == (200, "oom")
    # The words are fixed here, not computed by the function that writes them;
    # the turn's language is whatever the session resolved (it follows NEXE_LANG).
    words = {
        "ca": "Memòria insuficient. Tanca altres aplicacions per alliberar memòria i torna-ho a provar.",
        "es": "Memoria insuficiente. Cierra otras aplicaciones para liberar memoria e inténtalo de nuevo.",
        "en": "Not enough memory. Close other applications to free up memory and try again.",
    }
    assert plain.status == 503
    assert plain.detail == words[plain.ctx.lang[:2]]


@pytest.mark.parametrize("door", ["v1_json", "ui_json"])
async def test_q_a_terminal_error_reaches_a_json_client_with_the_engines_own_text(turn_lab, door):
    """ROW Q (terminal column), JSON doors: 503 and the raw message of the engine
    ("Cannot connect to mlx: refused")."""
    world = build_world({"mlx": "unreachable"}, live=["mlx", "llama_cpp"])
    seen = await run_door(turn_lab, world, door, backend="mlx", sid=f"qt-{door}")
    assert (seen.status, seen.detail) == (503, "Cannot connect to mlx: refused")


async def test_q_a_terminal_error_in_the_web_stream_is_the_generic_notice_never_the_text(turn_lab):
    """ROW Q (terminal column), web stream: a 200 whose notice is curated (MC-133)."""
    world = build_world({"mlx": "unreachable"}, live=["mlx", "llama_cpp"])
    seen = await run_door(turn_lab, world, "ui_stream", backend="mlx", sid="qt-stream")
    assert (seen.status, seen.notice) == (200, "error")
    assert "refused" not in seen.text


class _StartRefused(OllamaModule):
    """An Ollama module whose `chat` fails as it is called, before any generator
    exists (`start_engine_call` raises): no engine ever reaches its first event."""

    def chat(self, model, messages, stream=False, **kwargs):
        self.calls += 1
        raise RuntimeError("connection reset")


async def test_q_the_web_stream_where_no_engine_reaches_its_first_event_shows_the_first_error(turn_lab):
    """ROW Q (web stream, last cell) / D3 (decided provisionally 06/10). It used to
    raise the 503 INSIDE the already-open stream: the client got its 200 and then
    a dropped connection, with no notice. The first failure is now written in the
    chat, curated, like a failure on a first event; nothing is saved. The JSON
    door answers the 503 the plain way, with the curated text of the same error."""
    engine = _StartRefused()
    world = World(modules={"ollama_module": engine}, daemon=FakeOllamaDaemon(), engines={"ollama": engine})
    streamed = await run_door(turn_lab, world, "ui_stream", backend="ollama", sid="q-start-s")
    plain = await run_door(turn_lab, world, "ui_json", backend="ollama", sid="q-start-j")
    assert (streamed.status, streamed.cut, streamed.notice, streamed.saved) == (200, None, "error", False)
    failed = {
        "ca": "S'ha produït un error en generar la resposta. Torna-ho a provar.",
        "es": "Se ha producido un error al generar la respuesta. Inténtalo de nuevo.",
        "en": "An error occurred while generating the response. Please try again.",
    }
    assert streamed.text.strip().endswith(failed[streamed.ctx.lang[:2]])
    assert "connection reset" not in streamed.text
    assert (plain.status, plain.detail) == (503, failed[plain.ctx.lang[:2]])


# ───────────────────────────────────────────────────────────────────── B5 ──

def _count(engine: str, status: str) -> float:
    return REGISTRY.get_sample_value(
        "core_chat_engine_requests_total", {"engine": engine, "status": status},
    ) or 0.0


@pytest.mark.parametrize("door", DOORS)
async def test_b5_what_each_door_records_about_the_engine_that_answered(turn_lab, door):
    """ROW B5. MLX fails, llama.cpp answers.
    Both doors: one `generate` record in the turn's usage (engine and model).
    `/v1` only: the Prometheus counter per attempt, `nexe_engine` / `nexe_fallback`
    in the body or `X-Nexe-Engine` / `X-Nexe-Fallback-*` in the headers.
    Web only: the engine and model in the stats of the saved answer (the footer a
    reload paints). DIFFERENCE: the web JSON body carries neither engine nor model."""
    before = {(e, s): _count(e, s) for e in ("mlx", "llama_cpp") for s in ("error", "success")}
    world = build_world({"mlx": "pre_byte"}, live=["mlx", "llama_cpp"])
    seen = await run_door(turn_lab, world, door, backend="mlx", sid=f"b5-{door}")
    moved = {k: _count(*k) - v for k, v in before.items() if _count(*k) != v}
    generate = [c for c in seen.ctx.usage["llm"]["calls"] if c["step"] == "generate"]
    assert [(c["engine"], c["model"]) for c in generate] == [("llama_cpp", GGUF_NAME)]
    if door.startswith("v1"):
        assert moved == {("mlx", "error"): 1.0, ("llama_cpp", "success"): 1.0}
        assert seen.fallback == ("mlx", "execution_failed")
        assert seen.saved_stats == {}
    else:
        assert moved == {}
        assert (seen.saved_stats["engine"], seen.saved_stats["model"]) == ("llama_cpp", GGUF_NAME)


async def test_b5_the_v1_body_and_headers_name_the_engine_and_the_switch(turn_lab):
    world = build_world({"mlx": "pre_byte"}, live=["mlx", "llama_cpp"])
    plain = await run_door(turn_lab, world, "v1_json", backend="mlx", sid="b5-body")
    assert plain.wire["nexe_engine"] == "llama_cpp"
    assert plain.wire["nexe_fallback"] == {"from": "mlx", "to": "llama_cpp", "reason": "execution_failed"}
    assert plain.wire["model"] == GGUF_NAME
    world = build_world({"mlx": "pre_byte"}, live=["mlx", "llama_cpp"])
    streamed = await run_door(turn_lab, world, "v1_stream", backend="mlx", sid="b5-headers")
    assert streamed.headers["x-nexe-engine"] == "llama_cpp"
    assert (streamed.headers["x-nexe-fallback-from"], streamed.headers["x-nexe-fallback-reason"]) == (
        "mlx", "execution_failed",
    )


async def test_b5_the_web_json_wire_carries_no_engine_and_no_model(turn_lab):
    world = build_world({"mlx": "pre_byte"}, live=["mlx", "llama_cpp"])
    seen = await run_door(turn_lab, world, "ui_json", backend="mlx", sid="b5-ui-json")
    assert set(seen.wire) == {
        "response", "session_id", "intent", "memory_action", "memory_saved", "memory_facts", "turn_id",
    }


# ───────────────────────────────────────────────────────────────────── B6 ──

@pytest.mark.parametrize("door", DOORS)
async def test_b6_the_deadline_sets_the_cancel_event_the_engine_was_given(turn_lab, monkeypatch, door):
    """ROW B6 (the time limit, written four times today: one per `generate` body).
    A 50 ms deadline, an in-process engine that takes 250 ms: at the end of its
    wait the event it received is set, at every door."""
    monkeypatch.setenv("NEXE_ENGINE_DEADLINE_S", "0.05")
    world = build_world(live=["mlx"], delay=0.25)
    await run_door(turn_lab, world, door, backend="mlx", sid=f"b6-dl-{door}")
    assert world.engines["mlx"].calls[0]["cancel_event"].is_set()


@pytest.mark.parametrize("door", DOORS)
async def test_b6_without_a_deadline_or_a_client_leaving_the_event_stays_clear(turn_lab, monkeypatch, door):
    monkeypatch.delenv("NEXE_ENGINE_DEADLINE_S", raising=False)
    world = build_world(live=["mlx"], delay=0.1)
    await run_door(turn_lab, world, door, backend="mlx", sid=f"b6-clear-{door}")
    assert not world.engines["mlx"].calls[0]["cancel_event"].is_set()


@pytest.mark.parametrize("door", DOORS)
async def test_b6_when_the_turn_is_over_the_monitor_is_finished_and_the_gate_is_free(
        turn_lab, app_state, door):
    """ROW B6 (the engine gate and the disconnect monitor). Four doors, one end
    state. (Where they differ is in WHEN the monitor stops — the web stream keeps it
    past `generate`, `/v1` stops it in a `finally` — which is internal.)"""
    world = build_world(live=["mlx"])
    seen = await run_door(turn_lab, world, door, backend="mlx", sid=f"b6-end-{door}")
    _event, monitor = seen.ctx.cancel_token
    await asyncio.sleep(0.05)
    assert monitor.done()
    assert app_state.engine_gate.snapshot()["holders"] == []


# ───────────────────────────────────────────────────────────────────── R1 ──

ONLY_TAG = "[MEM_SAVE: l'usuari es diu Aran]"
ANSWER = "Encantat, Aran. Que vols fer avui?"
ACKS = {policy.empty_reply_text(lang) for lang in ("ca", "es", "en")}


class _ScriptedInProc(InProc):
    """MLX-shaped: answers (or fails) call by call, never by argument."""

    def __init__(self, name: str, script: list, **kwargs):
        super().__init__(name, **kwargs)
        self.script = script

    async def chat(self, messages, system="", session_id="default", stream_callback=None, **kwargs):
        step = self.script[min(len(self.calls), len(self.script) - 1)]
        if isinstance(step, Exception):
            self.fail, self.after, self.tokens = step, None, ()
        else:
            self.fail, self.after, self.tokens = None, None, (step,)
        return await super().chat(messages, system, session_id, stream_callback, **kwargs)


class _ScriptedOllama(OllamaModule):
    def __init__(self, script: list, **kwargs):
        super().__init__(**kwargs)
        self.script = script

    def chat(self, model, messages, stream=False, **kwargs):
        step = self.script[min(self.calls, len(self.script) - 1)]
        if isinstance(step, Exception):
            self.exc, self.after, self.tokens = step, None, ()
        else:
            self.exc, self.after, self.tokens = None, None, (step,)
        return super().chat(model, messages, stream=stream, **kwargs)


def _reprompts(seen) -> list:
    """The re-prompt records of the turn (I8): `(engine, model)` per call."""
    return [(c["engine"], c["model"]) for c in seen.ctx.usage["llm"]["calls"] if c["step"] == "reprompt"]


def _two(first, second) -> World:
    engines = {"mlx": first, "llama_cpp": second}
    modules = {"mlx_module": first, "llama_cpp_module": second}
    return World(modules=modules, daemon=FakeOllamaDaemon(), engines=engines)


@pytest.mark.parametrize("door", V1)
async def test_r1_the_v1_reprompt_goes_to_the_engine_that_answered_and_to_nobody_else(turn_lab, door):
    """ROW R1 (decided provisionally 06/10: «the /v1 re-prompt goes to the same engine,
    as the web»). The answer is only a memory tag, so the door asks again. It used to
    ask the cascade from the top (MLX a SECOND time, and llama.cpp answering when that
    failed); now the second call goes to MLX alone: when it fails nobody else is asked
    and the neutral stand-in is the answer. It is still made without the turn's
    cancel_event (the second call has never had one at this door)."""
    mlx = _ScriptedInProc("mlx", [ONLY_TAG, RuntimeError("worker died")])
    llama = _ScriptedInProc("llama_cpp", [ANSWER])
    seen = await run_door(turn_lab, _two(mlx, llama), door, backend="mlx", sid=f"r1-{door}",
                          message="recorda que em dic Aran")
    assert any(ack in seen.text for ack in ACKS)
    assert len(mlx.calls) == 2 and llama.calls == []
    assert [call.get("cancel_event") is not None for call in mlx.calls] == [True, False]
    # The re-prompt is recorded under the engine it was asked of (it was N7: the record
    # named the engine of the first answer whichever one the cascade chose).
    assert [engine for engine, _model in _reprompts(seen)] == ["mlx"]


@pytest.mark.parametrize("door", V1)
async def test_r1_the_v1_reprompt_that_the_same_engine_answers_is_the_answer(turn_lab, door):
    mlx = _ScriptedInProc("mlx", [ONLY_TAG, ANSWER])
    llama = _ScriptedInProc("llama_cpp", [ANSWER])
    seen = await run_door(turn_lab, _two(mlx, llama), door, backend="mlx", sid=f"r1b-{door}",
                          message="recorda que em dic Aran")
    assert seen.text == ANSWER
    assert len(mlx.calls) == 2 and llama.calls == []


@pytest.mark.parametrize("door", UI)
async def test_r1_the_web_reprompt_asks_the_same_engine_only_and_an_ollama_shaped_one(turn_lab, door):
    """ROW R1. Web: an Ollama-shaped engine is asked again, ITSELF; when that second
    call fails nobody else is asked, and the neutral stand-in is the answer."""
    ollama = _ScriptedOllama([ONLY_TAG, RuntimeError("down")])
    mlx = _ScriptedInProc("mlx", [ANSWER])
    world = World(modules={"ollama_module": ollama, "mlx_module": mlx}, daemon=FakeOllamaDaemon(),
                  engines={"mlx": mlx, "ollama": ollama})
    seen = await run_door(turn_lab, world, door, backend="ollama", sid=f"r1o-{door}",
                          message="recorda que em dic Aran")
    assert ollama.calls == 2 and mlx.calls == []
    assert any(ack in seen.text for ack in ACKS)
    assert [engine for engine, _model in _reprompts(seen)] == ["ollama"]


@pytest.mark.parametrize("door", UI)
async def test_r1_the_web_does_not_reprompt_an_in_process_engine_at_all(turn_lab, door):
    """ROW R1. MLX / llama.cpp run through a queue and a worker the second call was
    never wired for: the core says it skipped and the neutral stand-in is the answer."""
    mlx = _ScriptedInProc("mlx", [ONLY_TAG, ANSWER])
    llama = _ScriptedInProc("llama_cpp", [ANSWER])
    seen = await run_door(turn_lab, _two(mlx, llama), door, backend="mlx", sid=f"r1m-{door}",
                          message="recorda que em dic Aran")
    assert len(mlx.calls) == 1 and llama.calls == []
    assert any(ack in seen.text for ack in ACKS)
    assert _reprompts(seen) == [], "no engine was asked, so I8 counts nothing"


# ───────────────────────────────────────────────────────────────────── B7 ──

@pytest.mark.parametrize("door", DOORS)
async def test_b7_the_loading_banner_is_a_web_stream_thing_and_goes_out_once(turn_lab, door):
    """ROW B7. Both engines have their model out of memory, the first fails: the web
    stream announces ONE load (the first engine's) and `/v1`, like the web JSON,
    announces none. (Where the label of that banner points is #1117's open limit.)"""
    world = build_world({"mlx": "pre_byte"}, live=["mlx", "llama_cpp"])
    world.engines["mlx"].loaded = False
    world.engines["llama_cpp"].loaded = False
    seen = await run_door(turn_lab, world, door, backend="mlx", sid=f"b7-{door}")
    assert seen.status == 200 and seen.answered == "llama_cpp"
    assert seen.loading == (1 if door == "ui_stream" else 0)


# ──────────────────────────────────────────────── N4: a client that leaves ──

class _StopsWhenTheClientLeaves(InProc):
    """The real MLX loop between tokens: it checks its `cancel_event` and returns
    what it had, normally — nothing is raised."""

    async def chat(self, messages, system="", session_id="default", stream_callback=None, **kwargs):
        self.calls.append(kwargs)
        self.log.append(self.name)
        cancel = kwargs["cancel_event"]
        if stream_callback is not None:
            stream_callback("Hola ")
        for _ in range(100):
            if cancel.is_set():
                break
            await asyncio.sleep(0.01)
        if stream_callback is None:
            return {"response": "Hola ", "finish_reason": "stop", "tokens": 1}
        return {"finish_reason": "stop"}


@pytest.mark.parametrize("door", DOORS)
async def test_n4_a_client_that_leaves_while_the_engine_stops_cleanly_keeps_the_partial_everywhere(
        turn_lab, door):
    """N4, the other half (the matrix's `gone` is the engine dying with the client).
    An engine that notices the client left and returns what it had: no door asks
    another engine, every door answers 200 and keeps the partial."""
    first, other = _StopsWhenTheClientLeaves("mlx"), InProc("llama_cpp")
    world = World(modules={"mlx_module": first, "llama_cpp_module": other}, daemon=FakeOllamaDaemon(),
                  engines={"mlx": first, "llama_cpp": other})
    seen = await run_door(turn_lab, world, door, backend="mlx", sid=f"n4-{door}", gone=True)
    assert (seen.status, seen.asked, seen.saved) == (200, ("mlx",), True)
    assert seen.saved_text == "Hola"
    # The engine would also return "Hola" once its own loop ran out (1 s); the
    # event is what proves the stop came from the client leaving.
    assert first.calls[0]["cancel_event"].is_set()


# ───────────────────────────────────────── the wording of what the chat shows ──

def test_the_notices_the_chat_shows_are_these_words():
    """Not derived from the function that writes them: the matrix names a notice by
    its kind (`oom`, `error`), and this pins what each kind says, in every language."""
    plain = RuntimeError("x")
    assert _stream_error_notice(OOM, "en") == (
        "\n⚠️ Not enough memory. Close other applications to free up memory and try again."
    )
    assert _stream_error_notice(RuntimeError("MLX: Insufficient Memory"), "en") == (
        "\n⚠️ Not enough memory to load the model with MLX. Switch the engine to Ollama "
        "(it uses far less memory) or close other applications and try again."
    )
    assert _stream_error_notice(plain, "en") == "\n⚠️ An error occurred while generating the response. Please try again."
    assert _stream_error_notice(plain, "ca") == "\n⚠️ S'ha produït un error en generar la resposta. Torna-ho a provar."
    assert _stream_error_notice(plain, "es") == "\n⚠️ Se ha producido un error al generar la respuesta. Inténtalo de nuevo."


def test_the_neutral_stand_in_the_reprompt_falls_back_to_is_these_words():
    assert [policy.empty_reply_text(lang) for lang in ("ca", "es", "en")] == [
        "D'acord.", "De acuerdo.", "Okay.",
    ]


# ─────────────────────────────────────────────────────────── §E describe ──

async def _turn_with_image(lab, world: World, door: str, sid: str):
    image = _png()
    if door.startswith("v1"):
        parts = [{"type": "text", "text": "què hi veus?"}, _image_part(image)]
        return await run_door(lab, world, door, backend="mlx", sid=sid,
                              messages=[{"role": "user", "content": parts}])
    return await run_door(lab, world, door, backend="mlx", sid=sid, message="què hi veus?",
                          extra={"image_b64": image, "image_type": "image/png"})


@pytest.fixture
def _fresh_image_memory(monkeypatch):
    monkeypatch.setenv("NEXE_LANG", "ca")
    image_memory.DESCRIPTIONS.clear()
    image_memory.FAILED_ATTEMPTS.clear()
    yield
    image_memory.DESCRIPTIONS.clear()
    image_memory.FAILED_ATTEMPTS.clear()


def _described_by(world: World) -> dict:
    return {name: any(_is_description(p) for p in engine.prompts) for name, engine in world.engines.items()
            if hasattr(engine, "prompts")}


@pytest.mark.usefixtures("_fresh_image_memory")
@pytest.mark.parametrize("door", DOORS)
async def test_e_describe_image_is_asked_of_the_engine_that_served_not_the_one_that_failed(turn_lab, door):
    """§E (#1144). Same at both doors: after the turn, the description is asked of
    the engine that served; the engine that failed is not asked again. The record
    names the engine and no model."""
    world = build_world({"mlx": "pre_byte"}, live=["mlx", "llama_cpp"], mlx={"sees": True},
                        llama_cpp={"sees": True})
    seen = await _turn_with_image(turn_lab, world, door, f"e-desc-{door}")
    assert _described_by(world) == {"mlx": False, "llama_cpp": True}
    calls = [(c["step"], c["engine"], c["model"]) for c in seen.ctx.usage["llm"]["calls"]]
    assert calls == [("generate", "llama_cpp", GGUF_NAME), ("describe_image", "llama_cpp", None)]


@pytest.mark.usefixtures("_fresh_image_memory")
@pytest.mark.parametrize("door", ["v1_stream", "ui_stream"])
async def test_e_a_turn_that_broke_midway_describes_nothing(turn_lab, door):
    """§E (#1144 + #1040). The answer was cut by the engine: it is partial, and the
    description (post-commit) is skipped by policy — at both streams."""
    world = build_world({"mlx": "mid_stream"}, live=["mlx", "llama_cpp"], mlx={"sees": True},
                        llama_cpp={"sees": True})
    seen = await _turn_with_image(turn_lab, world, door, f"e-partial-{door}")
    assert seen.ctx.partial is True
    assert _described_by(world) == {"mlx": False, "llama_cpp": False}


# ───────────────────────────────────────────────────────── §E images ──

@pytest.mark.usefixtures("_fresh_image_memory")
@pytest.mark.parametrize("door", DOORS)
async def test_e_an_image_skips_a_fallback_that_cannot_see_at_both_doors(turn_lab, door):
    """§E (#1144 / #1035). MLX fails; llama.cpp runs a text model; Ollama does not
    say. The blind fallback is skipped (never asked) and the next answers, at
    `/v1` and at the web alike."""
    world = build_world({"mlx": "pre_byte"}, live=["mlx", "llama_cpp", "ollama"], mlx={"sees": True},
                        llama_cpp={"sees": False})
    seen = await _turn_with_image(turn_lab, world, door, f"e-skip-{door}")
    # The third call is the post-commit description: Ollama does not say whether its model
    # sees, so it is asked (the blind llama.cpp never is).
    assert (seen.status, seen.answered, seen.asked) == (200, "ollama", ("mlx", "ollama", "ollama"))


@pytest.mark.usefixtures("_fresh_image_memory")
@pytest.mark.parametrize("door", DOORS)
async def test_e_the_engine_asked_for_is_asked_even_if_it_cannot_see(turn_lab, door):
    """§E. Only a FALLBACK is judged by its sight: the first engine decides what to
    do with a picture. Both doors."""
    world = build_world(live=["mlx", "llama_cpp"], mlx={"sees": False}, llama_cpp={"sees": True})
    seen = await _turn_with_image(turn_lab, world, door, f"e-first-{door}")
    assert (seen.answered, seen.asked) == ("mlx", ("mlx",))
    assert world.engines["mlx"].calls[0]["images"]


# ──────────────────────────────────────────────────── §E compact ──────

async def _compact_got(lab, door: str, faults: dict, live: list, sid: str):
    """Which engine `compact` is handed, by name (and what the turn showed)."""
    world = build_world(faults, live=live)
    got: list = []

    async def _spy(session, engine, *args, **kwargs):
        got.append(engine)

    with patch("plugins.web_ui_module.api.turn_adapters.compact_session", new=_spy), \
         patch("core.sessions.compactor.compact_session", new=_spy):
        seen = await run_door(lab, world, door, backend="mlx", sid=sid)
    names = [next((n for n, e in world.engines.items() if e is g), repr(g)) for g in got]
    return seen, names


@pytest.mark.parametrize("door", DOORS)
async def test_e_compact_is_handed_the_engine_that_served(turn_lab, door):
    """§E. A fallback served: compaction is queued against it, at all four doors."""
    seen, names = await _compact_got(turn_lab, door, {"mlx": "pre_byte"}, ["mlx", "llama_cpp"], f"e-c1-{door}")
    assert (seen.answered, names) == ("llama_cpp", ["llama_cpp"])


async def test_e_compact_runs_against_the_engine_that_failed_when_the_web_stream_writes_its_notice(turn_lab):
    """§E (verified: the review wrote «plausible»). Every engine fails before a byte:
    the web stream answers 200 with the first one's notice, `ctx.engine` is left
    pointing at that engine (`_serve_with`), and `compact` — which no partial turn
    skips — is queued against it. The other three doors abort with an error and
    run no step after `generate`."""
    faults = {"mlx": "pre_byte", "llama_cpp": "pre_byte"}
    seen, names = await _compact_got(turn_lab, "ui_stream", faults, ["mlx", "llama_cpp"], "e-c2-stream")
    assert (seen.status, seen.notice, names) == (200, "error", ["mlx"])
    for door in ("v1_json", "v1_stream", "ui_json"):
        seen, names = await _compact_got(turn_lab, door, faults, ["mlx", "llama_cpp"], f"e-c2-{door}")
        assert (seen.status >= 500, names) == (True, [])


async def test_e_compact_after_a_stream_cut_midway_is_handed_the_engine_that_cut(turn_lab):
    seen, names = await _compact_got(turn_lab, "ui_stream", {"mlx": "mid_stream"}, ["mlx", "llama_cpp"], "e-c3")
    assert (seen.notice, names) == ("error", ["mlx"])


# ─────────────────────────────────────── §E the labels of the answer ──

@pytest.mark.parametrize("door", DOORS)
async def test_e_the_labels_the_client_reads_name_the_engine_that_answered(turn_lab, door):
    """§E ([MODEL:] / [ENGINE:], #1035 and #1146). The web stream sends the model
    of the engine asked and, after a fallback, a second one: the client keeps the
    LAST of each. `/v1` sends none of them; its equivalents are the headers and body
    fields of B5. The web JSON sends none either (the stats keep them)."""
    world = build_world({"mlx": "pre_byte"}, live=["mlx", "llama_cpp"])
    seen = await run_door(turn_lab, world, door, backend="mlx", sid=f"e-lab-{door}")
    if door == "ui_stream":
        assert seen.engine_tags == ("llama_cpp",)
        assert seen.model_tags[-1] == GGUF_NAME and len(seen.model_tags) == 2
    else:
        assert seen.engine_tags == () and seen.model_tags == ()


@pytest.mark.parametrize("door", V1)
async def test_b2_ollama_in_reserve_without_the_requested_model_is_passed_over_at_v1(turn_lab, door):
    """ROW B2 / R2 (D1-z, decided provisionally 06/10: «a model that is not on Ollama is
    reason enough to try the next engine, only for the engines in reserve»). MLX fails and
    Ollama, behind it, does not have the name the client sent. The web already passed it
    over (`ModelNotFoundError` is retryable: the `not_found` cells of the matrix); `/v1`
    answered the daemon's 404 as if the client had named a bad model for the engine it
    asked for. Now Ollama is passed over, nobody claims, and the client gets a 503 that
    tells the first engine's failure, curated."""
    world = build_world({"mlx": "pre_byte"}, live=["mlx", "ollama"])
    world.daemon.models = ["some-other-model"]
    seen = await run_door(turn_lab, world, door, backend="mlx", sid=f"b2z-{door}", extra={"model": MLX_NAME})
    assert (seen.status, seen.saved) == (503, False)
    assert seen.asked == ("mlx",)   # the daemon's tag list says no before its chat is ever asked
    assert seen.detail in {
        "S'ha produït un error en generar la resposta. Torna-ho a provar.",
        "Se ha producido un error al generar la respuesta. Inténtalo de nuevo.",
        "An error occurred while generating the response. Please try again.",
    }


@pytest.mark.parametrize("door", V1)
async def test_b2_ollama_asked_first_without_the_model_is_still_the_404_the_client_earned(turn_lab, door):
    """The other half of D1-z: the engine the client asked for answering «no such model» is
    the answer, as before."""
    world = build_world({}, live=["mlx", "ollama"])
    world.daemon.models = ["some-other-model"]
    seen = await run_door(turn_lab, world, door, backend="ollama", sid=f"b2y-{door}", extra={"model": "model-que-no-existeix"})
    assert (seen.status, seen.asked) == (404, ())
