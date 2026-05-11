"""
------------------------------------
Server Nexe
Author: Jordi Goy
Location: core/endpoints/chat_engines/_streaming.py
Description: Shared streaming infrastructure for chat engines (MLX, Llama.cpp).

Provides TokenBridge (sync→async token bridging), SSE formatters,
and background memory save with retry.

www.jgoy.net · https://server-nexe.org
------------------------------------
"""

import asyncio
import json
import logging
import time

from ..chat_memory import _save_conversation_to_memory
from ..chat_sanitization import _sanitize_sse_token

logger = logging.getLogger(__name__)

SSE_DONE = "data: [DONE]\n\n"


class TokenBridge:
    """Bridge between synchronous token callbacks and async iteration.

    The engine thread calls :meth:`on_token` for each generated token.
    The async consumer reads from :attr:`queue` until :attr:`done` is set.
    """

    def __init__(self, maxsize: int = 2048):
        self.queue: asyncio.Queue = asyncio.Queue(maxsize=maxsize)
        self.done = asyncio.Event()
        self.result = None
        self.error = None
        self._loop = asyncio.get_running_loop()
        self._response_parts: list = []

    def on_token(self, token: str):
        """Called from the engine thread for each generated token."""
        self._response_parts.append(token)
        try:
            self._loop.call_soon_threadsafe(self.queue.put_nowait, token)
        except Exception as e:
            logger.warning("Stream token enqueue failed (queue full/closed): %s", e)  # nosemgrep: python-logger-credential-disclosure

    def set_done(self, result=None, error=None):
        """Signal that generation is complete."""
        self.result = result
        self.error = error
        self._loop.call_soon_threadsafe(self.done.set)

    def get_response_text(self) -> str:
        """Return the full accumulated response text."""
        return "".join(self._response_parts)

    def __aiter__(self):
        return self

    async def __anext__(self) -> str:
        """Yield tokens until generation is done and the queue is drained."""
        while True:
            try:
                return await asyncio.wait_for(self.queue.get(), timeout=0.1)
            except asyncio.TimeoutError:
                if self.done.is_set() and self.queue.empty():
                    raise StopAsyncIteration


def format_sse_chunk(token: str, model_name: str, engine_prefix: str) -> str:
    """Format a single token as an OpenAI-compatible SSE chunk."""
    chunk = {
        "id": f"{engine_prefix}-stream-{int(time.time())}",
        "object": "chat.completion.chunk",
        "created": int(time.time()),
        "model": model_name,
        "choices": [{
            "index": 0,
            "delta": {"content": _sanitize_sse_token(token)},
            "finish_reason": None,
        }],
    }
    return f"data: {json.dumps(chunk)}\n\n"


def format_sse_done(model_name: str, engine_prefix: str) -> str:
    """Format the final SSE chunk with finish_reason=stop."""
    final_chunk = {
        "id": f"{engine_prefix}-stream-{int(time.time())}",
        "object": "chat.completion.chunk",
        "created": int(time.time()),
        "model": model_name,
        "choices": [{
            "index": 0,
            "delta": {},
            "finish_reason": "stop",
        }],
    }
    return f"data: {json.dumps(final_chunk)}\n\n"


async def background_memory_save(app_state, user_msg: str, response_text: str):
    """Fire-and-forget conversation save with one retry."""
    if not (app_state and user_msg and response_text.strip()):
        return
    for attempt in range(2):
        try:
            await _save_conversation_to_memory(app_state, user_msg, response_text)
            return
        except Exception as e:
            if attempt == 0:
                await asyncio.sleep(1)
            else:
                logger.error("Stream Auto-Save failed after retry: %s", e)
