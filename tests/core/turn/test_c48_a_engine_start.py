"""C4.8-a: the one engine start, tested on its own (`core/turn/engine_start.py`).

The function moved verbatim out of the web door; before the move it was only
exercised through whole turns, so a mutant that dropped `session_id`, the
sampling kwargs or the truncation sentinel survived the whole suite. These
tests drive it directly with recording engines of each shape and pin what
each shape is asked, line by line.
"""
from __future__ import annotations

import asyncio
import threading

import pytest

from core.turn.engine_start import start_engine_call

SAMPLING = {"top_p": 0.5}
MSGS = [{"role": "user", "content": "hi"}]


def _start(engine, name, *, model="m", stream=True, image="IMG", thinking=True,
           cancel=None, sampling=SAMPLING, sid="S1", resume=False, system="SYS"):
    import inspect
    return start_engine_call(
        engine, name, inspect.signature(engine.chat), model, system, list(MSGS),
        stream=stream, image_b64=image, thinking_enabled=thinking,
        cancel_event=cancel, sampling_kwargs=dict(sampling), session_id=sid, _continue=resume,
    )


class _OllamaShaped:
    """`chat(model, messages, …)`: the Ollama shape. Records what it got."""

    def __init__(self, with_continue=True):
        self.got = None
        if not with_continue:
            self.chat = self._chat_no_continue

    def chat(self, model, messages, stream=False, images=None, thinking_enabled=False,
             continue_final=False, cancel_event=None, top_p=None):
        self.got = dict(model=model, messages=messages, stream=stream, images=images,
                        thinking_enabled=thinking_enabled, continue_final=continue_final,
                        cancel_event=cancel_event, top_p=top_p)
        return "RESULT-OLLAMA"

    def _chat_no_continue(self, model, messages, stream=False, images=None,
                          thinking_enabled=False, cancel_event=None, top_p=None):
        self.got = dict(model=model, messages=messages, stream=stream, images=images,
                        thinking_enabled=thinking_enabled, cancel_event=cancel_event, top_p=top_p)
        return "RESULT-OLLAMA"


def test_ollama_shape_gets_the_system_prompt_first_and_every_argument():
    eng = _OllamaShaped()
    out = _start(eng, "ollama", model="qwen", stream=False, image="B64", thinking=True)
    assert out == "RESULT-OLLAMA"
    assert eng.got == dict(
        model="qwen", messages=[{"role": "system", "content": "SYS"}] + MSGS, stream=False,
        images=["B64"], thinking_enabled=True, continue_final=False, cancel_event=None, top_p=0.5,
    )


def test_ollama_shape_stream_flag_and_no_image():
    eng = _OllamaShaped()
    _start(eng, "ollama", stream=True, image=None, thinking=False)
    assert eng.got["stream"] is True and eng.got["images"] is None
    assert eng.got["thinking_enabled"] is False


def test_ollama_shape_resume_asks_to_continue_only_when_declared():
    eng = _OllamaShaped()
    _start(eng, "ollama", resume=True)
    assert eng.got["continue_final"] is True
    eng = _OllamaShaped()
    _start(eng, "ollama", resume=False)
    assert eng.got["continue_final"] is False
    # An engine that does not declare `continue_final` is never handed the flag
    # (it would ignore it and start a new answer).
    eng = _OllamaShaped(with_continue=False)
    _start(eng, "ollama", resume=True)
    assert "continue_final" not in eng.got


def test_ollama_shape_cancel_event_only_for_in_process_names():
    ev = threading.Event()
    eng = _OllamaShaped()
    _start(eng, "ollama", cancel=ev)
    assert eng.got["cancel_event"] is None
    eng = _OllamaShaped()
    _start(eng, "mlx", cancel=ev)
    assert eng.got["cancel_event"] is ev
    eng = _OllamaShaped()
    _start(eng, "llama_cpp", cancel=ev)
    assert eng.got["cancel_event"] is ev


def test_ollama_shape_without_sampling_kwargs_passes_none():
    eng = _OllamaShaped()
    _start(eng, "ollama", sampling={})
    assert eng.got["top_p"] is None


class _Queued:
    """The in-process shape: `chat(messages, system, stream_callback, …)`; calls
    the callback for each token, then returns `result`."""

    def __init__(self, tokens=("a", "b", "c"), result=None, exc=None, delay=0.0):
        self.tokens, self.result, self.exc, self.delay = tokens, result, exc, delay
        self.got = None

    async def chat(self, messages, system=None, stream_callback=None, session_id=None,
                   images=None, thinking_enabled=False, continue_final=False,
                   cancel_event=None, top_p=None):
        self.got = dict(messages=messages, system=system, session_id=session_id, images=images,
                        thinking_enabled=thinking_enabled, continue_final=continue_final,
                        cancel_event=cancel_event, top_p=top_p)
        for t in self.tokens:
            stream_callback(t)
            if self.delay:
                await asyncio.sleep(self.delay)
        if self.exc is not None:
            raise self.exc
        return self.result


async def _drain(gen):
    return [x async for x in gen]


@pytest.mark.parametrize("name", ["mlx", "llama_cpp"])
async def test_in_process_shape_is_asked_with_every_argument(name):
    ev = threading.Event()
    eng = _Queued(result={"finish_reason": "stop"})
    out = await _drain(_start(eng, name, image="B64", thinking=True, cancel=ev, sid="S9"))
    assert out == ["a", "b", "c"]
    assert eng.got == dict(messages=MSGS, system="SYS", session_id="S9", images=["B64"],
                           thinking_enabled=True, continue_final=False, cancel_event=ev, top_p=0.5)


async def test_in_process_shape_no_image_no_thinking_no_sampling():
    eng = _Queued(result=None)
    await _drain(_start(eng, "mlx", image=None, thinking=False, sampling={}))
    assert eng.got["images"] is None and eng.got["thinking_enabled"] is False
    assert eng.got["top_p"] is None


async def test_in_process_shape_resume_sets_continue_final():
    eng = _Queued(result=None)
    await _drain(_start(eng, "mlx", resume=True))
    assert eng.got["continue_final"] is True
    eng = _Queued(result=None)
    await _drain(_start(eng, "mlx", resume=False))
    assert eng.got["continue_final"] is False


@pytest.mark.parametrize("continuable", [True, False])
async def test_in_process_shape_surfaces_a_length_stop_as_a_sentinel(continuable):
    eng = _Queued(result={"finish_reason": "length", "continuable": continuable})
    out = await _drain(_start(eng, "mlx"))
    assert out == ["a", "b", "c", {"__nexe_trunc__": True, "continuable": continuable}]


@pytest.mark.parametrize("result", [{"finish_reason": "stop", "continuable": True}, None, "text"])
async def test_in_process_shape_adds_no_sentinel_otherwise(result):
    eng = _Queued(result=result)
    assert await _drain(_start(eng, "llama_cpp")) == ["a", "b", "c"]


async def test_in_process_shape_re_raises_the_workers_exception_after_the_tokens():
    eng = _Queued(exc=RuntimeError("boom"))
    gen = _start(eng, "mlx")
    got = []
    with pytest.raises(RuntimeError, match="boom"):
        async for x in gen:
            got.append(x)
    assert got == ["a", "b", "c"]


async def test_in_process_shape_waits_for_a_slow_worker_then_ends():
    eng = _Queued(tokens=("x", "y"), result=None, delay=0.12)
    assert await _drain(_start(eng, "mlx")) == ["x", "y"]


async def test_in_process_shape_each_start_owns_its_queue():
    """B023: two starts in a row never read each other's tokens."""
    e1, e2 = _Queued(tokens=("1",), result=None), _Queued(tokens=("2",), result=None)
    g1, g2 = _start(e1, "mlx"), _start(e2, "mlx")
    assert await _drain(g2) == ["2"]
    assert await _drain(g1) == ["1"]


class _Generic:
    def __init__(self, with_sid=True):
        self.got = None
        if not with_sid:
            self.chat = self._chat_no_sid

    def chat(self, messages, system=None, images=None, thinking_enabled=False,
             session_id=None, cancel_event=None, top_p=None):
        self.got = dict(messages=messages, system=system, images=images,
                        thinking_enabled=thinking_enabled, session_id=session_id,
                        cancel_event=cancel_event, top_p=top_p)
        return "RESULT-GENERIC"

    def _chat_no_sid(self, messages, system=None, images=None, thinking_enabled=False,
                     cancel_event=None, top_p=None):
        self.got = dict(messages=messages, system=system, images=images,
                        thinking_enabled=thinking_enabled, cancel_event=cancel_event, top_p=top_p)
        return "RESULT-GENERIC"


def test_generic_shape_gets_the_system_prompt_apart_and_the_session():
    ev = threading.Event()
    eng = _Generic()
    assert _start(eng, "other", image="B64", thinking=True, cancel=ev, sid="S3") == "RESULT-GENERIC"
    assert eng.got == dict(messages=MSGS, system="SYS", images=["B64"], thinking_enabled=True,
                           session_id="S3", cancel_event=None, top_p=0.5)


def test_generic_shape_without_session_id_param_is_not_given_one():
    eng = _Generic(with_sid=False)
    _start(eng, "other", image=None, thinking=False, sampling={})
    assert "session_id" not in eng.got
    assert eng.got["images"] is None and eng.got["thinking_enabled"] is False
    assert eng.got["top_p"] is None


def test_generic_shape_never_gets_the_resume_flag():
    """The generic call has no `continue_final`: a resume is dropped, not passed
    (a signature without it would raise TypeError), and the answer starts anew.
    The `engine` step is what keeps a Continue away from such an engine."""
    eng = _Generic()
    assert _start(eng, "other", resume=True) == "RESULT-GENERIC"
    assert "continue_final" not in eng.got


def test_the_shape_follows_the_signature_not_the_name():
    """An engine named `ollama` whose `chat` has no `model` parameter is called
    the generic way: system prompt apart, no cancel_event (only the in-process
    names get one)."""
    ev = threading.Event()
    eng = _Generic()
    _start(eng, "ollama", cancel=ev)
    assert eng.got["system"] == "SYS" and eng.got["cancel_event"] is None
