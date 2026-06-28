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
import os
import time

from ..chat_memory import _save_conversation_to_memory
from ..chat_sanitization import _sanitize_sse_token

logger = logging.getLogger(__name__)

SSE_DONE = "data: [DONE]\n\n"

# hard cap on streamed bytes per response.
# Without an explicit limit a runaway generation (model loop, prompt
# injection that keeps the engine talking, mis-configured stop tokens)
# would accumulate forever in TokenBridge._response_parts and exhaust
# memory both on the server and on the Tauri client that mirrors the
# SSE stream. 100 MB ≈ 500 pages of text — plenty of headroom for
# legitimate responses while still bounded. Configurable via the env
# var NEXE_MAX_STREAM_MB; values above 100 emit a warning at import
# time because they materially raise the OOM blast radius.
_DEFAULT_MAX_STREAM_MB = 100


def _resolve_max_stream_bytes() -> int:
    raw = os.environ.get("NEXE_MAX_STREAM_MB")
    if raw is None or raw.strip() == "":
        return _DEFAULT_MAX_STREAM_MB * 1024 * 1024
    try:
        value = int(raw.strip())
    except ValueError:
        logger.warning(
            "NEXE_MAX_STREAM_MB=%r is not an integer; "
            "falling back to the %d MB default",
            raw, _DEFAULT_MAX_STREAM_MB,
        )
        return _DEFAULT_MAX_STREAM_MB * 1024 * 1024
    if value <= 0:
        logger.warning(
            "NEXE_MAX_STREAM_MB=%d is not positive; "
            "falling back to the %d MB default",
            value, _DEFAULT_MAX_STREAM_MB,
        )
        return _DEFAULT_MAX_STREAM_MB * 1024 * 1024
    if value > _DEFAULT_MAX_STREAM_MB:
        logger.warning(
            "NEXE_MAX_STREAM_MB=%d MB exceeds the recommended "
            "ceiling of %d MB; raising it increases the OOM blast radius of a "
            "runaway generation. Keep it lean unless you really need it.",
            value, _DEFAULT_MAX_STREAM_MB,
        )
    return value * 1024 * 1024


MAX_STREAM_BYTES = _resolve_max_stream_bytes()


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
        # running byte counter for the cap below.
        self._response_bytes: int = 0
        self._cap_triggered: bool = False
        # B216: set when at least one token was dropped because the queue was
        # full. We keep dropping (drop > OOM, decision CS2) but the loss is no
        # longer silent: it is logged once and surfaced to the client.
        self._truncated: bool = False

    def on_token(self, token: str):
        """Called from the engine thread for each generated token.

        enforce MAX_STREAM_BYTES so a runaway generation
        cannot keep allocating into `_response_parts` indefinitely. Once
        the cap fires, set_done is signalled with an explicit error and
        further tokens are dropped silently (the engine thread may still
        emit a few before it observes `done`).
        """
        if self._cap_triggered:
            return
        token_bytes = len(token.encode("utf-8", errors="replace"))
        if self._response_bytes + token_bytes > MAX_STREAM_BYTES:
            self._cap_triggered = True
            logger.warning(
                "stream cap reached (%d bytes ≥ %d). "
                "Terminating generation early.",
                self._response_bytes, MAX_STREAM_BYTES,
            )
            self.set_done(error="stream_cap_exceeded")
            return
        self._response_bytes += token_bytes
        self._response_parts.append(token)

        def _enqueue() -> None:
            # Runs on the event loop. The real put_nowait lives HERE, so the
            # QueueFull it can raise must be caught HERE — not around the
            # call_soon_threadsafe scheduling above (B216). On overflow we drop
            # the token (drop > OOM, CS2) but mark _truncated and warn once.
            try:
                self.queue.put_nowait(token)
            except asyncio.QueueFull:
                if not self._truncated:
                    self._truncated = True
                    logger.warning(
                        "Stream queue full (maxsize=%d): dropping token, response "
                        "will be truncated (drop>OOM policy, CS2).",
                        self.queue.maxsize,
                    )

        try:
            self._loop.call_soon_threadsafe(_enqueue)
        except RuntimeError as e:
            # the loop is closed/closing — nothing more we can do with this token
            logger.warning("Stream token enqueue scheduling failed (loop closed): %s", e)  # nosemgrep: python-logger-credential-disclosure

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
    now = int(time.time())
    chunk = {
        "id": f"{engine_prefix}-stream-{now}",
        "object": "chat.completion.chunk",
        "created": now,
        "model": model_name,
        "choices": [{
            "index": 0,
            "delta": {"content": _sanitize_sse_token(token)},
            "finish_reason": None,
        }],
    }
    return f"data: {json.dumps(chunk)}\n\n"


def format_sse_done(model_name: str, engine_prefix: str, truncated: bool = False) -> str:
    """Format the final SSE chunk.

    ``finish_reason`` is ``"stop"`` for a clean completion, or ``"length"``
    (the OpenAI-canonical value for a cut-off response) when the stream was
    truncated because the bridge queue overflowed (B216). This makes the
    silent token drop visible to the client.
    """
    now = int(time.time())
    final_chunk = {
        "id": f"{engine_prefix}-stream-{now}",
        "object": "chat.completion.chunk",
        "created": now,
        "model": model_name,
        "choices": [{
            "index": 0,
            "delta": {},
            "finish_reason": "length" if truncated else "stop",
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
                logger.error("Stream Auto-Save failed after retry: %s", e, exc_info=True)
