"""
────────────────────────────────────
Server Nexe
Author: Jordi Goy
Location: tests/core/endpoints/test_chat_engines_api.py
Description: API providers, phase 3 — the `/v1` forwarder of the API engine
    (`core/endpoints/chat_engines/api.py`), piece by piece. The doors' column
    (`tests/core/turn/test_c48_p0_api.py`) shows what a client meets; this
    pins what the forwarder itself does with what the engine hands it: the
    SSE it writes, the sentinel that ends it, the byte cap, what an error
    before and after the first token turns into, that the provider's stream is
    closed on EVERY way out, and that the engine is called with exactly the
    request's fields.

www.jgoy.net · https://server-nexe.org
────────────────────────────────────
"""
from __future__ import annotations

import asyncio
import json
import logging
from types import SimpleNamespace
from typing import Any, List

import pytest
from fastapi import HTTPException
from fastapi.responses import StreamingResponse

import core.endpoints.chat  # noqa: F401  (breaks a circular import when this file runs alone)
from core import runtime_state
from core.endpoints.chat_engines import api
from core.endpoints.chat_engines._common import served_model_of
from core.endpoints.chat_engines._streaming import NEXE_END
from core.endpoints.chat_schemas import ChatCompletionRequest, Message
from core.providers.cloud import ALLOW_CLOUD_ENV
from plugins.api_module.errors import ApiAuthError, ApiProviderError

FAKE_KEY = "FAKE-KEY-for-tests-7f3a9c1e-not-a-secret"
MODEL = "deepseek-chat"


def chunk(content: str = "", thinking: str = "", *, done: bool = False, reason: str | None = None) -> dict:
    out: dict = {"message": {"role": "assistant", "content": content, "thinking": thinking}, "done": done}
    if done:
        out["done_reason"] = reason or "stop"
    return out


class Source:
    """What `engine.chat` returns: an async generator of the engine's chunks that notes how it was left."""

    def __init__(self, items: List[Any], then: BaseException | None = None) -> None:
        self.items, self.then = list(items), then
        self.read = 0
        self.closed = False   # the generator was left (it ended, failed or was closed)
        self.aclosed = False  # and it was CLOSED by whoever read it, explicitly
        self._gen = self._run()

    async def _run(self):
        try:
            for item in self.items:
                self.read += 1
                yield item
            if self.then is not None:
                raise self.then
        finally:
            self.closed = True

    def __aiter__(self):
        return self._gen.__aiter__()

    async def aclose(self):
        self.aclosed = True
        await self._gen.aclose()
        self.closed = True


async def run(source, model: str = MODEL) -> list:
    return [out async for out in api._api_stream_generator(source, model)]


def end_of(outputs: list) -> dict:
    last = outputs[-1]
    assert isinstance(last, dict) and set(last) == {NEXE_END}, outputs
    return last[NEXE_END]


def text_of(sse: str) -> dict:
    assert sse.startswith("data: ") and sse.endswith("\n\n")
    return json.loads(sse[6:])


# ============================================================ the stream, token by token

async def test_each_token_is_one_sse_chunk_and_one_sentinel_ends_it():
    source = Source([chunk("Ho"), chunk("la"), chunk(done=True)])
    out = await run(source)
    assert source.aclosed is True, "the provider's stream is closed explicitly, not left to the garbage collector"
    assert [text_of(s)["choices"][0]["delta"]["content"] for s in out[:-1]] == ["Ho", "la"]
    assert all(text_of(s)["model"] == MODEL and text_of(s)["id"].startswith("api-stream-") for s in out[:-1])
    assert end_of(out) == {"finish_reason": None, "truncated": False, "failure": None, "usage": None}


async def test_the_models_reasoning_travels_as_reasoning_in_its_own_chunk():
    out = await run(Source([chunk(thinking="pensant"), chunk("R"), chunk(done=True)]))
    first, second = text_of(out[0])["choices"][0]["delta"], text_of(out[1])["choices"][0]["delta"]
    assert first["reasoning"] == "pensant" and second["content"] == "R" and "reasoning" not in second


async def test_a_chunk_with_nothing_in_it_writes_nothing_but_the_stream_still_ends():
    out = await run(Source([chunk(), chunk(done=True)]))
    assert len(out) == 1 and end_of(out)["failure"] is None


async def test_the_ceiling_cut_is_reported_as_length_even_when_a_later_chunk_does_not_repeat_it():
    for items in ([chunk("a", done=True, reason="length")],
                  [chunk("a", done=True, reason="length"), chunk("b")]):
        out = await run(Source(items))
        assert end_of(out)["finish_reason"] == "length"
    assert end_of(await run(Source([chunk("a", done=True, reason="stop")])))["finish_reason"] is None
    assert end_of(await run(Source([chunk("a", done=True, reason="content_filter")])))["finish_reason"] is None


def test_the_ceiling_cut_is_read_from_the_chunk_and_nothing_else():
    assert api._chunk_end({"done_reason": "length"}) == "length"
    for other in ({"done_reason": "stop"}, {"done_reason": None}, {}, "length", None, 3, ["length"]):
        assert api._chunk_end(other) is None


# ============================================================================ the byte cap

@pytest.fixture
def cap(monkeypatch):
    monkeypatch.setattr(api, "MAX_STREAM_BYTES", 10)


async def test_a_stream_exactly_at_the_cap_is_complete(cap):
    out = await run(Source([chunk("12345"), chunk("67890"), chunk(done=True)]))
    assert len(out) == 3 and end_of(out) == {"finish_reason": None, "truncated": False, "failure": None, "usage": None}


async def test_one_byte_past_the_cap_ends_the_stream_with_a_failure_and_reads_no_further(cap):
    source = Source([chunk("12345"), chunk("678901"), chunk("never"), chunk(done=True)])
    out = await run(source)
    assert [text_of(s)["choices"][0]["delta"]["content"] for s in out[:-1]] == ["12345"], "the chunk past the cap is not sent"
    assert end_of(out) == {"finish_reason": None, "truncated": True, "failure": "stream_cap_exceeded", "usage": None}
    assert source.read == 2 and source.closed is True, "nothing was read after the cap, and the provider was let go"


async def test_the_cap_counts_the_reasoning_and_bytes_not_characters(cap):
    out = await run(Source([chunk("12345", thinking="678901")]))
    assert end_of(out)["failure"] == "stream_cap_exceeded" and len(out) == 1
    out = await run(Source([chunk("éééé")]))  # 4 characters, 8 bytes
    assert end_of(out)["failure"] is None and len(out) == 2
    out = await run(Source([chunk("éééééé")]))  # 12 bytes
    assert end_of(out)["failure"] == "stream_cap_exceeded"


# ================================================================ failures, before and after

async def test_an_error_before_the_first_token_is_raised_as_it_is_so_the_cascade_can_answer_with_http():
    for error in (ApiAuthError("DeepSeek", 401), ApiProviderError("DeepSeek", 429), TimeoutError("slow"), ConnectionError("down"),
                  ValueError("bad")):
        source = Source([], then=error)
        with pytest.raises(type(error)):
            await run(source)
        assert source.closed is True


async def test_an_empty_chunk_before_the_error_is_still_before_the_first_token():
    source = Source([chunk()], then=ApiProviderError("DeepSeek", 503))
    with pytest.raises(ApiProviderError):
        await run(source)


async def test_an_error_after_the_first_token_is_the_sentinel_not_a_raise_and_never_carries_its_text(caplog):
    caplog.set_level(logging.DEBUG)
    leaking = ApiProviderError("DeepSeek", 503)
    leaking.args = (f"boom {FAKE_KEY}",)
    source = Source([chunk("Hola")], then=leaking)
    out = await run(source)
    assert len(out) == 2 and "Hola" in out[0]
    assert end_of(out) == {"finish_reason": None, "truncated": False, "failure": "ApiProviderError", "usage": None}
    assert FAKE_KEY not in json.dumps(out) and FAKE_KEY not in caplog.text
    assert "ApiProviderError" in caplog.text, "the class is logged, so the failure can be told from silence"
    assert source.closed is True


async def test_a_consumer_that_goes_away_closes_the_providers_stream():
    source = Source([chunk("a"), chunk("b"), chunk("c")])
    generator = api._api_stream_generator(source, MODEL)
    await generator.__anext__()
    await generator.aclose()
    assert source.closed is True and source.read == 1


async def test_a_cancelled_read_leaves_cancelled_and_lets_the_provider_go():
    source = Source([chunk("a")], then=asyncio.CancelledError())
    out: list = []
    with pytest.raises(asyncio.CancelledError):
        async for sse in api._api_stream_generator(source, "m"):
            out.append(sse)
    assert len(out) == 1 and "a" in out[0], "no sentinel after a cancellation: the consumer is gone"
    assert source.closed is True


async def test_a_source_with_no_aclose_is_fine():
    class Plain:
        def __init__(self):
            self.items = [chunk("x"), chunk(done=True)]

        def __aiter__(self):
            return self

        async def __anext__(self):
            if not self.items:
                raise StopAsyncIteration
            return self.items.pop(0)

    out = await run(Plain())
    assert len(out) == 2 and end_of(out)["failure"] is None


# ============================================================================ a whole reply

async def test_a_whole_reply_is_the_engine_result_dict_with_the_ceiling_cut_kept():
    result = await api._whole_reply(Source([chunk("Ho", thinking="p"), chunk("la", thinking="q", done=True, reason="length"), chunk("")]))
    assert result == {"response": "Hola", "thinking": "pq", "finish_reason": "length"}
    assert await api._whole_reply(Source([chunk("a", done=True)])) == {"response": "a", "thinking": "", "finish_reason": None}
    assert await api._whole_reply(Source([])) == {"response": "", "thinking": "", "finish_reason": None}


# ===================================================================== the forwarder itself

@pytest.fixture
def cloud(monkeypatch):
    runtime_state.reset()
    monkeypatch.setenv(ALLOW_CLOUD_ENV, "1")
    monkeypatch.setenv("DEEPSEEK_API_KEY", FAKE_KEY)
    yield
    runtime_state.reset()


class RecordingEngine:
    """A hosted engine as the forwarder finds it: bound to the request's model by `for_model`."""

    runs_in_the_cloud = True

    def __init__(self, items=None, then=None):
        self.items, self.then = items if items is not None else [chunk("Hola"), chunk(done=True)], then
        self.calls: list = []
        self.bound: list = []
        self.sources: list = []

    def for_model(self, model):
        self.bound.append(model)
        return self

    def chat(self, **kwargs):
        self.calls.append(kwargs)
        source = Source(self.items, self.then)
        self.sources.append(source)
        return source


def _state(engine=None, **extra):
    modules = dict(extra)
    if engine is not None:
        modules["api_module"] = engine
    return SimpleNamespace(modules=modules, config={})


def _request(**fields) -> ChatCompletionRequest:
    fields.setdefault("messages", [Message(role="user", content="hola")])
    fields.setdefault("engine", "api")
    fields.setdefault("model", MODEL)
    fields.setdefault("nexe_cloud_consent", "deepseek")
    return ChatCompletionRequest(**fields)


def _req(state) -> Any:
    return SimpleNamespace(app=SimpleNamespace(state=state))


MESSAGES = [{"role": "system", "content": "S"}, {"role": "user", "content": "hola"}]


async def test_the_engine_is_called_with_exactly_what_the_request_says(cloud):
    engine = RecordingEngine()
    cancel = object()
    await api._forward_to_api(MESSAGES, _request(top_p=0.4, stream=True), _req(_state(engine)),
                              cancel_event=cancel, images=["B64"])
    assert engine.bound == [MODEL], "the engine is bound to the request's own model"
    assert engine.calls == [dict(model=MODEL, messages=MESSAGES, stream=True, images=["B64"], thinking_enabled=False,
                                 top_p=0.4, cancel_event=cancel)]


async def test_a_streamed_answer_is_a_streaming_response_the_way_the_other_forwarders_build_it(cloud):
    engine = RecordingEngine()
    response = await api._forward_to_api(MESSAGES, _request(stream=True), _req(_state(engine)))
    assert isinstance(response, StreamingResponse) and response.media_type == "text/event-stream"
    assert dict(response.headers)["cache-control"] == "no-cache"
    assert dict(response.headers)["connection"] == "keep-alive"
    assert dict(response.headers)["x-accel-buffering"] == "no"
    assert served_model_of(response) == MODEL
    assert engine.calls[0]["stream"] is True
    body = [part async for part in response.body_iterator]
    assert "Hola" in body[0] and end_of(body)["failure"] is None


async def test_a_whole_answer_is_an_openai_completion_of_the_requests_model(cloud):
    engine = RecordingEngine([chunk("Hola", thinking="pensant"), chunk(done=True, reason="length")])
    response = await api._forward_to_api(MESSAGES, _request(stream=False), _req(_state(engine)))
    assert engine.calls[0]["stream"] is False
    assert response["object"] == "chat.completion" and response["model"] == MODEL and response["id"].startswith("api-")
    choice = response["choices"][0]
    assert choice["message"] == {"role": "assistant", "content": "Hola", "reasoning": "pensant"}
    assert choice["finish_reason"] == "length"


@pytest.mark.parametrize("fields, thinking", [
    ({}, False), ({"reasoning_effort": "low"}, True), ({"reasoning_effort": "none"}, False),
    ({"reasoning": {"effort": "high"}}, True),
    ({"reasoning_effort": "low", "resume": True}, False),  # a resume never opens a new reasoning block
])
async def test_the_model_reasons_only_when_the_request_asks_and_never_on_a_resume(cloud, fields, thinking):
    engine = RecordingEngine()
    await api._forward_to_api(MESSAGES, _request(**fields), _req(_state(engine)))
    assert engine.calls[0]["thinking_enabled"] is thinking


async def test_a_double_that_answers_any_attribute_is_not_taken_for_a_resume(cloud):
    engine = RecordingEngine()
    request = _request(reasoning_effort="low")
    request.__dict__["resume"] = object()  # truthy but not exactly True
    await api._forward_to_api(MESSAGES, request, _req(_state(engine)))
    assert engine.calls[0]["thinking_enabled"] is True


@pytest.mark.parametrize("fields", [
    {"nexe_cloud_consent": None}, {"nexe_cloud_consent": "openai"}, {"model": "llama3.2:3b"}, {"model": None},
])
async def test_the_gate_is_asked_before_the_module_is_touched(cloud, fields):
    engine = RecordingEngine()
    with pytest.raises(HTTPException) as refused:
        await api._forward_to_api(MESSAGES, _request(**fields), _req(_state(engine)))
    assert refused.value.status_code in (400, 403) and engine.calls == [] and engine.bound == []


async def test_the_switch_off_refuses_before_anything(cloud, monkeypatch):
    monkeypatch.setenv(ALLOW_CLOUD_ENV, "0")
    engine = RecordingEngine()
    with pytest.raises(HTTPException) as refused:
        await api._forward_to_api(MESSAGES, _request(), _req(_state(engine)))
    assert refused.value.status_code == 403 and engine.calls == []


def test_a_refusal_says_why_by_code_and_never_by_key(cloud):
    with pytest.raises(HTTPException) as refused:
        api.cloud_gate(_request(nexe_cloud_consent=None))
    assert refused.value.status_code == 403 and refused.value.detail["code"] == "cloud_consent_required"
    assert refused.value.detail["provider"] == "deepseek"


@pytest.mark.parametrize("state", [_state(), _state(ollama_module=object()), _state(SimpleNamespace())])
def test_an_api_module_that_is_not_there_or_cannot_chat_is_a_503_that_says_so(cloud, state):
    with pytest.raises(HTTPException) as refused:
        api._live_engine(_request(), _req(state))
    assert refused.value.status_code == 503 and refused.value.detail == "The API engine is not loaded on this server"


def test_the_live_engine_is_the_module_bound_to_the_requests_model(cloud):
    engine = RecordingEngine()
    assert api._live_engine(_request(model="gpt-4o"), _req(_state(engine))) is engine
    assert engine.bound == ["gpt-4o"]


async def test_a_whole_reply_lets_the_providers_stream_go_on_every_way_out():
    done = Source([chunk("a", done=True)])
    assert (await api._whole_reply(done))["response"] == "a" and done.aclosed is True
    failing = Source([chunk("a")], then=ApiProviderError("DeepSeek", 503))
    with pytest.raises(ApiProviderError):
        await api._whole_reply(failing)
    assert failing.aclosed is True

    class Plain:  # nothing to close: still fine
        def __aiter__(self):
            return self

        async def __anext__(self):
            raise StopAsyncIteration

    assert (await api._whole_reply(Plain()))["response"] == ""


async def test_a_request_with_no_resume_field_is_not_a_resume(cloud):
    """The schema always has it; the forwarder does not assume an answer to be cut when it is not told."""
    engine = RecordingEngine()
    request = SimpleNamespace(model=MODEL, nexe_cloud_consent="deepseek", stream=False, top_p=None,
                              wants_reasoning=lambda: True)
    await api._forward_to_api(MESSAGES, request, _req(_state(engine)))
    assert engine.calls[0]["thinking_enabled"] is True


async def test_a_whole_reply_lets_the_stream_go_when_reading_it_fails_part_way_and_when_the_reader_is_cancelled(monkeypatch):
    """Exits where the generator does not run to its end by itself: the reader fails on a chunk, or is cancelled."""
    source = Source([chunk("a"), chunk("b"), chunk("c")])
    reads = {"n": 0}
    real = api.parse_chunk

    def failing(value):
        reads["n"] += 1
        if reads["n"] == 2:
            raise RuntimeError("cannot read this chunk")
        return real(value)

    monkeypatch.setattr(api, "parse_chunk", failing)
    with pytest.raises(RuntimeError):
        await api._whole_reply(source)
    assert source.aclosed is True and source.read == 2
    monkeypatch.setattr(api, "parse_chunk", real)

    class Stuck:
        aclosed = False

        def __aiter__(self):
            return self

        async def __anext__(self):
            await asyncio.sleep(3600)

        async def aclose(self):
            Stuck.aclosed = True

    task = asyncio.ensure_future(api._whole_reply(Stuck()))
    await asyncio.sleep(0.05)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert Stuck.aclosed is True


async def test_a_stream_that_fails_to_close_does_not_replace_the_answer_or_the_error_on_their_way_out():
    class BadClose(Source):
        async def aclose(self):
            raise RuntimeError("the connection was already gone")

    out = await run(BadClose([chunk("a"), chunk(done=True)]))
    assert end_of(out)["failure"] is None and "a" in out[0], "the answer is still the answer"
    with pytest.raises(ApiProviderError):
        await run(BadClose([], then=ApiProviderError("DeepSeek", 503)))  # and the provider's error is still the error
