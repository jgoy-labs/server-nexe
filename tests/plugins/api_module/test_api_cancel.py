"""
────────────────────────────────────
Server Nexe
Author: Jordi Goy
Location: tests/plugins/api_module/test_api_cancel.py
Description: API providers, phase 3 — a turn's cancel event really stops the
    HTTP exchange. A client that leaves is cancelled by asyncio (the task is
    cancelled and httpx closes); a DEADLINE only SETS the event
    (`core/turn/cancel.py`, `engine_hold.py`), so a read nobody tells to stop
    would run to its own timeout, with a paid answer still being generated at
    the other end. Here the fake provider streams slowly (or never answers) and
    the event is set: the read ends within a poll, the connection is closed and
    no more is yielded.

www.jgoy.net · https://server-nexe.org
────────────────────────────────────
"""
from __future__ import annotations

import asyncio
import inspect
import json
import threading
import time

import httpx
import pytest

import core.endpoints.chat  # noqa: F401  (breaks a circular import when this file runs alone)
from plugins.api_module import chat as chat_module
from plugins.api_module.module import ApiModule

FAKE_KEY = "FAKE-KEY-for-tests-7f3a9c1e-not-a-secret"


@pytest.fixture(autouse=True)
def _env(monkeypatch):
    monkeypatch.setenv("NEXE_ALLOW_CLOUD_ENGINES", "1")  # the module re-reads the switch at every request
    monkeypatch.setenv("DEEPSEEK_API_KEY", FAKE_KEY)
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.setattr(chat_module, "CANCEL_POLL_SECONDS", 0.01)


def _event(text: str) -> bytes:
    return ("data: " + json.dumps({"choices": [{"delta": {"content": text}, "finish_reason": None}]}) + "\n\n").encode()


class Endless(httpx.AsyncByteStream):
    """A provider that keeps generating, one token every 20 ms, and notes when its connection is closed."""

    def __init__(self) -> None:
        self.closed = False
        self.sent = 0

    async def __aiter__(self):
        while True:
            await asyncio.sleep(0.02)
            self.sent += 1
            yield _event(f"t{self.sent} ")

    async def aclose(self) -> None:
        self.closed = True


def _module_with(handler) -> ApiModule:
    return ApiModule(transport=httpx.MockTransport(handler))


def _endless_module():
    body = Endless()
    requests: list = []

    def handler(request):
        requests.append(request)
        return httpx.Response(200, stream=body)

    return _module_with(handler), body, requests


async def _read(gen, limit: float = 2.0) -> list:
    async with asyncio.timeout(limit):
        return [chunk async for chunk in gen]


async def test_setting_the_event_mid_stream_ends_the_read_and_closes_the_connection():
    module, body, _requests = _endless_module()
    cancel = threading.Event()
    got: list = []
    started = time.monotonic()
    async with asyncio.timeout(2.0):
        async for chunk in module.chat(model="deepseek-chat", messages=[{"role": "user", "content": "hola"}],
                                       cancel_event=cancel):
            got.append(chunk)
            if len(got) == 3:
                cancel.set()
    assert 3 <= len(got) <= 5, "what was already read stands; at most a token or two more were in flight"
    assert time.monotonic() - started < 1.0
    assert body.closed is True, "the connection to the provider was closed, not left to its own timeout"
    sent_when_stopped = body.sent
    await asyncio.sleep(0.1)
    assert body.sent == sent_when_stopped, "and the provider is no longer being read"


async def test_the_event_stops_a_request_the_provider_has_not_even_started_to_answer():
    """The event comes while the engine waits for the first byte (a slow first token): the wait is cancelled."""
    asked = asyncio.Event()

    async def never_answers(request):
        asked.set()
        await asyncio.sleep(3600)
        return httpx.Response(200)

    module = _module_with(never_answers)
    cancel = threading.Event()

    async def trip():
        await asked.wait()
        cancel.set()

    tripper = asyncio.ensure_future(trip())
    got = await _read(module.chat(model="deepseek-chat", messages=[{"role": "user", "content": "hola"}], cancel_event=cancel))
    await tripper
    assert got == [], "nothing was answered, and it is not an error"


async def test_an_event_set_from_another_thread_is_seen():
    module, body, _requests = _endless_module()
    cancel = threading.Event()
    threading.Timer(0.1, cancel.set).start()
    started = time.monotonic()
    got = await _read(module.chat(model="deepseek-chat", messages=[{"role": "user", "content": "x"}], cancel_event=cancel))
    assert time.monotonic() - started < 1.0 and body.closed and len(got) >= 1


async def test_an_event_that_is_already_set_sends_no_request_at_all():
    module, body, requests = _endless_module()
    cancel = threading.Event()
    cancel.set()
    assert await _read(module.chat(model="deepseek-chat", messages=[{"role": "user", "content": "x"}], cancel_event=cancel)) == []
    assert requests == [] and body.sent == 0, "a turn that was cancelled before it began spends nothing"


async def test_a_whole_reply_request_is_cancelled_too():
    asked = asyncio.Event()

    async def slow(request):
        asked.set()
        await asyncio.sleep(3600)

    module = _module_with(slow)
    cancel = threading.Event()
    tripper = asyncio.ensure_future(_set_after(asked, cancel))
    got = await _read(module.chat(model="deepseek-chat", messages=[{"role": "user", "content": "x"}], stream=False,
                                  cancel_event=cancel))
    await tripper
    assert got == []


async def _set_after(asked: asyncio.Event, cancel: threading.Event) -> None:
    await asked.wait()
    cancel.set()


async def test_without_an_event_nothing_changes_the_whole_stream_is_read():
    def handler(request):
        events = b"".join(_event(t) for t in ("a", "b", "c")) + b"data: [DONE]\n\n"
        return httpx.Response(200, content=events)

    for cancel in (None, threading.Event()):  # an event that is never set is the same as none
        got = await _read(_module_with(handler).chat(model="deepseek-chat", messages=[{"role": "user", "content": "x"}],
                                                     cancel_event=cancel))
        assert [c["message"]["content"] for c in got] == ["a", "b", "c"]


async def test_an_error_of_the_provider_still_surfaces_with_an_event_attached():
    from plugins.api_module.errors import ApiAuthError, ApiProviderError

    for status, expected in ((401, ApiAuthError), (429, ApiProviderError), (503, ApiProviderError)):
        module = _module_with(lambda request, s=status: httpx.Response(s, json={"error": FAKE_KEY}))
        with pytest.raises(expected):
            await _read(module.chat(model="deepseek-chat", messages=[{"role": "user", "content": "x"}],
                                    cancel_event=threading.Event()))
    module = _module_with(lambda request: (_ for _ in ()).throw(httpx.ReadTimeout("slow", request=request)))
    with pytest.raises(TimeoutError):
        await _read(module.chat(model="deepseek-chat", messages=[{"role": "user", "content": "x"}], cancel_event=threading.Event()))


async def test_a_consumer_that_walks_away_closes_the_provider_too():
    module, body, _requests = _endless_module()
    gen = module.chat(model="deepseek-chat", messages=[{"role": "user", "content": "x"}], cancel_event=threading.Event())
    await gen.__anext__()
    await gen.aclose()
    assert body.closed is True


async def test_the_metric_says_cancelled_for_a_cancelled_read_and_ok_for_a_whole_one():
    from core.metrics.registry import API_ENGINE_REQUESTS

    def value(status):
        return API_ENGINE_REQUESTS.labels(provider="deepseek", status=status)._value.get()

    cancelled0, ok0 = value("cancelled"), value("ok")
    module, _body, _requests = _endless_module()
    cancel = threading.Event()
    async for _ in module.chat(model="deepseek-chat", messages=[{"role": "user", "content": "x"}], cancel_event=cancel):
        cancel.set()
    assert value("cancelled") == cancelled0 + 1 and value("ok") == ok0
    done = _module_with(lambda r: httpx.Response(200, content=_event("a") + b"data: [DONE]\n\n"))
    await _read(done.chat(model="deepseek-chat", messages=[{"role": "user", "content": "x"}], cancel_event=threading.Event()))
    assert value("ok") == ok0 + 1 and value("cancelled") == cancelled0 + 1


async def test_the_engine_the_turn_starts_is_handed_the_event_and_stops_with_it():
    """`start_engine_call` for the API engine (hosted: `cancel_event` goes by the table, not by the signature)."""
    from core.turn.engine_start import start_engine_call

    module, body, _requests = _endless_module()
    view = module.for_model("deepseek-chat")
    cancel = threading.Event()
    result = start_engine_call(
        view, "api", inspect.signature(view.chat), "deepseek-chat", "SYS", [{"role": "user", "content": "x"}],
        stream=True, image_b64=None, thinking_enabled=False, cancel_event=cancel, sampling_kwargs={},
        session_id="s", _continue=False,
    )
    got = []
    async with asyncio.timeout(2.0):
        async for chunk in result:
            got.append(chunk)
            cancel.set()
    assert len(got) >= 1 and body.closed is True


def test_the_event_is_optional():
    assert inspect.signature(ApiModule.chat).parameters["cancel_event"].default is None


async def test_a_read_that_the_provider_never_ends_is_cancelled_not_waited_for():
    """The in-flight read must be CANCELLED: waiting for it would hold the turn for as long as the provider
    chooses (here, an hour), and a cancellation of the consumer's own task must not be swallowed on the way."""
    asked = asyncio.Event()
    finished = asyncio.Event()

    async def never(request):
        asked.set()
        try:
            await asyncio.sleep(3600)
        finally:
            finished.set()
        return httpx.Response(200)

    module = _module_with(never)
    cancel = threading.Event()
    gen = module.chat(model="deepseek-chat", messages=[{"role": "user", "content": "x"}], cancel_event=cancel)
    task = asyncio.ensure_future(_read(gen, limit=1.5))
    await asked.wait()
    cancel.set()
    assert await task == []
    assert finished.is_set(), "the provider's wait was torn down, not left running"


async def test_the_consumer_being_cancelled_while_a_read_is_in_flight_is_not_swallowed():
    asked = asyncio.Event()

    async def never(request):
        asked.set()
        await asyncio.sleep(3600)

    module = _module_with(never)
    task = asyncio.ensure_future(_read(module.chat(model="deepseek-chat", messages=[{"role": "user", "content": "x"}],
                                                   cancel_event=threading.Event()), limit=5.0))
    await asked.wait()
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await asyncio.wait_for(task, timeout=2.0)
