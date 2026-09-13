"""
────────────────────────────────────
Server Nexe
Author: Jordi Goy
Description: Gate for F-D block 5 — both doors resolve, dispatch and fail over
    with the same engine routing.

    What this block removed: the web UI carried a second engine table
    (`_resolve_engines`, in module-key spelling, whose only alias was
    "llamacpp"), rebuilt the live-instance lookup by hand on every request
    (registry → .instance → get_module_instance() → .chat — a walk the plugin
    loader had already done at startup), and spread the retry policy across four
    `except` clauses that /v1 did not have at all.

    Three things are pinned here, and each one is checked on BEHAVIOUR, driving
    the real endpoints. The two "it is wired in" tests the sibling #965 left
    behind assert that a substring appears in a function's source: they stay
    green if the call is there and wrong, and go red if someone renames a local.

      (1) both doors agree on what is live, and neither dispatches to a module
          whose node is dead (B260);
      (2) the fallback cascade and the retry policy are the same at both doors —
          including which errors are NOT worth another engine;
      (3) the canonical engine names did not change what the browser is told
          (the MODEL_LOADING sentinel is a wire protocol).

www.jgoy.net · https://server-nexe.org
────────────────────────────────────
"""
from __future__ import annotations

import asyncio
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest
from fastapi import HTTPException
from fastapi.responses import StreamingResponse

from core.endpoints.chat_engines.routing import (
    engine_error_to_http,
    iter_live_engines,
    resolve_engine_cascade,
    should_try_next_engine,
)

_MODULE_KEYS = {"mlx": "mlx_module", "llama_cpp": "llama_cpp_module", "ollama": "ollama_module"}


@pytest.fixture(autouse=True)
def _isolation(monkeypatch):
    """A preferred engine or a model name left in the environment by another
    file rewrites every cascade here; the rate limiter is process-global."""
    from core.dependencies import limiter as _limiter
    from core.runtime_state import get_override, set_override

    for var in ("NEXE_MODEL_ENGINE", "NEXE_OLLAMA_MODEL", "NEXE_DEFAULT_MODEL"):
        monkeypatch.delenv(var, raising=False)
    _prev = get_override("NEXE_MODEL_ENGINE")
    set_override("NEXE_MODEL_ENGINE", None)
    _was_enabled = _limiter.enabled
    _limiter.enabled = False
    yield
    _limiter.enabled = _was_enabled
    set_override("NEXE_MODEL_ENGINE", _prev)


class _Engine:
    """An in-process engine double (no 'model' parameter: MLX/llama.cpp shape).

    ``raises`` is what its chat() throws; ``node`` False makes it the case B260
    is about — registered, but with nothing behind it.
    """

    def __init__(self, reply="ok", raises=None, node=True, window=None):
        self.reply = reply
        self.raises = raises
        self.calls = 0
        if window is not None:
            self.get_context_window = lambda: window
        if node:
            self._node = object()
        else:
            self._node = None

    async def chat(self, messages, system="", session_id="default",
                   stream_callback=None, images=None, thinking_enabled=False, **kwargs):
        self.calls += 1
        if self.raises is not None:
            raise self.raises
        return {
            "response": self.reply, "tokens": 1, "prompt_tokens": 0,
            "context_used": 0, "tokens_per_second": 0.0, "system_tokens": 0,
            "elapsed_ms": 1, "model_used": "fake", "session_id": session_id,
            "cache_hit": False, "timing": {},
        }

    async def is_model_loaded(self, model_name):
        return True


def _state(**engines):
    """A server state whose registry serves exactly these engines, keyed by
    canonical name (mlx=..., ollama=...)."""
    registrations = {}
    items = []
    for name, engine in engines.items():
        key = _MODULE_KEYS[name]
        manifest = MagicMock(spec=["get_module_instance"])
        manifest.get_module_instance.return_value = engine
        registration = MagicMock()
        registration.instance = manifest
        registrations[key] = registration
        item = MagicMock()
        item.name = key
        items.append(item)

    registry = MagicMock()
    registry.list_modules.return_value = items
    registry.get_module.side_effect = registrations.get

    state = MagicMock()
    state.module_manager = MagicMock(registry=registry)
    state.project_root = "/tmp"
    state.config = {}
    state.modules = {_MODULE_KEYS[n]: e for n, e in engines.items()}
    return state


async def _ui_turn(state, body):
    """Drive the real /ui/chat handler and return its response text."""
    from tests.plugins.web_ui_module.test_chat_inner_behavior import _Harness

    harness = _Harness()
    result = await harness.call({"message": "hola", **body}, server_state=state)
    return result


class TestBothDoorsAgreeOnWhatIsLive:

    def test_a_dead_node_is_not_offered_to_either_door(self):
        """B260, and the reason the UI's own table could not express it: the
        module is registered, `get_module_instance()` returns it, `.chat` is
        there — and there is nothing behind it."""
        state = _state(mlx=_Engine(node=False), ollama=_Engine())
        assert resolve_engine_cascade("auto", state) == ["ollama"]
        assert [name for name, _ in iter_live_engines(["mlx", "ollama"], state)] == ["ollama"]

    def test_the_ui_dispatches_to_the_live_one(self):
        mlx, ollama = _Engine(node=False), _Engine()
        state = _state(mlx=mlx, ollama=ollama)
        asyncio.run(_ui_turn(state, {"backend": "mlx"}))
        assert mlx.calls == 0, "the UI dispatched to a module with a dead node"
        assert ollama.calls == 1

    def test_the_ui_has_no_resolver_of_its_own(self, monkeypatch):
        """The behavioural version of "the copy is gone": make the CORE say
        nothing is serviceable and the UI must answer 503. A second table in
        the plugin would still find its engines and answer 200."""
        monkeypatch.setattr(
            "core.endpoints.chat_engines.routing._engine_available",
            lambda engine, app_state: False,
        )
        engine = _Engine()
        state = _state(mlx=engine, ollama=engine)
        with pytest.raises(HTTPException) as raised:
            asyncio.run(_ui_turn(state, {}))
        assert raised.value.status_code == 503
        assert engine.calls == 0


class TestTheCascadeIsTheSameAtBothDoors:

    @pytest.mark.parametrize("alias", ["llamacpp", "llama-cpp", "llama.cpp", "LLAMA.CPP"])
    def test_every_spelling_of_llama_cpp_resolves_alike(self, alias):
        """The UI sends "llamacpp"; the API takes whatever a client wrote. The
        old UI table knew exactly one of these."""
        state = _state(mlx=_Engine(), llama_cpp=_Engine(), ollama=_Engine())
        assert resolve_engine_cascade(alias, state)[0] == "llama_cpp"

    def test_a_fallback_because_nothing_was_live_keeps_its_own_reason(self):
        """The other reason, unchanged: the engine asked for was never live, so
        nothing failed at run time."""
        async def _dispatch(engine, *a, **kw):
            return {"choices": [{"message": {"content": "ok"}}]}

        state = _state(llama_cpp=_Engine(), ollama=_Engine())
        _resp, answered, fallback_from, reason, _model = self._v1_dispatch(state, "mlx", _dispatch)
        assert answered == "llama_cpp"
        assert fallback_from == "mlx"
        assert reason == "preferred_unavailable"

    def test_the_ui_now_honours_the_configured_preferred_engine(self):
        """A quiet consequence of adopting the core resolver, kept on purpose.

        The UI's own table only ever saw `body.backend` and NEXE_MODEL_ENGINE;
        `_get_preferred_engine` also reads plugins.models.preferred_engine from
        the config file, which /status and /v1 have always honoured. So a user
        who set a preferred engine in the config and none in the environment now
        gets it in the chat too, instead of the plain mlx→llama_cpp→ollama
        order. That is the two doors agreeing, but it IS a behaviour change and
        it is pinned here rather than left to be discovered.
        """
        state = _state(mlx=_Engine(), llama_cpp=_Engine(), ollama=_Engine())
        state.config = {"plugins": {"models": {"preferred_engine": "ollama"}}}
        assert resolve_engine_cascade("auto", state)[0] == "ollama"

    def test_an_explicit_pick_falls_through_the_canonical_order(self):
        state = _state(llama_cpp=_Engine(), ollama=_Engine())
        assert resolve_engine_cascade("mlx", state) == ["llama_cpp", "ollama"]

    def test_the_ui_retries_the_next_engine_when_one_crashes(self):
        mlx = _Engine(raises=RuntimeError("model went bad"))
        llama = _Engine(reply="from llama")
        state = _state(mlx=mlx, llama_cpp=llama, ollama=_Engine(reply="from ollama"))
        asyncio.run(_ui_turn(state, {"backend": "mlx"}))
        assert mlx.calls == 1
        assert llama.calls == 1, "the cascade skipped llama.cpp and went to ollama"

    def test_v1_retries_the_next_engine_when_one_crashes(self):
        """#1036 (C2.4): drives the REAL `_forward_to_mlx` (no patch of
        `_dispatch_to_engine`, unlike before C2.4) with a fake MLX module that
        crashes in `chat()`. This used to be masked by two independent
        mechanisms: mocking `_dispatch_to_engine` skipped the forwarders
        entirely, AND the real forwarders had their own fallback-to-Ollama
        that jumped straight past llama.cpp. Both are gone: the cascade in
        `_dispatch_through_cascade` is now the only thing deciding what runs
        next, and it must land on llama.cpp (not skip to ollama)."""
        mlx = _Engine(raises=RuntimeError("model went bad"))
        llama = _Engine(reply="from llama")
        state = _state(mlx=mlx, llama_cpp=llama, ollama=_Engine(reply="from ollama"))
        state.session_manager = None  # no mirror bookkeeping needed for this test

        import core.endpoints.chat as chat_mod
        from core.endpoints.chat_schemas import ChatCompletionRequest, Message

        body = ChatCompletionRequest(messages=[Message(role="user", content="hola")], engine="mlx")
        request = MagicMock()
        request.app.state = state
        request.headers.get = lambda key, default=None: default if default is not None else ""

        response, answered, fallback_from, reason, _model = asyncio.run(
            chat_mod._dispatch_through_cascade(body, request, [], "hola", "sid", "mlx", None)
        )
        assert mlx.calls == 1
        assert llama.calls == 1, "the cascade skipped llama.cpp and went straight to ollama"
        assert answered == "llama_cpp"
        assert fallback_from == "mlx", "the headers must name the engine that did not answer"
        assert reason == "execution_failed", (
            "the client is told WHY it got another engine, and this one was live "
            "and broke — reporting 'preferred_unavailable' describes a different event"
        )
        assert response["choices"][0]["message"]["content"] == "from llama"

    def test_v1_stream_error_before_first_byte_falls_to_next_engine(self):
        """#1036 (C2.4): the SAME cascade behaviour, but streaming — the
        forwarder must peek the generator's first chunk before returning a
        StreamingResponse, so an engine that dies before any token reaches
        the client is still retried, not just its non-streaming twin above.
        `_Engine.raises` never calls `stream_callback`, matching a crash
        before generation starts."""
        mlx = _Engine(raises=RuntimeError("model went bad"))
        llama = _Engine(reply="from llama")
        state = _state(mlx=mlx, llama_cpp=llama, ollama=_Engine(reply="from ollama"))
        state.session_manager = None

        import core.endpoints.chat as chat_mod
        from core.endpoints.chat_schemas import ChatCompletionRequest, Message

        body = ChatCompletionRequest(messages=[Message(role="user", content="hola")], engine="mlx", stream=True)
        request = MagicMock()
        request.app.state = state
        request.headers.get = lambda key, default=None: default if default is not None else ""

        response, answered, fallback_from, reason, _model = asyncio.run(
            chat_mod._dispatch_through_cascade(body, request, [], "hola", "sid", "mlx", None)
        )
        assert mlx.calls == 1
        assert llama.calls == 1, "the cascade skipped llama.cpp and went straight to ollama"
        assert answered == "llama_cpp"
        assert fallback_from == "mlx"
        assert reason == "execution_failed"
        assert isinstance(response, StreamingResponse)

    def test_the_prompt_is_refitted_for_the_engine_that_answers(self):
        """The fit guard (#976) sized the prompt for the engine that was
        RESOLVED, and this loop can hand it to a different one. A prompt built
        for a 32k window on a 2048-token engine is the crash #976 exists to
        stop, on the one path nobody exercises."""
        seen = {}

        async def _dispatch(engine, messages, *a, **kw):
            seen[engine] = sum(len(m.get("content") or "") for m in messages)
            if engine == "mlx":
                raise RuntimeError("boom")
            return {"choices": [{"message": {"content": "ok"}}]}

        state = _state(mlx=_Engine(window=32768), ollama=_Engine(window=2048))
        big_prompt = [
            {"role": "system", "content": "S" * 4000},
            {"role": "user", "content": "H" * 100_000},
            {"role": "user", "content": "i ara?"},
        ]
        import core.endpoints.chat as chat_mod
        from core.endpoints.chat_schemas import ChatCompletionRequest, Message

        body = ChatCompletionRequest(messages=[Message(role="user", content="hola")], engine="mlx")
        request = MagicMock()
        request.app.state = state
        with patch.object(chat_mod, "_dispatch_to_engine", _dispatch):
            asyncio.run(chat_mod._dispatch_through_cascade(
                body, request, big_prompt, "hola", "sid", "mlx", None,
            ))
        assert seen["ollama"] < seen["mlx"], (
            "the fallback engine got the prompt sized for the one that failed"
        )
        assert seen["ollama"] <= 2048 * 4, "and it does not fit its window"

    def _v1_dispatch(self, state, requested, dispatch):
        import core.endpoints.chat as chat_mod
        from core.endpoints.chat_schemas import ChatCompletionRequest, Message

        body = ChatCompletionRequest(messages=[Message(role="user", content="hola")], engine=requested)
        request = MagicMock()
        request.app.state = state
        with patch.object(chat_mod, "_dispatch_to_engine", dispatch):
            return asyncio.run(
                chat_mod._dispatch_through_cascade(
                    body, request, [], "hola", "sid", requested, None,
                )
            )


class TestTheThirdCopyOfTheOrder:
    """The backend dropdown answers a different question — which backend to show
    as active, judged on what the scan listed and whether it is connected, not
    on whether a module has a live node — but it must offer them in the SAME
    order. It was a third table aligned by hand, and its comment pointed at
    routes_chat._resolve_engines, which block 5 deleted."""

    def test_the_dropdown_follows_the_core_cascade(self, monkeypatch):
        from plugins.web_ui_module.api import routes_auth

        assert routes_auth._auto_backend_cascade() == ("mlx", "llamacpp", "ollama")
        monkeypatch.setattr(
            "core.endpoints.chat_engines.routing.ENGINE_CASCADE",
            ["ollama", "mlx", "llama_cpp"],
        )
        assert routes_auth._auto_backend_cascade() == ("ollama", "mlx", "llamacpp"), (
            "the dropdown kept its own order after the cascade changed"
        )


class TestASelectedModelMeetsTheCascade:
    """Characterisation, not endorsement: what the product does today when the
    UI has a model selected AND the engine serving it fails mid-turn.

    A model name belongs to one engine — an MLX directory is not a .gguf — so
    the next engine in the cascade is asked to load something it cannot, its
    validation raises ValueError("not found"), and that is terminal. The user
    gets a 404 about a model instead of the fallback answer the cascade exists
    to give. Unchanged by F-D block 5 (the old loop switched per engine inside
    the same try), so this pins it rather than fixing it under cover of a
    refactor.
    """

    def test_a_model_from_the_failed_engine_ends_the_turn(self):
        mlx = _Engine(raises=RuntimeError("corrupt model"))
        llama = _Engine(reply="from llama")
        llama.switch_model_by_path = MagicMock(
            side_effect=ValueError("Model 'Qwen3-8B-MLX' not found: not a GGUF file")
        )
        state = _state(mlx=mlx, llama_cpp=llama, ollama=_Engine())
        with pytest.raises(HTTPException) as raised:
            asyncio.run(_ui_turn(state, {"backend": "mlx", "model": "Qwen3-8B-MLX"}))
        assert raised.value.status_code == 404
        assert llama.calls == 0, "the fallback engine never got to answer"


class TestWhichErrorsAreWorthAnotherEngine:
    """One decision, in one place. It was four except clauses in the plugin and
    nothing at all in the core."""

    @pytest.mark.parametrize("exc,status", [
        (ValueError("Model 'x' not found: no MLX model"), 404),
        (ValueError("bad request"), 400),
        (ConnectionError("refused"), 503),
        (TimeoutError("slow"), 504),
    ])
    def test_a_terminal_error_keeps_its_meaning(self, exc, status):
        assert should_try_next_engine(exc) is False
        assert engine_error_to_http(exc, "mlx")[0] == status

    @pytest.mark.parametrize("exc", [RuntimeError("oom"), MemoryError(), KeyError("k")])
    def test_an_engine_failing_now_is_worth_the_next_one(self, exc):
        assert should_try_next_engine(exc) is True
        assert engine_error_to_http(exc, "mlx") is None

    def test_an_http_exception_is_the_answer_not_a_crash(self):
        """How the /v1 forwarders report a backend that is down. Retrying it
        would turn a deliberate 502 into another engine's 200."""
        exc = HTTPException(status_code=502, detail="ollama is down")
        assert should_try_next_engine(exc) is False
        assert engine_error_to_http(exc, "ollama") is None

    def test_the_ui_stops_on_a_terminal_error_instead_of_trying_on(self):
        mlx = _Engine(raises=ValueError("nope"))
        llama = _Engine()
        state = _state(mlx=mlx, llama_cpp=llama, ollama=_Engine())
        with pytest.raises(HTTPException) as raised:
            asyncio.run(_ui_turn(state, {"backend": "mlx"}))
        assert raised.value.status_code == 400
        assert llama.calls == 0, "a bad request was retried on another engine"

    def test_v1_stops_on_a_terminal_error_instead_of_trying_on(self):
        tried = []

        async def _dispatch(engine, *a, **kw):
            tried.append(engine)
            raise HTTPException(status_code=502, detail="down")

        state = _state(mlx=_Engine(), ollama=_Engine())
        with pytest.raises(HTTPException) as raised:
            TestTheCascadeIsTheSameAtBothDoors()._v1_dispatch(state, "mlx", _dispatch)
        assert raised.value.status_code == 502
        assert tried == ["mlx"]


class TestTheBrowserWasNotTold:
    """The engine names in the loop went from module keys to canonical names,
    and one of them reaches the browser: the MODEL_LOADING sentinel carries it
    and nexe-chat.js renders a label from it. This is that transform."""

    @staticmethod
    def _js_label(engine_name: str) -> str:
        # nexe-chat.js: loadingBackend.replace('_module', '').toUpperCase()
        return engine_name.replace("_module", "").upper()

    @pytest.mark.parametrize("canonical,module_key", list(_MODULE_KEYS.items()))
    def test_the_label_is_identical_either_way(self, canonical, module_key):
        assert self._js_label(canonical) == self._js_label(module_key)


class TestNothingLive:

    def test_an_empty_cascade_is_a_503_and_not_a_fake_reply(self):
        """#884: a failed request is not an assistant turn."""
        state = _state()
        with pytest.raises(HTTPException) as raised:
            asyncio.run(_ui_turn(state, {}))
        assert raised.value.status_code == 503
        assert raised.value.detail == "No AI engine available"


class TestTheLiveInstanceIsTheLoaderS:
    """The five-guard walk is gone because the loader already did it: what
    `iter_live_engines` yields is the object `_register_plugin_instance` put in
    `app.state.modules`, not a fresh `get_module_instance()` per request."""

    def test_it_yields_the_registered_instance(self):
        ollama = _Engine()
        state = _state(ollama=ollama)
        assert [module for _, module in iter_live_engines(["ollama"], state)] == [ollama]

    def test_a_module_without_chat_is_skipped_not_dispatched_to(self):
        state = SimpleNamespace(modules={"ollama_module": object()}, config={})
        assert list(iter_live_engines(["ollama"], state)) == []


class TestTheSwitchIsNotOnTheApiDoor:
    """Decided on purpose: the capability moved to the core, the API door does
    not plug it in. /v1 runs the model that is loaded and reports it (B075-C3);
    giving it a per-request switch is a product decision, not a side effect.

    Both halves are driven, not inspected. The first version of this class
    asserted `engine.switch_model_by_path.call_count == 0` on a mock nothing had
    touched — true of any mock, in any codebase, forever — and grepped
    routes_chat.py for a substring to prove the other half.
    """

    def test_v1_does_not_switch_the_model_even_when_asked_for_one(self):
        engine = MagicMock()
        state = _state(ollama=_Engine())
        state.modules["ollama_module"] = engine
        engine._node = object()

        async def _dispatch(name, *a, **kw):
            return {"choices": [{"message": {"content": "ok"}}]}

        import core.endpoints.chat as chat_mod
        from core.endpoints.chat_schemas import ChatCompletionRequest, Message

        body = ChatCompletionRequest(
            messages=[Message(role="user", content="hola")],
            model="a-different-model", engine="ollama",
        )
        request = MagicMock()
        request.app.state = state
        with patch.object(chat_mod, "_dispatch_to_engine", _dispatch):
            asyncio.run(chat_mod._dispatch_through_cascade(
                body, request, [], "hola", "sid", "ollama", None,
            ))
        assert engine.switch_model_by_path.call_count == 0, (
            "/v1 asked an engine to load another model: that is a product change"
        )

    def test_the_ui_does_switch_when_the_selector_sends_a_model(self):
        engine = _Engine()
        engine.switch_model_by_path = MagicMock(return_value=True)
        state = _state(ollama=engine)
        with patch(
            "core.endpoints.chat_engines.model_switch.resolve_local_model_path",
            lambda name: name,
        ):
            asyncio.run(_ui_turn(state, {"model": "un-altre-model"}))
        assert engine.switch_model_by_path.call_count == 1


@pytest.mark.asyncio
async def test_the_ui_answers_with_the_engine_that_worked():
    """End to end through the real handler: the first engine crashes, the reply
    is the second one's."""
    mlx = _Engine(raises=RuntimeError("boom"))
    llama = _Engine(reply="resposta de llama")
    state = _state(mlx=mlx, llama_cpp=llama, ollama=_Engine(reply="resposta d'ollama"))
    from tests.plugins.web_ui_module.test_chat_inner_behavior import _Harness

    result = await _Harness().call(
        {"message": "hola", "backend": "mlx"}, server_state=state,
    )
    assert "llama" in str(result), f"answered with the wrong engine: {result}"


class TestTheCascadeNamesTheModelThatAnswered:
    """#1054: `served_by` names the ENGINE ("mlx", "ollama"); what it loaded is
    a different string entirely, and /v1's LLM counter had no way to reach it —
    every call was billed with `model=null` while the UI door billed the real
    name. The cascade reports it as the fifth element, read off the response the
    forwarder has already built, so no forwarder signature changes.

    Mutation guard: return `None` instead of `served_model_of(response)` in
    `_dispatch_through_cascade` and the first two go red.
    """

    def _cascade_over(self, response):
        """Run the real cascade with a forwarder that answers `response`."""
        import core.endpoints.chat as chat_mod
        from core.endpoints.chat_schemas import ChatCompletionRequest, Message

        async def _dispatch(*_args, **_kwargs):
            return response

        body = ChatCompletionRequest(messages=[Message(role="user", content="hola")], engine="mlx")
        request = MagicMock()
        request.app.state = _state(mlx=_Engine())
        with patch.object(chat_mod, "_dispatch_to_engine", _dispatch):
            return asyncio.run(chat_mod._dispatch_through_cascade(
                body, request, [], "hola", "sid", "mlx", None,
            ))

    def test_a_json_reply_is_asked_for_the_model_it_already_carries(self):
        from core.endpoints.chat_engines._common import build_openai_response

        reply = build_openai_response({"response": "hola"}, "gemma-4-e4b-it-4bit", "mlx")
        _resp, answered, _fb, _reason, model = self._cascade_over(reply)

        assert answered == "mlx", "the engine that answered"
        assert model == "gemma-4-e4b-it-4bit", "and the model it loaded — not the same string"

    def test_a_stream_carries_the_name_its_forwarder_resolved(self):
        """The half that was actually broken: a `StreamingResponse` exposes the
        model nowhere, so the forwarder marks it (`mark_served_model`) with the
        name it resolved synchronously before building the response."""
        from core.endpoints.chat_engines._common import mark_served_model

        async def _body():
            yield b"data: {}\n\n"

        stream = mark_served_model(StreamingResponse(_body()), "Qwen3.5-27B-4bit")
        _resp, _answered, _fb, _reason, model = self._cascade_over(stream)

        assert model == "Qwen3.5-27B-4bit"

    def test_a_response_that_names_no_model_is_reported_unknown_not_guessed(self):
        """A test double (or an engine that never said) leaves this empty. The
        counter then logs an unknown model as unknown — the one thing it must
        not do is put the ENGINE's name there and call it a model."""
        _resp, answered, _fb, _reason, model = self._cascade_over({"choices": []})

        assert answered == "mlx"
        assert model is None
