"""A client that leaves cancels the task that is reading Ollama's stream.

Starlette cancels the response task when the client disconnects, which raises
`CancelledError` at the generator's `await`. The generator caught it and
returned, so the turn saw a clean end: the call was recorded `ok`, the
turn went on to persist a partial answer, and in the field the trace of a
cut turn arrived 103 s late. A cancellation has to leave the generator.
"""
import asyncio
import json

import pytest

from core.endpoints.chat_engines import ollama as ollama_engine


class _Resp:
    status_code = 200

    async def aiter_lines(self):
        yield json.dumps({"message": {"content": "hola"}, "done": False})
        await asyncio.sleep(3600)  # the daemon is still generating


class _Stream:
    async def __aenter__(self):
        return _Resp()

    async def __aexit__(self, *_exc):
        return False


class _Client:
    def __init__(self, *_a, **_k):
        pass

    async def __aenter__(self):
        return self

    async def __aexit__(self, *_exc):
        return False

    def stream(self, *_a, **_k):
        return _Stream()


@pytest.mark.asyncio
async def test_a_cancelled_task_leaves_the_stream_cancelled(monkeypatch):
    monkeypatch.setattr(ollama_engine.httpx, "AsyncClient", _Client)
    monkeypatch.setattr(ollama_engine, "_ollama_stream_gate", lambda *_a: None)
    got: list[str] = []

    async def read():
        async for chunk in ollama_engine._ollama_stream_generator("http://x/api/chat", {}):
            got.append(chunk)

    task = asyncio.create_task(read())
    for _ in range(50):
        await asyncio.sleep(0.01)
        if got:
            break
    assert got, "the first token never came"
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await asyncio.wait_for(task, 2)


class _Module:
    """An in-process engine that sends one token and keeps generating."""

    async def chat(self, *, stream_callback=None, **_kw):
        stream_callback("hola")
        await asyncio.sleep(3600)


@pytest.mark.asyncio
@pytest.mark.parametrize("engine", ["mlx", "llama_cpp"])
async def test_a_cancelled_task_leaves_an_in_process_stream_cancelled(engine):
    import importlib

    mod = importlib.import_module(f"core.endpoints.chat_engines.{engine}")
    make = getattr(mod, "_mlx_stream_generator" if engine == "mlx" else "_llama_cpp_stream_generator")
    got: list[str] = []

    async def read():
        async for chunk in make(_Module(), [], "sys", "model"):
            got.append(chunk)

    task = asyncio.create_task(read())
    for _ in range(100):
        await asyncio.sleep(0.01)
        if got:
            break
    assert got, "the first token never came"
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await asyncio.wait_for(task, 2)
