"""API providers, phase 3 — the API as an engine of full right, beyond the column of the matrix.

What `test_c48_p0_api.py` pins (the column: every way the provider answers, every refusal, never a
fallback) is not repeated. Here: the model is the TURN's (not state of the module), the internal
steps follow it, `/v1` carries its own consent and never reaches Ollama, and the trace says when a
turn left the machine.
"""
from __future__ import annotations

import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import HTTPException

from core import runtime_state
from core.endpoints.chat_engines import model_switch, routing
from core.endpoints.chat_sanitization import DEFAULT_CONTEXT_WINDOW
from core.providers.cloud import ALLOW_CLOUD_ENV
from plugins.api_module.module import ApiModule, ApiTurnEngine

from ._c48_p0_api_lab import FAKE_KEY, MODEL, FakeProvider, api_world, ask_api, consent_for
from ._c48_p0_lab import run_door
from .test_1144_image_memory import _image_part, _png  # noqa: E402

V1 = ("v1_json", "v1_stream")
WEB = ("ui_json", "ui_stream")


@pytest.fixture
def cloud(monkeypatch):
    runtime_state.reset()
    monkeypatch.setenv(ALLOW_CLOUD_ENV, "1")
    monkeypatch.setenv("DEEPSEEK_API_KEY", FAKE_KEY)
    monkeypatch.setenv("OPENAI_API_KEY", FAKE_KEY)
    yield
    runtime_state.reset()


def _state(**modules):
    return SimpleNamespace(modules=modules, config={})


# ====================================================== the model is the turn's

def test_the_candidates_of_a_turn_hand_a_hosted_engine_bound_to_the_turns_model_and_the_others_as_they_are():
    from core.turn.engine_claim import live_candidates

    local = SimpleNamespace(chat=lambda *a, **k: None)
    module = ApiModule()
    state = _state(ollama_module=local, api_module=module)
    (name, engine), = live_candidates("api", state, cloud_ok=True, model_name="gpt-4o")
    assert name == "api" and isinstance(engine, ApiTurnEngine) and engine.model_in_use == "gpt-4o"
    assert engine is not module
    (name, engine), = live_candidates("ollama", state, model_name="gpt-4o")
    assert engine is local, "a local engine is never wrapped"


def test_two_turns_on_two_models_do_not_read_each_others_window_or_sight():
    from core.context_window import ask_engine_window
    from core.turn.engine_claim import live_candidates

    state = _state(api_module=ApiModule())
    (_n1, small), = live_candidates("api", state, cloud_ok=True, model_name="deepseek-chat")
    (_n2, big), = live_candidates("api", state, cloud_ok=True, model_name="gpt-4o")
    # asked in the "wrong" order, after both exist: each still answers for its own
    assert (ask_engine_window(big), routing.engine_can_see_images(big)) == (128000, True)
    assert (ask_engine_window(small), routing.engine_can_see_images(small)) == (64000, False)
    assert small.model_in_use == "deepseek-chat" and big.model_in_use == "gpt-4o"


async def test_two_concurrent_turns_each_get_their_own_window_through_the_real_web_door(turn_lab, cloud, app_state, monkeypatch):
    """Concurrently, both open, interleaved at the provider: the window of each turn is its model's.

    The lab's patches are entered ONCE around both turns: two turns each entering `door_patches` at the same time
    would unwind them out of order and leave a stand-in patched into the module for every later test."""
    import contextlib
    import json

    import httpx

    turns = {"deepseek-chat": "deepseek", "gpt-4o": "openai"}
    gate = asyncio.Event()

    async def handler(request):
        await gate.wait()  # both turns are inside the engine at once
        assert json.loads(request.content).get("stream") is False
        return httpx.Response(200, json={"choices": [{"message": {"content": "ok"}, "finish_reason": "stop"}]})

    app_state.modules = {"api_module": ApiModule(transport=httpx.MockTransport(handler))}

    async def one(model, provider_key):
        return await turn_lab.ui(streaming=False, session_id=f"conc-{model}", message="hola",
                                 body_extra={"backend": "api", "model": model, "cloud_consent": provider_key})

    with turn_lab._patches():
        monkeypatch.setattr(turn_lab, "_patches", lambda streaming=False: contextlib.nullcontext())
        tasks = [asyncio.ensure_future(one(m, k)) for m, k in turns.items()]
        await asyncio.sleep(0.2)
        assert not any(t.done() for t in tasks), "both turns are waiting on the provider at the same time"
        gate.set()
        ctxs = dict(zip(turns, await asyncio.gather(*tasks)))
    assert ctxs["deepseek-chat"].context_window == 64000 and ctxs["gpt-4o"].context_window == 128000
    assert [ctxs[m].engine.model_in_use for m in turns] == list(turns)


def test_the_effective_window_is_asked_for_the_model_of_the_request():
    from core.endpoints.chat import get_effective_context_window

    state = _state(api_module=ApiModule())
    assert get_effective_context_window("api", state, "gpt-4o") == 128000
    assert get_effective_context_window("api", state, "deepseek-chat") == 64000
    assert get_effective_context_window("api", state) == DEFAULT_CONTEXT_WINDOW, "no model, no window to invent"
    assert get_effective_context_window("api", state, "llama3.2:3b") == DEFAULT_CONTEXT_WINDOW


@pytest.mark.parametrize("model, window", [("gpt-4o", 128000), ("deepseek-chat", 64000)])
@pytest.mark.parametrize("door", WEB + V1)
async def test_the_window_a_turn_is_sized_with_is_its_models(turn_lab, cloud, model, window, door):
    key = "openai" if model.startswith("gpt") else "deepseek"
    provider = FakeProvider("ok")
    seen, _world = await ask_api(turn_lab, door, provider, model=model, consent=False, extra=consent_for(door, key),
                                 sid=f"win-{model}-{door}")
    assert seen.status == 200 and seen.ctx.context_window == window


async def test_the_prompt_at_v1_is_fitted_to_the_models_window_not_a_default(turn_lab, cloud):
    fitted: list = []
    import core.endpoints.chat as chat_mod
    real = chat_mod._fit_v1_messages_to_window

    def spy(messages, window, body):
        fitted.append(window)
        return real(messages, window, body)

    with patch.object(chat_mod, "_fit_v1_messages_to_window", spy):
        await ask_api(turn_lab, "v1_json", FakeProvider("ok"), model="gpt-4o", consent=False,
                      extra=consent_for("v1_json", "openai"), sid="fit-gpt")
        await ask_api(turn_lab, "v1_json", FakeProvider("ok"), model="deepseek-chat", sid="fit-ds")
    assert 128000 in fitted and 64000 in fitted
    assert DEFAULT_CONTEXT_WINDOW not in fitted


def test_a_fallback_never_asks_a_hosted_engine_for_a_loaded_model():
    """`_model_on_fallback`: a hosted engine has no loaded model, the name asked for IS the model. The check is
    explicit: this engine even carries a `_node` that a local lookup would answer from."""
    from plugins.web_ui_module.api.engine_doors import _model_on_fallback

    node = SimpleNamespace(config=SimpleNamespace(model_path="/models/something-local.gguf"))
    hosted = SimpleNamespace(runs_in_the_cloud=True, _node=node)
    local = SimpleNamespace(_node=node)
    assert _model_on_fallback(hosted, "gpt-4o") == "gpt-4o"
    assert _model_on_fallback(local, "gpt-4o") == "something-local.gguf", "the local rule is untouched"


async def test_switching_the_model_of_a_hosted_engine_never_looks_for_a_file(monkeypatch):
    looked = []
    monkeypatch.setattr(model_switch, "resolve_local_model_path", lambda name: looked.append(name))
    swap = MagicMock(side_effect=AssertionError("a hosted engine swaps nothing"))
    for engine in (SimpleNamespace(runs_in_the_cloud=True, switch_model_by_path=swap), "api"):
        assert await model_switch.switch_engine_model(engine, "api", "gpt-4o") is False
    assert looked == []
    # control: a local engine that swaps does resolve its path
    local = SimpleNamespace(switch_model_by_path=lambda path: True)
    monkeypatch.setattr(model_switch, "resolve_local_model_path", lambda name: f"/models/{name}")
    assert await model_switch.switch_engine_model(local, "mlx", "m") is True


def test_the_module_keeps_no_model_whatever_the_turns_do():
    module = ApiModule()
    for model in ("deepseek-chat", "gpt-4o"):
        view = module.for_model(model)
        view.get_context_window(), view.can_see_images()
    assert vars(module) == vars(ApiModule()), "the module is as stateless after the turns as before"


# ================================================================ /v1 on its own

def _body(**kwargs):
    from core.endpoints.chat_schemas import ChatCompletionRequest, Message
    kwargs.setdefault("messages", [Message(role="user", content="hola")])
    return ChatCompletionRequest(**kwargs)


def test_the_consent_field_is_the_requests_own_optional_and_bounded():
    from pydantic import ValidationError
    assert _body().nexe_cloud_consent is None
    assert _body(nexe_cloud_consent="deepseek").nexe_cloud_consent == "deepseek"
    with pytest.raises(ValidationError):
        _body(nexe_cloud_consent="x" * 51)


@pytest.mark.parametrize("engine", ["api", "API", " api "])
async def test_the_dispatcher_sends_the_api_to_its_own_forwarder_and_never_to_ollama(cloud, engine):
    from core.endpoints import chat as chat_mod
    request = MagicMock()
    request.app.state = _state(api_module=ApiModule(), ollama_module=object())
    with patch.object(chat_mod, "_forward_to_ollama", new=AsyncMock(side_effect=AssertionError("Ollama"))), \
            patch.object(chat_mod, "_forward_to_api", new=AsyncMock(return_value={"api": True})) as api:
        out = await chat_mod._dispatch_to_engine(engine, [], _body(engine="api"), request, request.app.state, "q")
    assert out == {"api": True} and api.await_count == 1


async def test_the_forwarder_asks_the_gate_itself_so_a_caller_that_skipped_it_still_sends_nothing(cloud):
    from core.endpoints import chat as chat_mod
    provider = FakeProvider("ok")
    request = MagicMock()
    request.app.state = _state(api_module=provider.module(), ollama_module=object())
    with patch.object(chat_mod, "_forward_to_ollama", new=AsyncMock(side_effect=AssertionError("Ollama"))):
        for body in (_body(engine="api", model=MODEL),                                           # no consent
                     _body(engine="api", model=MODEL, nexe_cloud_consent="openai"),              # another provider's
                     _body(engine="api", model="llama3.2:3b", nexe_cloud_consent="deepseek"),    # not a provider's model
                     _body(engine="api", nexe_cloud_consent="deepseek")):                        # no model
            with pytest.raises(HTTPException) as refused:
                await chat_mod._dispatch_to_engine("api", [], body, request, request.app.state, "q")
            assert refused.value.status_code in (400, 403)
    assert provider.seen == []


async def test_the_forwarder_with_the_switch_off_sends_nothing_even_with_a_consent(cloud, monkeypatch):
    from core.endpoints import chat as chat_mod
    monkeypatch.setenv(ALLOW_CLOUD_ENV, "0")
    provider = FakeProvider("ok")
    request = MagicMock()
    request.app.state = _state(api_module=provider.module())
    with pytest.raises(HTTPException) as refused:
        await chat_mod._dispatch_to_engine("api", [], _body(engine="api", model=MODEL, nexe_cloud_consent="deepseek"),
                                           request, request.app.state, "q")
    assert refused.value.status_code == 403 and provider.seen == []


async def test_an_unloaded_api_module_is_a_503_from_the_forwarder_not_an_ollama_answer(cloud):
    from core.endpoints import chat as chat_mod
    request = MagicMock()
    request.app.state = _state(ollama_module=object())
    with patch.object(chat_mod, "_forward_to_ollama", new=AsyncMock(side_effect=AssertionError("Ollama"))):
        with pytest.raises(HTTPException) as refused:
            await chat_mod._dispatch_to_engine("api", [], _body(engine="api", model=MODEL, nexe_cloud_consent="deepseek"),
                                               request, request.app.state, "q")
    assert refused.value.status_code == 503


async def test_an_unknown_engine_name_still_reaches_the_local_default_as_before_and_the_api_is_not_one_of_them():
    """The legacy default of this dispatcher is untouched (a name that is no engine goes to Ollama); what changed is
    that the API is a name it knows."""
    from core.endpoints import chat as chat_mod
    request = MagicMock()
    with patch.object(chat_mod, "_forward_to_ollama", new=AsyncMock(return_value="ollama")), \
            patch.object(chat_mod, "_forward_to_api", new=AsyncMock(return_value="api")):
        assert await chat_mod._dispatch_to_engine("mystery", [], _body(), request, MagicMock(), "q") == "ollama"
        assert await chat_mod._dispatch_to_engine("api", [], _body(), request, MagicMock(), "q") == "api"


@pytest.mark.parametrize("door", V1)
async def test_v1_does_not_send_what_the_web_door_does_not_either_only_the_models_own_defaults(turn_lab, cloud, door):
    provider = FakeProvider("ok")
    await ask_api(turn_lab, door, provider, extra={"temperature": 1.5, "max_tokens": 10, "top_p": 0.4}, sid=f"fields-{door}")
    body = provider.bodies()[0]
    assert body["top_p"] == 0.4
    allowed = {"model", "messages", "stream", "top_p"} | ({"stream_options"} if body["stream"] else set())
    assert set(body) == allowed, "no temperature, no max_tokens: the provider's defaults"


@pytest.mark.parametrize("door", V1)
async def test_v1_continue_is_refused_for_the_api_and_nothing_is_sent(turn_lab, cloud, door):
    provider = FakeProvider("ok")
    messages = [{"role": "user", "content": "hola"}, {"role": "assistant", "content": "Hola, qu"}]
    world = api_world(provider)
    seen = await run_door(turn_lab, world, door, backend="api", sid=f"resume-{door}", messages=messages,
                          extra={"model": MODEL, "resume": True, **consent_for(door)})
    assert seen.status == 400 and "continue" in (seen.detail or "")
    assert provider.seen == [] and world.asked() == ()


@pytest.mark.parametrize("door", V1)
async def test_v1_names_the_engine_that_answered_and_labels_nothing_of_the_web(turn_lab, cloud, door):
    provider = FakeProvider("ok")
    seen, _world = await ask_api(turn_lab, door, provider, sid=f"labels-{door}")
    assert seen.answered == "api"
    assert seen.fallback in ((None, None), (None, "preferred_unavailable")) or not seen.fallback[0]
    assert seen.engine_tags == () and seen.model_tags == ()
    if door == "v1_stream":
        assert seen.headers["x-nexe-engine"] == "api" and "x-nexe-fallback-from" not in seen.headers
        assert "api-stream-" in "".join(c.decode() if isinstance(c, bytes) else c for c in seen.wire)
    else:
        assert seen.wire["nexe_engine"] == "api" and "nexe_fallback" not in seen.wire and seen.wire["model"] == MODEL


@pytest.mark.parametrize("door", V1)
async def test_v1_reasoning_travels_as_reasoning_when_asked_for_and_not_otherwise(turn_lab, cloud, door):
    import json

    import httpx

    def reasoner(request):
        stream = json.loads(request.content).get("stream")
        if not stream:
            return httpx.Response(200, json={"choices": [{"message": {"content": "R", "reasoning_content": "pensant"},
                                                          "finish_reason": "stop"}]})
        events = [{"choices": [{"delta": {"reasoning_content": "pensant"}, "finish_reason": None}]},
                  {"choices": [{"delta": {"content": "R"}, "finish_reason": "stop"}]}]
        return httpx.Response(200, content=("".join(f"data: {json.dumps(e)}\n\n" for e in events) + "data: [DONE]\n\n").encode())

    for effort, expected in (("low", True), (None, False)):
        provider = FakeProvider("ok")
        provider.handler = reasoner
        extra = {"reasoning_effort": effort} if effort else {}
        seen, _ = await ask_api(turn_lab, door, provider, extra=extra, sid=f"reason-{door}-{effort}")
        text = json.dumps(seen.wire, default=str) if door == "v1_json" else "".join(
            c.decode() if isinstance(c, bytes) else str(c) for c in seen.wire)
        assert ("pensant" in text) is expected, (effort, text[:300])


@pytest.mark.parametrize("door", V1)
async def test_v1_an_image_goes_to_a_model_that_sees_and_is_refused_for_one_that_does_not(turn_lab, cloud, door):
    content = [{"type": "text", "text": "què veus?"}, _image_part(_png())]
    provider = FakeProvider("ok")
    world = api_world(provider)
    seen = await run_door(turn_lab, world, door, backend="api", sid=f"img-{door}", messages=[{"role": "user", "content": content}],
                          extra={"model": "gpt-4o", **consent_for(door, "openai")})
    assert seen.status == 200
    sent = provider.bodies()[0]["messages"][-1]["content"]
    assert [part["type"] for part in sent] == ["text", "image_url"]
    # a model that cannot read it: a 400 from the engine, terminal, and no request
    provider = FakeProvider("ok")
    world = api_world(provider)
    seen = await run_door(turn_lab, world, door, backend="api", sid=f"imgno-{door}", messages=[{"role": "user", "content": content}],
                          extra={"model": MODEL, **consent_for(door)})
    # A bad request said on purpose, in words written for the user: they arrive whole (P2-7).
    assert seen.status == 400 and "cannot read images" in (seen.detail or "")
    assert provider.seen == [] and world.asked() == ()


# ---------------------------------------------------- the internal steps follow the turn

def test_the_steps_that_ask_the_engine_again_get_it_bound_to_the_requests_model():
    from core.turn.adapters_api import _engine_module_of

    module = ApiModule()
    state = _state(api_module=module, ollama_module=SimpleNamespace(chat=lambda *a, **k: None))
    ctx = SimpleNamespace(engine="api", app_state=state, body=_body(model="gpt-4o"))
    view = _engine_module_of(ctx)
    assert isinstance(view, ApiTurnEngine) and view.model_in_use == "gpt-4o" and view.get_context_window() == 128000
    local = state.modules["ollama_module"]
    assert _engine_module_of(SimpleNamespace(engine="ollama", app_state=state, body=_body())) is local
    already = object()
    assert _engine_module_of(SimpleNamespace(engine=already, app_state=state, body=_body())) is already
    assert _engine_module_of(SimpleNamespace(engine="mystery", app_state=state, body=_body())) is None


@pytest.mark.parametrize("door", V1)
async def test_v1_the_reprompt_goes_to_the_api_and_counts_as_a_call_that_left(turn_lab, cloud, door):
    """The reply was only a memory tag, so the turn asks again: the second call goes to the API (the engine that
    answered, under the same consent) and to nobody else; the record says it left the machine."""
    only_tag, answer = "[MEM_SAVE: l'usuari es diu Aran]", "Encantat, Aran."
    provider = FakeProvider("ok", script=[only_tag, answer])
    world = api_world(provider)
    seen = await run_door(turn_lab, world, door, backend="api", sid=f"reprompt-{door}", message="recorda que em dic Aran",
                          extra={"model": MODEL, **consent_for(door)})
    assert seen.text == answer
    assert len(provider.seen) == 2 and world.asked() == ("api", "api")
    calls = seen.ctx.usage["llm"]["calls"]
    assert [(c["step"], c["engine"], c["left_machine"]) for c in calls if c["step"] in ("generate", "reprompt")] == [
        ("generate", "api", True), ("reprompt", "api", True)]


async def test_v1_ask_again_is_the_same_engine_and_the_same_gate(cloud):
    from core.turn.api_cascade import ask_again
    provider = FakeProvider("ok")
    state = _state(api_module=provider.module(), ollama_module=object())
    state.session_manager = None
    request = MagicMock()
    request.app.state = state
    with patch("core.endpoints.chat._forward_to_ollama", new=AsyncMock(side_effect=AssertionError("Ollama"))):
        ok = await ask_again(_body(engine="api", model=MODEL, nexe_cloud_consent="deepseek"), request,
                             [{"role": "user", "content": "hola"}], "hola", "s", "api")
        assert ok["choices"][0]["message"]["content"] == "Hola de api." and len(provider.seen) == 1
        with pytest.raises(HTTPException) as refused:
            await ask_again(_body(engine="api", model=MODEL), request, [{"role": "user", "content": "hola"}], "hola", "s", "api")
        assert refused.value.status_code == 403 and len(provider.seen) == 1, "no consent, no second request"


# ------------------------------------------- the steps after the turn, on the API, at /v1

def _compactable_session():
    session = MagicMock()
    session.id = "s-api"
    session.compaction_count = 0
    session.context_summary = ""
    session.lang = "ca"
    session.needs_compaction.return_value = True
    session.get_messages_to_compact.return_value = [
        {"role": "user", "content": "hola " * 50}, {"role": "assistant", "content": "ep " * 50},
    ]

    def apply(summary, compacted_count=0):
        session.compaction_count += 1

    session.apply_compaction.side_effect = apply
    return session


def _post_commit_ctx(provider, session, *, model="deepseek-chat", engine="api", key="deepseek"):
    from core.turn.context import TurnContext

    state = MagicMock()
    state.session_manager.get_or_create_session.return_value = session
    state.modules = {"api_module": provider.module()}
    ctx = TurnContext(turn_id="t-pc", entry="api", app_state=state, engine=engine, session_id="s-api",
                      body=_body(engine="api", model=model, nexe_cloud_consent=key))
    return ctx


async def test_v1_compaction_on_the_api_asks_the_provider_with_the_requests_model_and_counts_as_a_call_that_left(cloud):
    from fastapi import BackgroundTasks

    from core.turn.adapters_api import api_adapters

    provider = FakeProvider("ok", script=["resum de la conversa"])
    session = _compactable_session()
    ctx = _post_commit_ctx(provider, session)
    await api_adapters(BackgroundTasks())["compact"](ctx)
    (body,) = provider.bodies()
    assert body["model"] == "deepseek-chat" and body["stream"] is False
    assert session.compaction_count == 1 and ctx.usage["post_commit_result"]["compact"] == {"compacted": 1}
    (call,) = [c for c in ctx.usage["llm"]["calls"] if c["step"] == "compact"]
    assert (call["engine"], call["left_machine"]) == ("api", True)


async def test_v1_compaction_stops_when_the_switch_is_turned_off_after_the_turn(cloud, monkeypatch):
    from fastapi import BackgroundTasks

    from core.turn.adapters_api import api_adapters

    provider = FakeProvider("ok", script=["resum"])
    session = _compactable_session()
    ctx = _post_commit_ctx(provider, session)
    monkeypatch.setenv(ALLOW_CLOUD_ENV, "0")  # the user turned it off while the turn was being answered
    await api_adapters(BackgroundTasks())["compact"](ctx)
    assert provider.seen == [] and session.compaction_count == 0, "nothing left the machine after the switch went off"


async def test_v1_the_image_of_a_turn_is_described_by_the_same_provider_and_counted(turn_lab, cloud):
    from core.turn import image_memory

    provider = FakeProvider("ok", script=["Un quadrat blau.", "Un quadrat blau amb una vora."])
    world = api_world(provider)
    content = [{"type": "text", "text": "què veus?"}, _image_part(_png((61, 43)))]
    seen = await run_door(turn_lab, world, "v1_json", backend="api", sid="describe-api", messages=[{"role": "user", "content": content}],
                          extra={"model": "gpt-4o", **consent_for("v1_json", "openai")})
    assert seen.status == 200 and len(provider.seen) == 2, "the answer, then the description of the image"
    description = provider.bodies()[1]
    assert description["model"] == "gpt-4o"
    last = description["messages"][-1]["content"]
    assert [part["type"] for part in last] == ["text", "image_url"]
    assert last[0]["text"] in image_memory.DESCRIBE_PROMPT.values()
    calls = {c["step"]: c for c in seen.ctx.usage["llm"]["calls"]}
    assert (calls["describe_image"]["engine"], calls["describe_image"]["left_machine"]) == ("api", True)


async def test_v1_the_second_call_of_a_turn_is_fitted_to_the_models_window(cloud):
    from core.turn.api_cascade import ask_again
    import core.endpoints.chat as chat_mod

    windows: list = []
    real = chat_mod._fit_v1_messages_to_window
    state = _state(api_module=ApiModule(transport=__import__("httpx").MockTransport(FakeProvider("ok").handler)))
    request = MagicMock()
    request.app.state = state
    with patch.object(chat_mod, "_fit_v1_messages_to_window", lambda m, w, b: (windows.append(w), real(m, w, b))[1]):
        await ask_again(_body(engine="api", model="gpt-4o", nexe_cloud_consent="openai"), request, [{"role": "user", "content": "hola"}],
                        "hola", "s", "api")
    assert windows == [128000]


async def test_the_dispatcher_hands_the_forwarder_the_turns_cancel_event_and_images(cloud):
    from core.endpoints import chat as chat_mod

    cancel = object()
    request = MagicMock()
    with patch.object(chat_mod, "_forward_to_api", new=AsyncMock(return_value="ok")) as forward:
        await chat_mod._dispatch_to_engine("api", ["m"], _body(), request, MagicMock(), "q", cancel_event=cancel, images=["I"])
    (args, kwargs) = forward.await_args
    assert args[0] == ["m"] and kwargs == {"cancel_event": cancel, "images": ["I"]}


async def test_the_model_switch_sees_a_hosted_engine_by_either_its_module_or_its_name(monkeypatch):
    monkeypatch.setattr(model_switch, "resolve_local_model_path", lambda name: (_ for _ in ()).throw(AssertionError("no path")))
    swap = MagicMock(side_effect=AssertionError("nothing is swapped"))
    by_module = SimpleNamespace(runs_in_the_cloud=True, switch_model_by_path=swap)
    by_name = SimpleNamespace(switch_model_by_path=swap)
    assert await model_switch.switch_engine_model(by_module, "whatever", "m") is False
    assert await model_switch.switch_engine_model(by_name, "api", "m") is False


# ------------------------------------------ the web door reads an environment preference like /v1 does

@pytest.mark.parametrize("env", ["api", "API", " api "])
@pytest.mark.parametrize("streaming", [False, True])
async def test_an_environment_preference_for_the_api_is_not_a_request_at_the_web_door_either(turn_lab, cloud, app_state, fake_engine,
                                                                                            monkeypatch, env, streaming):
    """No `backend` in the body (a client other than the selector, which always sends it) and NEXE_MODEL_ENGINE=api left
    in the environment: the turn runs on the local engine, never reaches the provider, and does not even ask for consent —
    though the body carries a consent and a provider model, which is all the API would need."""
    provider = FakeProvider("ok")
    monkeypatch.setenv("NEXE_MODEL_ENGINE", env)
    app_state.modules = {"ollama_module": fake_engine, "api_module": provider.module()}
    ctx = await turn_lab.ui(streaming=streaming, session_id=f"envapi-{streaming}-{env.strip()}", message="hola",
                            body_extra={"model": MODEL, "cloud_consent": "deepseek"})
    assert provider.seen == [], "nothing was sent to the provider"
    assert ctx.left_machine is False and ctx.session.cloud_consent is None
    assert type(ctx.engine).__name__ != "ApiTurnEngine"


def test_the_engine_a_web_turn_asks_for_is_the_selectors_else_the_installations_and_never_the_api_by_environment(monkeypatch):
    from plugins.web_ui_module.api.turn_adapters import _requested_engine

    def asked(backend=None, env=None):
        monkeypatch.delenv("NEXE_MODEL_ENGINE", raising=False)
        if env is not None:
            monkeypatch.setenv("NEXE_MODEL_ENGINE", env)
        body = {"backend": backend} if backend is not None else {}
        return _requested_engine(SimpleNamespace(body=body))

    assert asked("api") == "api" and asked("API", env="ollama") == "api", "the selector is an explicit request"
    assert asked("mlx", env="api") == "mlx", "and it wins over the environment"
    assert asked(None) == "auto" and asked(None, env="llama.cpp") == "llama.cpp" and asked("", env="Ollama") == "ollama"
    assert asked(None, env="api") == "auto" and asked(None, env=" API ") == "auto"


# ------------------------------- a job queued after a turn asks again before it sends anything (web door)

def _web_post_commit_ctx(provider, session, *, model="deepseek-chat"):
    from core.turn.context import TurnContext

    ctx = TurnContext(turn_id="t-web-pc", entry="ui", app_state=_state(api_module=provider.module()), session=session,
                      session_id="s-web", body={"backend": "api", "model": model})
    ctx.engine = ctx.app_state.modules["api_module"].for_model(model)
    ctx.usage["ui"] = {"engine_name": "api", "model_name": model}
    return ctx


def _web_session(consent):
    session = _compactable_session()
    session.cloud_consent = consent
    session.messages = []
    return session


def _ui_table():
    from plugins.web_ui_module.api.turn_adapters import ui_adapters

    return ui_adapters(MagicMock(), streaming=False)


async def test_web_compaction_runs_while_the_session_still_consents(cloud):
    provider = FakeProvider("ok", script=["resum"])
    session = _web_session("deepseek")
    ctx = _web_post_commit_ctx(provider, session)
    await _ui_table()["compact"](ctx)
    assert len(provider.seen) == 1 and session.compaction_count == 1


@pytest.mark.parametrize("withdrawn", [None, "openai"])
async def test_web_compaction_queued_by_a_cloud_turn_does_not_run_once_the_consent_is_gone(cloud, withdrawn):
    """The next turn went local (its gate clears the session's consent), or the session now consents to another
    provider: the job of the turn before has nothing to stand on."""
    provider = FakeProvider("ok", script=["resum"])
    session = _web_session(withdrawn)
    ctx = _web_post_commit_ctx(provider, session)
    await _ui_table()["compact"](ctx)
    assert provider.seen == [] and session.compaction_count == 0
    assert "consent" in ctx.usage["degraded"]["compact"]


async def test_web_compaction_queued_by_a_cloud_turn_does_not_run_once_the_switch_is_off(cloud, monkeypatch):
    provider = FakeProvider("ok", script=["resum"])
    session = _web_session("deepseek")
    ctx = _web_post_commit_ctx(provider, session)
    monkeypatch.setenv(ALLOW_CLOUD_ENV, "0")
    await _ui_table()["compact"](ctx)
    assert provider.seen == [] and session.compaction_count == 0


async def test_web_compaction_on_a_local_engine_never_asks_for_a_consent(cloud):
    from core.turn.context import TurnContext

    seen = []

    class Local:
        def chat(self, model, messages, stream=False, **_):
            seen.append(model)

            async def gen():
                yield {"message": {"content": "resum"}}
            return gen()

    session = _web_session(None)
    ctx = TurnContext(turn_id="t", entry="ui", app_state=_state(), session=session, session_id="s", body={"backend": "ollama"})
    ctx.engine = Local()
    ctx.usage["ui"] = {"engine_name": "ollama", "model_name": "llama3.2:3b"}
    await _ui_table()["compact"](ctx)
    assert len(seen) == 1 and session.compaction_count == 1


@pytest.mark.parametrize("consent, described, width", [("openai", True, 37), (None, False, 38), ("deepseek", False, 39)])
async def test_web_image_description_asks_the_consent_again(cloud, monkeypatch, consent, described, width):
    from core.turn import image_memory

    monkeypatch.setenv("OPENAI_API_KEY", FAKE_KEY)
    provider = FakeProvider("ok", script=["Un quadrat blau."])
    png = _png((width, 29))  # its own image: the descriptions are kept by the bytes, process-wide
    session = _web_session(consent)
    session.messages = [{"role": "user", "content": "què veus?", "image_b64": png}]
    ctx = _web_post_commit_ctx(provider, session, model="gpt-4o")
    ctx.body["model"] = "gpt-4o"
    ctx.engine = ctx.app_state.modules["api_module"].for_model("gpt-4o")
    session_mgr = MagicMock()
    from plugins.web_ui_module.api.turn_adapters import ui_adapters
    await ui_adapters(session_mgr, streaming=False)["describe_image"](ctx)
    assert (len(provider.seen) == 1) is described
    assert bool(session.messages[0].get("image_description")) is described
    if not described:
        assert image_memory.DESCRIPTIONS.get(image_memory.image_key(png)) is None, "and it is not counted as a failed attempt"
        assert not image_memory.gave_up(image_memory.image_key(png))


async def test_a_job_the_user_already_signalled_does_not_send_a_hosted_compaction_and_a_local_one_still_does(cloud):
    import threading

    from core.sessions import compactor

    cancelled = threading.Event()
    cancelled.set()
    provider = FakeProvider("ok", script=["resum"])
    session = _compactable_session()
    view = provider.module().for_model("deepseek-chat")
    await compactor.compact_session(session, view, MagicMock(), cancel_event=cancelled)
    assert provider.seen == [] and session.compaction_count == 0, "a hosted engine is not asked once the job was preempted"
    # control 1: not signalled, it goes; control 2: a local engine keeps its rule (asked, then not applied)
    await compactor.compact_session(session, view, MagicMock(), cancel_event=threading.Event())
    assert len(provider.seen) == 1 and session.compaction_count == 1
    asked = []

    class Local:
        def chat(self, model, messages, stream=False, **_):
            asked.append(model)

            async def gen():
                yield {"message": {"content": "resum"}}
            return gen()

    local_session = _compactable_session()
    await compactor.compact_session(local_session, Local(), MagicMock(), cancel_event=cancelled)
    assert len(asked) == 1 and local_session.compaction_count == 0, "unchanged: asked, and the summary discarded"


# ------------------------------- each step that opens the way to the provider asks the gate, on its own

async def test_the_v1_engine_step_asks_the_gate_by_itself_not_only_the_session_step(cloud):
    """Run alone, without the `session` step before it, the step that picks the engine still refuses."""
    from fastapi import BackgroundTasks

    from core.turn.adapters_api import api_adapters
    from core.turn.context import TurnContext

    table = api_adapters(BackgroundTasks())
    state = _state(api_module=ApiModule(), ollama_module=SimpleNamespace(chat=lambda *a, **k: None))
    for fields in ({"nexe_cloud_consent": None}, {"nexe_cloud_consent": "openai"}, {"model": "llama3.2:3b"}):
        ctx = TurnContext(turn_id="t", entry="api", app_state=state,
                          body=_body(**{"engine": "api", "model": MODEL, "nexe_cloud_consent": "deepseek", **fields}))
        with pytest.raises(HTTPException) as refused:
            await table["engine"](ctx)
        assert refused.value.status_code in (400, 403) and ctx.engine is None
    ctx = TurnContext(turn_id="t", entry="api", app_state=state, body=_body(engine="api", model="gpt-4o", nexe_cloud_consent="openai"))
    await table["engine"](ctx)
    assert (ctx.engine, ctx.left_machine, ctx.context_window) == ("api", True, 128000)
    local = TurnContext(turn_id="t", entry="api", app_state=state, body=_body(engine="ollama"))
    await table["engine"](local)
    assert (local.engine, local.left_machine) == ("ollama", False)


async def test_the_v1_session_step_asks_the_gate_before_it_stores_anything(cloud):
    from fastapi import BackgroundTasks

    from core.turn.adapters_api import api_adapters
    from core.turn.context import TurnContext

    mirrored: list = []
    state = _state(api_module=ApiModule())
    state.session_manager = MagicMock()
    ctx = TurnContext(turn_id="t", entry="api", app_state=state, request=MagicMock(),
                      body=_body(engine="api", model=MODEL, nexe_cloud_consent=None))
    with patch("core.turn.adapters_api.derive_session_id", side_effect=lambda *a, **k: mirrored.append(1) or "s"):
        with pytest.raises(HTTPException) as refused:
            await api_adapters(BackgroundTasks())["session"](ctx)
    assert refused.value.status_code == 403 and mirrored == [] and state.session_manager.mock_calls == []


async def test_dispatch_v1_asks_the_gate_on_the_body_before_it_picks_a_single_candidate(cloud):
    from core.turn.api_cascade import dispatch_v1

    request = MagicMock()
    request.app.state = _state(api_module=ApiModule(), ollama_module=SimpleNamespace(chat=lambda *a, **k: None))
    with patch("core.endpoints.chat._dispatch_to_engine", new=AsyncMock(side_effect=AssertionError("nobody is asked"))):
        for body in (_body(engine="api", model=MODEL, nexe_cloud_consent=None), _body(engine="api", model=MODEL, nexe_cloud_consent="openai")):
            with pytest.raises(HTTPException) as refused:
                await dispatch_v1(body, request, [{"role": "user", "content": "hola"}], "hola", "s", "api", None)
            assert refused.value.status_code == 403
