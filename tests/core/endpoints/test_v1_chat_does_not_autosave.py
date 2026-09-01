"""Gate for F-A: no /v1/chat/completions path writes a conversation to memory.

Drives the REAL generators (chat_completions, mlx, llama_cpp, ollama), not a
local copy of the expression. Patches MemoryService.remember and Qdrant
memory.store at the source modules those functions import from — the two
sinks _save_conversation_to_memory used to write to.

A mutation that restores any of the four call sites must turn the matching
test red. Drain fire-and-forget tasks (BackgroundTasks and asyncio.create_task)
on the same loop so a restored call is visible to the spies.
"""
from __future__ import annotations

import asyncio
import inspect
import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import BackgroundTasks

from core.dependencies import limiter as _limiter


@pytest.fixture(autouse=True)
def _disable_rate_limiter():
    _limiter.enabled = False
    yield
    _limiter.enabled = True


def _spies():
    """Return (remember, store, patches-as-context-stack args)."""
    remember = AsyncMock(return_value="entry-id")
    store = AsyncMock(return_value="doc-id")
    svc = MagicMock(initialized=True, remember=remember)
    api = MagicMock(
        store=store,
        collection_exists=AsyncMock(return_value=True),
        create_collection=AsyncMock(),
    )
    return remember, store, svc, api


async def _drain_background(bg: BackgroundTasks) -> None:
    for task in list(getattr(bg, "tasks", ())):
        result = task.func(*task.args, **task.kwargs)
        if inspect.isawaitable(result):
            await result


async def _drain_agen_and_tasks(agen):
    chunks = []
    async for chunk in agen:
        chunks.append(chunk)
    await asyncio.sleep(0)
    extra = [t for t in asyncio.all_tasks() if t is not asyncio.current_task()]
    if extra:
        await asyncio.gather(*extra, return_exceptions=True)
    return chunks


def _assert_no_memory_write(remember, store):
    assert remember.await_count == 0, (
        "MemoryService.remember() was called from a /v1 chat path; "
        f"calls={remember.await_args_list}"
    )
    assert store.await_count == 0, (
        "Qdrant memory.store() was called from a /v1 chat path; "
        f"calls={store.await_args_list}"
    )


class TestV1ChatCompletionsDoesNotWriteMemory:
    def test_non_streaming_path_does_not_remember_or_store(self):
        from core.endpoints.chat import chat_completions, ChatCompletionRequest, Message

        remember, store, svc, api = _spies()
        req = MagicMock()
        req.app.state.config = {}
        req.app.state.modules = {}
        req.headers = {"x-api-key": "test-key"}
        bg = BackgroundTasks()
        body = ChatCompletionRequest(
            messages=[Message(role="user", content="hola")],
            use_rag=False,
            stream=False,
            engine="ollama",
        )

        async def _run():
            with patch("memory.memory.module.get_memory_service", return_value=svc), \
                 patch("memory.memory.api.v1.get_memory_api", AsyncMock(return_value=api)), \
                 patch(
                     "core.endpoints.chat._forward_to_ollama",
                     new=AsyncMock(return_value={
                         "choices": [{"message": {"content": "adeu"}}],
                     }),
                 ):
                await chat_completions(body, req, bg)
                await _drain_background(bg)
            _assert_no_memory_write(remember, store)

        asyncio.run(_run())

    def test_mlx_stream_does_not_remember_or_store(self):
        from core.endpoints.chat_engines.mlx import _mlx_stream_generator

        remember, store, svc, api = _spies()

        async def fake_chat(**kwargs):
            cb = kwargs.get("stream_callback")
            if cb:
                cb("Hola")
            return {"response": "Hola", "tokens": 1, "tokens_per_second": 1}

        mock_mlx = MagicMock()
        mock_mlx.chat = fake_chat

        async def _run():
            with patch("memory.memory.module.get_memory_service", return_value=svc), \
                 patch("memory.memory.api.v1.get_memory_api", AsyncMock(return_value=api)):
                await _drain_agen_and_tasks(
                    _mlx_stream_generator(
                        mock_mlx,
                        [{"role": "user", "content": "hi"}],
                        "system",
                        "mlx-local",
                        app_state=MagicMock(),
                        user_msg="hi",
                    )
                )
            _assert_no_memory_write(remember, store)

        asyncio.run(_run())

    def test_llama_cpp_stream_does_not_remember_or_store(self):
        from core.endpoints.chat_engines.llama_cpp import _llama_cpp_stream_generator

        remember, store, svc, api = _spies()

        async def fake_chat(**kwargs):
            cb = kwargs.get("stream_callback")
            if cb:
                cb("Hola")
            return {"response": "Hola", "tokens": 1}

        mock_llama = MagicMock()
        mock_llama.chat = fake_chat

        async def _run():
            with patch("memory.memory.module.get_memory_service", return_value=svc), \
                 patch("memory.memory.api.v1.get_memory_api", AsyncMock(return_value=api)):
                await _drain_agen_and_tasks(
                    _llama_cpp_stream_generator(
                        mock_llama,
                        [{"role": "user", "content": "hi"}],
                        "system",
                        "llama-cpp-local",
                        app_state=MagicMock(),
                        user_msg="hi",
                    )
                )
            _assert_no_memory_write(remember, store)

        asyncio.run(_run())

    def test_ollama_stream_does_not_remember_or_store(self):
        from core.endpoints.chat_engines.ollama import _ollama_stream_generator

        remember, store, svc, api = _spies()

        ollama_lines = [
            json.dumps({"message": {"content": "Hola"}, "done": False}),
            json.dumps({"message": {"content": ""}, "done": True, "done_reason": "stop"}),
        ]

        async def _aiter():
            for line in ollama_lines:
                yield line

        mock_resp = AsyncMock()
        mock_resp.status_code = 200
        mock_resp.aiter_lines = MagicMock(return_value=_aiter())

        mock_stream_cm = AsyncMock()
        mock_stream_cm.__aenter__ = AsyncMock(return_value=mock_resp)
        mock_stream_cm.__aexit__ = AsyncMock(return_value=False)

        mock_client = AsyncMock()
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)
        mock_client.stream = MagicMock(return_value=mock_stream_cm)

        async def _run():
            with patch("memory.memory.module.get_memory_service", return_value=svc), \
                 patch("memory.memory.api.v1.get_memory_api", AsyncMock(return_value=api)), \
                 patch("httpx.AsyncClient", return_value=mock_client):
                await _drain_agen_and_tasks(
                    _ollama_stream_generator(
                        "http://localhost/api/chat",
                        {"model": "test", "messages": []},
                        app_state=MagicMock(),
                        user_msg="hi",
                    )
                )
            _assert_no_memory_write(remember, store)

        asyncio.run(_run())
