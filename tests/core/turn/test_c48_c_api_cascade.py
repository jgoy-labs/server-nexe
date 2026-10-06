"""C4.8-c: what /v1 tells the core's cascade (`core/turn/api_cascade.py`) and the
first-chunk peek that moved out of the three forwarders
(`_streaming.peek_stream`). The loop itself is `test_c48_b_engine_claim.py`;
what a client sees at each door is the part 0 matrix.
"""
from __future__ import annotations

import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import HTTPException
from fastapi.responses import StreamingResponse

from core.endpoints.chat_engines._streaming import NEXE_END, peek_stream, stream_end
from core.turn.api_cascade import ApiDoor, ask_again, dispatch_v1


# ── the peek ────────────────────────────────────────────────────────────────

class _Stream:
    """An async generator that remembers whether it was closed."""

    def __init__(self, chunks, raises=None):
        self.chunks, self.raises, self.closed = list(chunks), raises, False
        self.gen = self._gen()

    async def _gen(self):
        try:
            if self.raises is not None:
                raise self.raises
            for chunk in self.chunks:
                yield chunk
        finally:
            self.closed = True


def _response(stream, headers=None):
    response = StreamingResponse(stream.gen, media_type="text/event-stream", headers=headers or {})
    return response


async def _read(response):
    return [c async for c in response.body_iterator]


async def test_the_peek_puts_the_first_chunk_back_in_front_and_keeps_the_response():
    stream = _Stream(["a", "b", "c"])
    response = _response(stream, {"X-Nexe-Engine": "mlx"})
    same = response
    assert await peek_stream(response) is None
    assert response is same and response.headers["X-Nexe-Engine"] == "mlx"
    assert await _read(response) == ["a", "b", "c"]


async def test_the_peek_raises_what_the_engine_raised_before_its_first_token():
    stream = _Stream([], raises=RuntimeError("model went bad"))
    with pytest.raises(RuntimeError, match="model went bad"):
        await peek_stream(_response(stream))


async def test_the_peek_calls_a_stream_that_ends_without_a_word_a_failure_and_closes_it():
    stream = _Stream([])
    with pytest.raises(RuntimeError, match="engine produced no stream"):
        await peek_stream(_response(stream))
    assert stream.closed


async def test_the_peek_calls_a_first_chunk_that_is_a_failure_sentinel_a_failure_and_closes_it():
    stream = _Stream([stream_end(failure="stream_cap_exceeded", truncated=True), "never"])
    with pytest.raises(RuntimeError, match="stream_cap_exceeded"):
        await peek_stream(_response(stream))
    assert stream.closed


async def test_a_first_chunk_that_is_a_clean_end_is_an_empty_answer_not_a_failure():
    clean = stream_end(finish_reason="stop")
    stream = _Stream([clean])
    response = _response(stream)
    await peek_stream(response)
    assert await _read(response) == [clean]
    assert NEXE_END in clean


async def test_a_dict_chunk_that_is_not_a_sentinel_passes():
    chunk = {"thinking": "hm", "content": "x"}
    response = _response(_Stream([chunk]))
    await peek_stream(response)
    assert await _read(response) == [chunk]


async def test_closing_the_peeked_body_closes_the_engine_stream_underneath():
    stream = _Stream(["a", "b"])
    response = _response(stream)
    await peek_stream(response)
    await response.body_iterator.__anext__()
    await response.body_iterator.aclose()
    assert stream.closed


# ── the door ────────────────────────────────────────────────────────────────

def _door(**kw):
    request = MagicMock()
    request.app.state = SimpleNamespace(modules={}, config={})
    args = dict(body=SimpleNamespace(), request=request, messages=[{"role": "user", "content": "hi"}],
                last_user_msg="hi", session_id="s1", cancel_event="EV", images=None)
    args.update(kw)
    return ApiDoor(args["body"], args["request"], args["messages"], args["last_user_msg"], args["session_id"],
                   cancel_event=args["cancel_event"], images=args["images"])


class _Blind:
    def can_see_images(self):
        return False


class _Sighted:
    def can_see_images(self):
        return True


def test_only_a_fallback_that_cannot_see_is_skipped_and_only_when_there_is_an_image():
    with_image = _door(images=["IMG"])
    assert with_image.skip(1, "llama_cpp", _Blind()) is True
    assert with_image.skip(0, "mlx", _Blind()) is False           # the one asked for is never skipped
    assert with_image.skip(1, "llama_cpp", _Sighted()) is False
    assert with_image.skip(1, "ollama", object()) is False         # an engine that does not say is left to it
    assert with_image.skip(1, "ollama", None) is False
    assert _door(images=None).skip(1, "llama_cpp", _Blind()) is False
    assert _door(images=[]).skip(1, "llama_cpp", _Blind()) is False


async def test_each_attempt_asks_the_forwarder_with_the_prompt_the_door_got_and_everything_else():
    door = _door(images=["IMG"])
    body, request = door.body, door.request
    forwarder = AsyncMock(return_value={"choices": []})
    with patch("core.endpoints.chat._dispatch_to_engine", forwarder):
        opened = await door.read_first(0, "mlx", object(), ["FITTED"])
    forwarder.assert_awaited_once_with(
        "mlx", ["FITTED"], body, request, request.app.state, "hi", "s1", cancel_event="EV", images=["IMG"],
    )
    assert opened.value == {"choices": []} and opened.failure is None


async def test_a_stream_from_the_forwarder_is_read_to_its_first_chunk_before_it_counts():
    door = _door()
    stream = _Stream([], raises=RuntimeError("before any token"))
    with patch("core.endpoints.chat._dispatch_to_engine", AsyncMock(return_value=_response(stream))):
        with pytest.raises(RuntimeError, match="before any token"):
            await door.read_first(0, "mlx", object(), [])


async def test_a_stream_that_speaks_is_handed_on_with_its_first_chunk_in_front():
    door = _door()
    stream = _Stream(["a", "b"])
    with patch("core.endpoints.chat._dispatch_to_engine", AsyncMock(return_value=_response(stream))):
        opened = await door.read_first(0, "mlx", object(), [])
    assert await _read(opened.value) == ["a", "b"]


async def test_the_prompt_is_fitted_to_this_engines_window_every_time_even_the_first():
    door = _door()
    seen = []

    def fit(messages, window, body):
        seen.append((messages, window, body))
        return ["FITTED"]

    with patch("core.endpoints.chat._fit_v1_messages_to_window", fit), \
            patch("core.endpoints.chat.get_effective_context_window", lambda name, state: {"mlx": 111}[name]):
        assert await door.prepare(0, "mlx", object()) == ["FITTED"]
    assert seen == [(door.messages, 111, door.body)]


def test_each_attempt_is_counted_under_its_engine_with_its_outcome():
    door = _door()
    with patch("core.endpoints.chat._record_engine_metrics") as record:
        door.observe("mlx", True, 12.5)
        door.observe("ollama", False, 13.5)
    assert [c.args for c in record.call_args_list] == [("mlx", "success", 12.5), ("ollama", "error", 13.5)]


def test_when_everything_failed_the_door_ends_as_the_core_does_a_503_with_the_first_error_curated():
    door = _door()
    ended = door.exhausted(RuntimeError("secret path /Users/x"), RuntimeError("last"))
    assert isinstance(ended, HTTPException) and ended.status_code == 503
    assert ended.detail == "S'ha produït un error en generar la resposta. Torna-ho a provar."
    assert "secret" not in ended.detail


# ── the candidates and the answer ───────────────────────────────────────────

class _Module:
    def __init__(self, can_continue=True, node=True):
        self._can = can_continue
        self.asked = None
        if node:
            self._node = object()

    def can_continue(self, model=None):
        self.asked = model
        return self._can

    async def chat(self, *a, **k):
        raise AssertionError("not called here")


def _state(**modules):
    keys = {"mlx": "mlx_module", "llama_cpp": "llama_cpp_module", "ollama": "ollama_module"}
    return SimpleNamespace(modules={keys[n]: m for n, m in modules.items()}, config={})


@pytest.fixture(autouse=True)
def _env(monkeypatch):
    monkeypatch.setenv("NEXE_MODEL_ENGINE", "auto")


async def _asked(state, body, *, resume=False, engine="mlx"):
    """The engines the forwarder is asked, in order, for a turn with `body`."""
    asked = []
    request = MagicMock()
    request.app.state = state

    async def forward(name, *a, **k):
        asked.append(name)
        return {"model": "m"}

    with patch("core.endpoints.chat._dispatch_to_engine", forward), \
            patch("core.endpoints.chat._fit_v1_messages_to_window", lambda m, w, b: m), \
            patch("core.endpoints.chat.get_effective_context_window", lambda n, s: 4096), \
            patch("core.endpoints.chat._record_engine_metrics"):
        await dispatch_v1(body, request, [], "hi", "s", engine, None, resume=resume)
    return asked


async def test_nothing_live_is_a_503_and_no_forwarder_is_asked():
    """R4 (decided provisionally 06/10: «/v1 without live engines → 503, like the
    web»). It used to ask the Ollama daemon all the same, registered or not."""
    asked = []

    async def forward(name, *a, **k):
        asked.append(name)
        return {"model": "m"}

    request = MagicMock()
    request.app.state = _state()
    with patch("core.endpoints.chat._dispatch_to_engine", forward):
        with pytest.raises(HTTPException) as caught:
            await dispatch_v1(SimpleNamespace(engine="auto", resume=False, model=None), request, [], "hi", "s",
                              "ollama", None)
    assert (caught.value.status_code, caught.value.detail, asked) == (503, "No AI engine available", [])


async def test_the_candidates_are_the_live_engines_in_the_cascades_order():
    state = _state(ollama=_Module(), mlx=_Module())
    body = SimpleNamespace(engine="auto", resume=False, model=None)
    assert await _asked(state, body) == ["mlx"]                  # the first that answers
    body = SimpleNamespace(engine="ollama", resume=False, model=None)
    assert await _asked(state, body, engine="ollama") == ["ollama"]


async def test_a_continue_narrows_the_candidates_and_asks_with_the_requests_model():
    mlx, ollama = _Module(can_continue=False), _Module(can_continue=True)
    state = _state(mlx=mlx, ollama=ollama)
    body = SimpleNamespace(engine="auto", resume=False, model="qwen")
    assert await _asked(state, body, resume=True) == ["ollama"]
    assert mlx.asked == "qwen" and ollama.asked == "qwen"
    body = SimpleNamespace(engine="auto", resume=True, model="qwen")        # the body can say it too
    assert await _asked(state, body, resume=False) == ["ollama"]


async def test_a_continue_that_no_engine_can_resume_is_a_400():
    state = _state(mlx=_Module(can_continue=False))
    with pytest.raises(HTTPException) as caught:
        await _asked(state, SimpleNamespace(engine="auto", resume=True, model=None), resume=True)
    assert caught.value.status_code == 400


async def test_a_body_that_only_looks_like_it_resumes_does_not():
    """A MagicMock grows a truthy `.resume`; only an explicit True counts."""
    mlx = _Module(can_continue=False)
    assert await _asked(_state(mlx=mlx), MagicMock(engine="auto")) == ["mlx"]
    assert mlx.asked is None


async def _dispatch(state, answers, *, engine="mlx", preferred=None, body=None, lang=None):
    body = body or SimpleNamespace(engine="auto", resume=False, model=None)
    request = MagicMock()
    request.app.state = state

    async def forward(name, messages, *a, **k):
        what = answers[name]
        if isinstance(what, Exception):
            raise what
        return what

    with patch("core.endpoints.chat._dispatch_to_engine", forward), \
            patch("core.endpoints.chat._fit_v1_messages_to_window", lambda m, w, b: m), \
            patch("core.endpoints.chat.get_effective_context_window", lambda n, s: 4096), \
            patch("core.endpoints.chat._record_engine_metrics"):
        return await dispatch_v1(body, request, [], "hi", "s1", engine, preferred, lang=lang)


async def test_the_answer_names_the_engine_that_answered_and_the_one_it_replaced():
    state = _state(mlx=_Module(), llama_cpp=_Module(), ollama=_Module())
    reply = {"choices": [{"message": {"content": "from llama"}}], "model": "gguf"}
    got = await _dispatch(state, {"mlx": RuntimeError("bad"), "llama_cpp": reply})
    response, served_by, fallback_from, reason, model = got
    assert response is reply and served_by == "llama_cpp"
    assert (fallback_from, reason) == ("mlx", "execution_failed")
    assert model == "gguf"


async def test_the_engine_that_was_asked_for_answering_is_no_fallback():
    state = _state(mlx=_Module(), ollama=_Module())
    got = await _dispatch(state, {"mlx": {"model": "m"}})
    assert got[1:4] == ("mlx", None, "preferred_unavailable")


async def test_a_fallback_the_resolution_already_made_keeps_its_own_origin():
    state = _state(ollama=_Module())
    got = await _dispatch(state, {"ollama": {"model": "m"}}, engine="ollama", preferred="mlx")
    assert got[1:4] == ("ollama", "mlx", "preferred_unavailable")


async def test_an_engine_that_was_not_live_and_one_that_broke_are_told_apart():
    state = _state(llama_cpp=_Module())
    got = await _dispatch(state, {"llama_cpp": {"model": "m"}}, engine="mlx")
    assert got[1:4] == ("llama_cpp", "mlx", "preferred_unavailable")


async def test_every_engine_failing_retryably_is_a_503_telling_the_first_error_curated():
    state = _state(mlx=_Module(), llama_cpp=_Module())
    with pytest.raises(HTTPException) as caught:
        await _dispatch(state, {"mlx": RuntimeError("OutOfMemory: mlx died"), "llama_cpp": RuntimeError("llama died")})
    assert caught.value.status_code == 503
    assert caught.value.detail == "Memòria insuficient. Tanca altres aplicacions per alliberar memòria i torna-ho a provar."


async def test_a_final_error_is_the_answer_and_nobody_else_is_asked():
    state = _state(mlx=_Module(), llama_cpp=_Module())
    asked = []

    async def forward(name, *a, **k):
        asked.append(name)
        raise HTTPException(status_code=502, detail="down")

    request = MagicMock()
    request.app.state = state
    with patch("core.endpoints.chat._dispatch_to_engine", forward), \
            patch("core.endpoints.chat._fit_v1_messages_to_window", lambda m, w, b: m), \
            patch("core.endpoints.chat.get_effective_context_window", lambda n, s: 4096), \
            patch("core.endpoints.chat._record_engine_metrics"):
        with pytest.raises(HTTPException) as caught:
            await dispatch_v1(SimpleNamespace(engine="auto", resume=False, model=None), request, [], "hi", "s", "mlx", None)
    assert (caught.value.status_code, asked) == (502, ["mlx"])


async def test_a_cancel_event_does_not_stop_this_door_from_asking_the_next_engine():
    """N4, as it is today: the API door keeps asking for an answer nobody will read."""
    import threading

    event = threading.Event()
    event.set()
    state = _state(mlx=_Module(), llama_cpp=_Module())
    request = MagicMock()
    request.app.state = state

    async def forward(name, *a, **k):
        if name == "mlx":
            raise RuntimeError("died with the client")
        return {"model": "m"}

    with patch("core.endpoints.chat._dispatch_to_engine", forward), \
            patch("core.endpoints.chat._fit_v1_messages_to_window", lambda m, w, b: m), \
            patch("core.endpoints.chat.get_effective_context_window", lambda n, s: 4096), \
            patch("core.endpoints.chat._record_engine_metrics"):
        got = await dispatch_v1(SimpleNamespace(engine="auto", resume=False, model=None), request, [], "hi", "s",
                                "mlx", None, cancel_event=event)
    assert got[1] == "llama_cpp"


# ── the forwarders no longer read their own first chunk ───────────────────────

class _CountingEngine:
    def __init__(self):
        self.calls = 0
        self._node = object()

    async def chat(self, messages, system="", session_id="default", stream_callback=None, **kwargs):
        self.calls += 1
        if stream_callback is not None:
            stream_callback("hola")
        return {"finish_reason": "stop"}


def _forward_args(engine_module_key, engine):
    from core.endpoints.chat_schemas import ChatCompletionRequest, Message

    req = MagicMock()
    req.app.state = SimpleNamespace(modules={engine_module_key: engine}, config={})
    req.headers.get = lambda key, default=None: default if default is not None else ""
    request = ChatCompletionRequest(messages=[Message(role="user", content="hi")], stream=True)
    return [{"role": "user", "content": "hi"}], request, req


@pytest.mark.parametrize("key, forwarder", [("mlx_module", "_forward_to_mlx"),
                                            ("llama_cpp_module", "_forward_to_llama_cpp")])
async def test_an_in_process_forwarder_returns_its_stream_unread_and_the_cascade_reads_it(key, forwarder):
    import core.endpoints.chat as chat_mod

    engine = _CountingEngine()
    messages, request, req = _forward_args(key, engine)
    response = await getattr(chat_mod, forwarder)(messages, request, req)
    assert isinstance(response, StreamingResponse)
    assert engine.calls == 0, "the forwarder started reading: the peek is the cascade's now"
    await peek_stream(response)
    assert engine.calls == 1
    chunks = await _read(response)
    assert any("hola" in str(c) for c in chunks)


async def test_the_ollama_forwarder_returns_its_stream_unread_too():
    from core.endpoints.chat_engines import ollama as ollama_forwarder

    class _NoNetwork:
        def __init__(self, *a, **k):
            raise AssertionError("the forwarder opened a connection before anybody read the stream")

    with patch.object(ollama_forwarder.httpx, "AsyncClient", _NoNetwork):
        response = await ollama_forwarder._ollama_streaming_response(
            "http://ollama.invalid/api/chat", {"model": "qwen"}, None, None, None, None,
        )
        assert isinstance(response, StreamingResponse)
        assert response.headers["X-Nexe-Engine"] == "ollama"
        with pytest.raises(AssertionError, match="opened a connection"):
            await peek_stream(response)   # the first read is what reaches for the network


async def test_the_ollama_forwarder_names_the_fallback_it_was_given_in_the_headers():
    from core.endpoints.chat_engines import ollama as ollama_forwarder

    response = await ollama_forwarder._ollama_streaming_response(
        "http://ollama.invalid/api/chat", {"model": "qwen"}, None, None, "mlx", "execution_failed",
    )
    assert response.headers["X-Nexe-Fallback-From"] == "mlx"
    assert response.headers["X-Nexe-Fallback-Reason"] == "execution_failed"
    from core.endpoints.chat_engines._common import served_model_of
    assert served_model_of(response) == "qwen"
    await response.body_iterator.aclose()


async def test_a_resolution_fallback_that_then_breaks_still_names_the_engine_first_asked_for():
    """mlx was asked for and was not live, so llama.cpp was resolved ("mlx" is the
    origin); llama.cpp then breaks and Ollama answers: the client is told it
    started from mlx, not from the engine that was only the second choice."""
    state = _state(llama_cpp=_Module(), ollama=_Module())
    got = await _dispatch(state, {"llama_cpp": RuntimeError("bad"), "ollama": {"model": "m"}},
                          engine="llama_cpp", preferred="mlx")
    assert got[1:4] == ("ollama", "mlx", "execution_failed")


async def test_the_503_of_a_cascade_that_found_nobody_speaks_the_turns_language():
    state = _state(mlx=_Module())
    for lang, words in [
        ("en", "An error occurred while generating the response. Please try again."),
        ("es", "Se ha producido un error al generar la respuesta. Inténtalo de nuevo."),
    ]:
        with pytest.raises(HTTPException) as caught:
            await _dispatch(state, {"mlx": RuntimeError("x")}, lang=lang)
        assert caught.value.detail == words


def test_the_door_keeps_the_language_it_was_given():
    door = ApiDoor(SimpleNamespace(), MagicMock(), [], None, "s", cancel_event=None, images=None, lang="es")
    assert door.lang == "es"


# ── what the three /v1 callers hand the cascade ──────────────────────────────

async def test_both_v1_generate_calls_hand_the_cascade_the_turns_language_and_cancel_state():
    from fastapi import BackgroundTasks

    from core.turn.adapters_api import api_adapters
    from core.turn.gate import EngineGate

    from .test_c48_d_engine_hold import _v1_ctx

    reply = {"choices": [{"message": {"content": "ok"}}], "model": "m"}
    cascade = AsyncMock(return_value=(reply, "ollama", None, "preferred_unavailable", "m"))

    async def stream_reply():
        yield "data: {}\n\n"

    # JSON generate
    gate = EngineGate(slots=1)
    ctx = _v1_ctx(gate, stream=False)
    ctx.lang = "es"
    with patch("core.turn.api_cascade.dispatch_v1", cascade):
        await api_adapters(BackgroundTasks())["generate"](ctx)
    assert cascade.await_args.kwargs["lang"] == "es"
    assert cascade.await_args.kwargs["cancel_event"] is ctx.cancel_token[0]
    assert cascade.await_args.kwargs["resume"] is False

    # streaming generate
    cascade.reset_mock()
    response = StreamingResponse(stream_reply(), media_type="text/event-stream")
    cascade.return_value = (response, "ollama", None, "preferred_unavailable", "m")
    gate = EngineGate(slots=1)
    ctx = _v1_ctx(gate, stream=True)
    ctx.lang = "en"
    with patch("core.turn.api_cascade.dispatch_v1", cascade):
        generator = api_adapters(BackgroundTasks(), streaming=True)["generate"](ctx)
        await generator.__anext__()
        await generator.aclose()
    assert cascade.await_args.kwargs["lang"] == "en"
    assert cascade.await_args.kwargs["cancel_event"] is ctx.cancel_token[0]



# ── R1: the second call goes to the engine that answered ─────────────────────

async def test_the_second_call_is_made_to_the_named_engine_with_its_window_and_nothing_else():
    state = _state(mlx=_Module(), llama_cpp=_Module())
    request = MagicMock()
    request.app.state = state
    body = SimpleNamespace(engine="auto")
    forwarder = AsyncMock(return_value={"choices": []})
    fit = MagicMock(return_value=["FITTED"])
    with patch("core.endpoints.chat._dispatch_to_engine", forwarder), \
            patch("core.endpoints.chat._fit_v1_messages_to_window", fit), \
            patch("core.endpoints.chat.get_effective_context_window", lambda n, s: {"llama_cpp": 777}[n]):
        got = await ask_again(body, request, ["PROMPT"], "hi", "s1", "llama_cpp")
    assert got == {"choices": []}
    fit.assert_called_once_with(["PROMPT"], 777, body)
    forwarder.assert_awaited_once_with("llama_cpp", ["FITTED"], body, request, state, "hi", "s1")


async def test_a_failing_second_call_is_the_callers_to_take_and_no_other_engine_is_asked():
    state = _state(mlx=_Module(), llama_cpp=_Module())
    request = MagicMock()
    request.app.state = state
    asked = []

    async def forward(name, *a, **k):
        asked.append(name)
        raise RuntimeError("worker died")

    with patch("core.endpoints.chat._dispatch_to_engine", forward), \
            patch("core.endpoints.chat._fit_v1_messages_to_window", lambda m, w, b: m), \
            patch("core.endpoints.chat.get_effective_context_window", lambda n, s: 4096):
        with pytest.raises(RuntimeError, match="worker died"):
            await ask_again(SimpleNamespace(engine="auto"), request, [], "hi", "s", "mlx")
    assert asked == ["mlx"]


async def test_the_reprompt_call_asks_the_engine_of_the_turn_with_the_prompt_under_the_override():
    from core.turn.adapters_api import _v1_reprompt_call
    from core.turn.gate import EngineGate

    from .test_c48_d_engine_hold import _v1_ctx

    ctx = _v1_ctx(EngineGate(slots=1), stream=False)
    ctx.engine = "llama_cpp"
    ctx.prompt = [{"role": "system", "content": "sys"}, {"role": "user", "content": "hi"}]
    ctx.message = "hi"
    asked = AsyncMock(return_value={"choices": [{"message": {"content": "ok"}}]})
    with patch("core.turn.api_cascade.ask_again", asked):
        chunks = [c async for c in _v1_reprompt_call(ctx)("OVERRIDE")]
    assert chunks == ["ok"]
    args = asked.await_args.args
    assert args[0] is ctx.body and args[1] is ctx.request and args[5] == "llama_cpp"
    assert args[2] == [{"role": "system", "content": "OVERRIDE"}, {"role": "user", "content": "hi"}]
    assert args[3:5] == ("hi", ctx.session_id)
    assert ctx.prompt[0]["content"] == "sys"   # the turn's own prompt is left as it was


# ── D1-z: a model that is not on an engine in reserve ────────────────────────

@pytest.mark.parametrize("index, status, passed_over", [
    (1, 404, True),     # in reserve, no such model: try the next engine
    (0, 404, False),    # the engine asked for: the client named a model that is not there
    (1, 503, False),    # Ollama down is still the answer
    (1, 400, False),
    (2, 404, True),
])
async def test_a_404_from_an_engine_in_reserve_is_a_reason_to_try_the_next(index, status, passed_over):
    from core.endpoints.chat_engines.routing import should_try_next_engine as policy
    from core.turn.api_cascade import ModelNotOnFallback

    door = _door()
    boom = HTTPException(status_code=status, detail="model 'x' not found")
    with patch("core.endpoints.chat._dispatch_to_engine", AsyncMock(side_effect=boom)):
        with pytest.raises(Exception) as caught:
            await door.read_first(index, "ollama", object(), [])
    if passed_over:
        assert isinstance(caught.value, ModelNotOnFallback) and policy(caught.value) is True
        assert caught.value.__cause__ is boom and "ollama" in str(caught.value)
    else:
        assert caught.value is boom and policy(caught.value) is False


async def test_a_fallback_without_the_model_is_passed_over_and_the_next_engine_answers():
    state = _state(mlx=_Module(), ollama=_Module(), llama_cpp=_Module())
    reply = {"model": "gguf"}
    got = await _dispatch(state, {
        "mlx": RuntimeError("bad"), "llama_cpp": HTTPException(status_code=404, detail="no such model"),
        "ollama": reply,
    })
    assert got[0] is reply and got[1] == "ollama"
    assert got[3] == "execution_failed"


async def test_the_engine_asked_for_answering_404_ends_the_turn():
    state = _state(mlx=_Module(), ollama=_Module())
    with pytest.raises(HTTPException) as caught:
        await _dispatch(state, {"mlx": HTTPException(status_code=404, detail="no such model"), "ollama": {"model": "m"}})
    assert caught.value.status_code == 404


# ── what the review of this part found ───────────────────────────────────────

async def test_every_attempt_of_a_cascade_is_counted_under_its_engine_in_order():
    state = _state(mlx=_Module(), llama_cpp=_Module())
    request = MagicMock()
    request.app.state = state
    counted = []

    async def forward(name, *a, **k):
        if name == "mlx":
            raise RuntimeError("died")
        return {"model": "m"}

    with patch("core.endpoints.chat._dispatch_to_engine", forward), \
            patch("core.endpoints.chat._fit_v1_messages_to_window", lambda m, w, b: m), \
            patch("core.endpoints.chat.get_effective_context_window", lambda n, s: 4096), \
            patch("core.endpoints.chat._record_engine_metrics", lambda *a: counted.append(a[:2])):
        await dispatch_v1(SimpleNamespace(engine="auto", resume=False, model=None), request, [], "hi", "s", "mlx", None)
    assert counted == [("mlx", "error"), ("llama_cpp", "success")]


@pytest.mark.parametrize("fails, status", [(False, "success"), (True, "error")])
async def test_the_second_call_is_counted_like_the_first_was(fails, status):
    request = MagicMock()
    request.app.state = _state(llama_cpp=_Module())
    counted = []

    async def forward(name, *a, **k):
        if fails:
            raise RuntimeError("died")
        return {"model": "m"}

    with patch("core.endpoints.chat._dispatch_to_engine", forward), \
            patch("core.endpoints.chat._fit_v1_messages_to_window", lambda m, w, b: m), \
            patch("core.endpoints.chat.get_effective_context_window", lambda n, s: 4096), \
            patch("core.endpoints.chat._record_engine_metrics", lambda *a: counted.append((a[0], a[1], a[2] > 0))):
        if fails:
            with pytest.raises(RuntimeError, match="died"):
                await ask_again(SimpleNamespace(engine="auto"), request, [], "hi", "s", "llama_cpp")
        else:
            await ask_again(SimpleNamespace(engine="auto"), request, [], "hi", "s", "llama_cpp")
    assert counted == [("llama_cpp", status, True)]
