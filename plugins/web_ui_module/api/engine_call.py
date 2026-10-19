"""
------------------------------------
Server Nexe
Location: plugins/web_ui_module/api/engine_call.py
Description: The web door's engine call: starting an engine's generation in
             its shape (Ollama-style, the in-process MLX / llama.cpp queue,
             generic), reading its first event before the cascade commits to
             it, its stream in this door's alphabet, a JSON-mode reply, and the
             second call of a tags-only turn. Split out of routes_chat.py
             (2026-10-04); the start itself moved to core/turn/engine_start.py
             (C4.8-a).

www.jgoy.net · https://server-nexe.org
------------------------------------
"""

import asyncio
import inspect
import logging
from dataclasses import dataclass
from typing import Any

from core.endpoints.chat_engines._common import extract_engine_text as _engine_text
from core.turn.errors import StreamCapExceeded
from core.turn.stream import (
    Delta, Failed, Ready, StreamFlags, StreamGuard, Whole, add_chunk_usage, add_result_usage, close_quietly,
    engine_events,
)
from plugins.web_ui_module.api.wire import _stream_error_notice
from plugins.web_ui_module.core.latex_sanitizer import LatexStreamBuffer, latex_to_unicode

logger = logging.getLogger(__name__)


@dataclass
class RepromptSetup:
    """This door's way of asking its engine once more — `policy.reprompt_chunks`'s
    `call` (C4.5): what `generate` had in hand when the engine started, kept as
    DATA so two turns that differ only in `ctx.entry` compare equal (the I1
    contract test reads the door's scratch). Ollama-shaped engines only, as it
    has always been: MLX and llama.cpp run through a queue and a worker thread
    (`start_engine_call`) that was never wired for a second call. Returning
    None for them lets the core SAY it skipped, where `_yield_reprompt` used to
    skip in silence."""
    engine: Any
    sig: Any
    model_name: "str | None"
    messages: list
    thinking_enabled: bool

    def __call__(self, system_prompt: str):
        if "model" not in self.sig.parameters:
            return None
        full = [{"role": "system", "content": system_prompt}] + list(self.messages)
        return self.engine.chat(
            model=self.model_name, messages=full, stream=True, thinking_enabled=self.thinking_enabled,
        )


def reprompt_call_for(engine, sig, model_name, messages: list, thinking_enabled: bool) -> RepromptSetup:
    return RepromptSetup(engine, sig, model_name, messages, thinking_enabled)


def _json_chunk_text(chunk) -> "str | None":
    """The text of one chunk of a JSON-mode reply, whatever the engine's shape."""
    if isinstance(chunk, dict) and "message" in chunk and "content" in chunk["message"]:
        return chunk["message"]["content"]
    if isinstance(chunk, dict) and "content" in chunk:
        return chunk["content"]
    if isinstance(chunk, str):
        return chunk
    return None


async def _accumulate_nonstreaming_response(chat_result, response_chunks: list, on_first_chunk=None,
                                            said: "dict | None" = None) -> bool:
    """Accumulate chunks from a non-streaming chat_result into response_chunks.

    #1039: through the core's `StreamGuard`, like the streaming shape — no
    control characters, and a reply that grows past `NEXE_MAX_STREAM_MB` stops
    there. Returns True when it did: the text so far is kept, and the caller
    ends the turn partial and stops the engine's worker.

    `on_first_chunk` (#1165) is called once, when the engine hands over its
    first chunk: the JSON door's first byte. An engine whose answer comes
    whole (a coroutine) hands over nothing before its end.

    `said`, if given, receives `usage`: what the engine says the call cost.
    """
    guard = StreamGuard()
    try:
        if inspect.isasyncgen(chat_result) or hasattr(chat_result, '__aiter__'):
            async for chunk in chat_result:
                if on_first_chunk is not None:
                    on_first_chunk()
                    on_first_chunk = None
                if said is not None:
                    add_chunk_usage(said, chunk)
                text = _json_chunk_text(chunk)
                if text is not None:
                    response_chunks.append(guard.take(text, "")[0])
        else:
            result = await chat_result if inspect.iscoroutine(chat_result) else chat_result
            if said is not None:
                add_result_usage(said, result)
            content = _engine_text(result)
            if content:
                response_chunks.append(guard.take(content, "")[0])
    except StreamCapExceeded:
        await close_quietly(chat_result)
        return True
    return False


@dataclass
class StreamingChatContext:
    """Request-scoped state of one streamed answer (MC-027 F2), built by the
    `generate` adapter and read by the steps after it.

    `session`, `messages` and `memory_helper` are LIVE references (mutated in place,
    never copied); `disconnect_monitor_task` is the live asyncio.Task the turn's
    `generate` step started (INV-CRIT-01/02/06).
    """
    model_name: "str | None"
    rag_count: int
    rag_items: list
    compacted: bool
    doc_truncated_pct: int
    session: Any
    session_mgr: Any
    memory_helper: Any
    engine: Any
    engine_name: str
    chat_result: Any
    sig: Any
    system_prompt: str
    messages: list
    thinking_enabled: bool
    lang: "str | None"
    message: str
    disconnect_monitor_task: "asyncio.Task"
    # UI collection toggles for this request; None = all collections enabled
    # (old clients / bare API calls). Gates MEM_SAVE persistence.
    rag_collections: "list | None" = None


async def claim_engine_start(chat_result, model_name: "str | None", flags: StreamFlags):
    """The engine's first event, read before this engine is given the stream.

    A streaming turn used to treat "the generator object exists" as the engine
    having started, and only then pull a chunk. llama.cpp refusing an image on
    a Continue, and Ollama answering 404 for a model, both happen on that
    first pull, so the next engine was never asked. This peek lets the
    cascade move. Once a real event has arrived, this engine owns the stream.

    #1117: it never raises. A `Failed` comes back with its stream closed and
    `flags.error` set, so the caller decides: the next engine, or this
    failure written as the turn's notice when no engine claims the stream
    (the response is already committed; a raise would cut the connection).
    """
    events = engine_events(
        chat_result, model_name, flags, visible_buffer=LatexStreamBuffer(),
    )
    try:
        first = await events.__anext__()
    except StopAsyncIteration:
        # `engine_events` always yields something; this keeps the contract if
        # that ever changes.
        exc = RuntimeError("engine ended before its first event")
        flags.error = exc
        return events, Failed(exc)
    if isinstance(first, Failed):
        await events.aclose()
    return events, first


async def _event_source(primed):
    """The events `claim_engine_start` opened, its first one included."""
    events, first = primed
    yield first
    async for ev in events:
        yield ev


async def _yield_engine_chunks(ctx: "StreamingChatContext", primed):
    """The engine's events in this door's alphabet: `(wire_token, full_delta)`.

    C4.4: the loop is the core's (`core.turn.stream.engine_events`); what is
    left here is the web door's presentation — the MODEL_READY sentinel, the
    LaTeX buffer, the localized error notice. The caller owns `full_response`:
    a pair whose token is None is accumulation only, and it comes before the
    wire tokens of its chunk, so a disconnect leaves the partial text where
    MC-116 expects it.

    `primed` is `(events, first)` from `claim_engine_start`: the cascade has
    already pulled the first event, and the same parser has to finish the turn.
    A primed `Failed` (no engine claimed the stream, #1117) comes out as the
    notice alone.
    """
    async for ev in _event_source(primed):
        if isinstance(ev, Ready):
            yield "\x00[MODEL_READY]\x00", ""
        elif isinstance(ev, Delta):
            yield None, ev.full
            for _tok in ev.wire:
                yield _tok, ""
        elif isinstance(ev, Whole):
            yield latex_to_unicode(ev.text), ev.text
        elif isinstance(ev, Failed):
            yield _stream_error_notice(ev.exc, ctx.lang), ""
