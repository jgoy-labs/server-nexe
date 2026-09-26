"""
────────────────────────────────────
Server Nexe
Author: Jordi Goy
Location: core/turn/stream.py
Description: The engine's stream, read as events (C4.4, moved from routes_chat.py).

www.jgoy.net · https://server-nexe.org
────────────────────────────────────
"""

import inspect
from dataclasses import dataclass, field
from typing import Any

from core.endpoints.chat_engines._common import extract_engine_text
from core.turn.text.chunks import parse_chunk
from core.turn.text.tags import TagStreamFilter
from core.turn.text.think import StreamThinkParser


@dataclass
class StreamFlags:
    """Per-request flags the engine loop hands back to the streaming body.

    `engine_events` cannot return values while it is yielding, so the
    three flags it discovers travel on this object instead. `full_response`
    deliberately does NOT live here: it stays a bare local of
    the door's streaming body, accumulated at the yield site, so a client
    disconnect finds the partial text exactly where MC-116 expects it.
    """
    # FD-S5: truncation marker state. Set by the in-band sentinel (MLX
    # via queue_generator) or by an Ollama done_reason=='length' chunk.
    trunc: bool = False
    trunc_continuable: bool = False
    has_any_thinking: bool = False
    # #1040 (C2.4): the exception `engine_events` caught mid-stream, if
    # any. The generator itself only has room to turn it into wire text (see
    # the door's `_stream_error_notice`); this is the out-of-band channel that lets the
    # caller (`generate_stream`) mark the turn PARTIAL after the fact — the
    # error is already committed to the wire by the time this is read, so the
    # turn cannot be retried, only recorded as broken.
    error: "Exception | None" = None


def apply_trunc_sentinels(chunk: Any, flags: StreamFlags) -> bool:
    """Read the FD-S5 truncation sentinels off a chunk. True = skip the chunk.

    Two shapes, and only the first one is skippable:
      - the in-band `__nexe_trunc__` sentinel (MLX, via queue_generator), which
        carries no text and must never be mixed with a content yield;
      - an Ollama passthrough `done` chunk with done_reason == 'length', which
        may still carry content for `parse_chunk` — so it is NOT skipped.
    """
    if isinstance(chunk, dict) and chunk.get("__nexe_trunc__"):
        flags.trunc = True
        flags.trunc_continuable = bool(chunk.get("continuable"))
        return True
    if (
        isinstance(chunk, dict)
        and chunk.get("done")
        and chunk.get("done_reason") == "length"
    ):
        flags.trunc = True
    return False


@dataclass
class Ready:
    """The engine answered: its first chunk arrived."""


@dataclass
class Delta:
    """One chunk, split: `wire` is what the client may see (visible, through
    the door's buffer), `full` is the raw text the turn accumulates."""
    wire: list = field(default_factory=list)
    full: str = ""


@dataclass
class Whole:
    """A non-streaming engine's whole reply, raw."""
    text: str


@dataclass
class Failed:
    """The engine raised mid-generation. Already the last event."""
    exc: Exception


def _visible(text: str) -> list:
    return [text] if text else []


async def engine_events(chat_result: Any, model_name: "str | None", flags: StreamFlags,
                        visible_buffer: Any = None):
    """The engine's stream as structured events — the loop, not its wire.

    C4.4: it used to be the web door's `_yield_engine_chunks`, which also
    wrote the door's alphabet into the loop (the MODEL_READY sentinel, LaTeX,
    the localized error notice). Those are presentation and stay there; this
    says only WHAT happened. Order is the old loop's, event for event: Ready
    before the first chunk's Delta; each Delta's `full` before its `wire`.

    `Exception` is caught with the loop it guards and becomes `Failed`.
    GeneratorExit is a BaseException, so a client disconnect still tears this
    generator down.
    """
    try:
        if inspect.isasyncgen(chat_result) or hasattr(chat_result, '__aiter__'):
            first = True
            parser = StreamThinkParser(model_name, visible_buffer=visible_buffer)
            # Section labels the model echoes ([USER MEMORY], [CONTEXT …]) never
            # reach the wire. Memory tags do: the web client paints its badges
            # from them and strips them itself.
            labels = TagStreamFilter(memory=False, labels=True)
            async for chunk in chat_result:
                if apply_trunc_sentinels(chunk, flags):
                    continue
                content, thinking = parse_chunk(chunk)
                if first:
                    first = False
                    yield Ready()
                wire, full = parser.feed(content, thinking)
                wire = _visible(labels.feed("".join(wire)))
                if isinstance(chunk, dict) and isinstance(chunk.get("raw"), str):
                    # ADR-010: the engine split its text; the turn's raw text
                    # stays exactly what the model generated (Continue needs it).
                    full = chunk["raw"]
                yield Delta(wire, full)
                flags.has_any_thinking = parser.has_any_thinking
            wire, full = parser.flush()
            yield Delta(_visible(labels.feed("".join(wire)) + labels.flush()), full)
        else:
            yield Ready()
            result = await chat_result if inspect.iscoroutine(chat_result) else chat_result
            content = extract_engine_text(result)
            if content:
                yield Whole(content)
    except Exception as e:
        flags.error = e
        yield Failed(e)
