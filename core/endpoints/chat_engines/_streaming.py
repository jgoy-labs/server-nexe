"""
------------------------------------
Server Nexe
Author: Jordi Goy
Location: core/endpoints/chat_engines/_streaming.py
Description: Shared streaming infrastructure for chat engines (MLX, Llama.cpp).

Provides TokenBridge (sync→async token bridging) and SSE formatters.

www.jgoy.net · https://server-nexe.org
------------------------------------
"""

import asyncio
import json
import logging
import os
import time

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


async def _prepend_chunk(first: str, agen):
    """Re-emit ``first`` (already pulled off ``agen`` by the caller), then drain it.

    #1036 (C2.4): the forwarders must "peek" the generator's first chunk
    before wrapping it in a ``StreamingResponse``, so an error that happens
    before any token reaches the client raises out of that peek as a real
    exception the cascade can retry — instead of only surfacing once
    ``StreamingResponse`` starts draining the generator, by which point the
    cascade's own ``try`` has long since returned.
    """
    yield first
    async for chunk in agen:
        yield chunk


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


def format_sse_done(
    model_name: str,
    engine_prefix: str,
    truncated: bool = False,
    finish_reason: str | None = None,
) -> str:
    """Format the final SSE chunk.

    ``finish_reason`` is ``"stop"`` for a clean completion, or ``"length"``
    (the OpenAI-canonical value for a cut-off response) in two cases:

    * ``truncated`` — the bridge queue overflowed and tokens were dropped
      (B216). Kept as-is: the drop must stay visible to the client.
    * ``finish_reason`` — the ENGINE reports it hit the token ceiling. The
      blocking path already forwards this (``build_openai_response``); a
      stream used to throw it away and always close with "stop", so an
      OpenAI-compatible client (stream=True is the default in LangChain,
      Open WebUI, aider and Continue) never asked for the tail.

    Anything the engine cannot answer for degrades to "stop": an absent
    reason is not a truncation.

    The two cases are NOT the same cut, and "length" alone cannot tell them
    apart, so the chunk also carries ``x_nexe_truncation`` (#989):

    * ``"ceiling"`` — the answer is missing its TAIL. A client that asks for
      the continuation stitches it in the right place.
    * ``"overflow"`` — tokens were dropped from the MIDDLE and the ending
      that arrived is the natural one. Resuming would append new text over
      an internal hole, producing something that reads as coherent and is
      not. Such an answer cannot be repaired by continuing it.

    The field is absent on a clean stop, and ``"overflow"`` wins when both
    happen at once: an internal hole is the damage a client must not paper
    over, whatever else went on. It is an extension, not OpenAI: it lives at
    the root of the chunk (where ``system_fingerprint`` lives) so a strict
    client that validates ``choices`` never sees it, and one that ignores
    unknown keys behaves exactly as before.
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
            "finish_reason": "length" if (truncated or finish_reason == "length") else "stop",
        }],
    }
    cause = "overflow" if truncated else ("ceiling" if finish_reason == "length" else None)
    if cause:
        final_chunk["x_nexe_truncation"] = cause
    return f"data: {json.dumps(final_chunk)}\n\n"
