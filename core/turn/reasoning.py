"""
────────────────────────────────────
Server Nexe
Author: Jordi Goy
Location: core/turn/reasoning.py
Description: The engine contract for a model's reasoning (ADR-010).

An engine returns its output STRUCTURED: each chunk is
`{"message": {"content": …, "thinking": …}}` — the shape Ollama already
returns natively and `core.turn.text.chunks.parse_chunk` already reads — so
no door has to guess where the answer starts. An engine whose model writes
its reasoning INTO the text (MLX, llama.cpp: <think> tags, a template that
opens the block in the prompt, gpt-oss harmony channels) splits it with
`ReasoningSplitter`. Knowing which case applies is the engine's; how to
split is here, once.

A structured chunk may carry `"raw"`: the model's text exactly as generated.
The web door keeps it as the turn's raw text (a truncated turn's Continue
needs the exact token prefix); nothing shows it to anyone.

www.jgoy.net · https://server-nexe.org
────────────────────────────────────
"""
from __future__ import annotations

from typing import Callable, Optional

from core.turn.text.harmony import HarmonyStreamFilter

_OPEN, _CLOSE = "<think>", "</think>"


def _held_prefix(text: str, tag: str) -> int:
    """How many trailing chars of `text` could be the start of `tag`."""
    for k in range(min(len(tag) - 1, len(text)), 0, -1):
        if tag.startswith(text[-k:]):
            return k
    return 0


def structured_chunk(content: str, thinking: str, raw: Optional[str] = None) -> dict:
    """One engine chunk in the contract's shape."""
    chunk: dict = {"message": {"content": content, "thinking": thinking}}
    if raw is not None:
        chunk["raw"] = raw
    return chunk


class ReasoningSplitter:
    """Splits a model's text stream into (thinking, content), statefully.

    - Tags split across chunks are held until they resolve.
    - Blocks NEST: a model reasoning about a text that contains the tags
      quotes them inside its own block; only the outermost pair delimits.
    - `starts_inside`: the chat template opened the block in the PROMPT, so
      the model's text begins inside it and only ever writes `</think>`.
    - `harmony`: gpt-oss channels, rewritten to <think> first.
    - A partial tag held at the end is text; an unclosed block is reasoning.
    - The whitespace a model puts between its block and its answer goes with
      the block (the exact text travels as `raw` anyway).
    """

    def __init__(self, *, starts_inside: bool = False, harmony: bool = False) -> None:
        self._depth = 1 if starts_inside else 0
        self._pending = ""
        self._after_block = False
        self._harmony = HarmonyStreamFilter() if harmony else None

    def feed(self, text: str) -> tuple[str, str]:
        if self._harmony is not None:
            text = self._harmony.feed(text)
        return self._split(text)

    def flush(self) -> tuple[str, str]:
        thinking, content = ("", "")
        if self._harmony is not None:
            thinking, content = self._split(self._harmony.flush())
        pending, self._pending = self._pending, ""
        if self._depth:
            thinking += pending
        else:
            content += self._answer(pending)
        return thinking, content

    def _answer(self, text: str) -> str:
        if self._after_block and text:
            text = text.lstrip()
            if text:
                self._after_block = False
        return text

    def _split(self, text: str) -> tuple[str, str]:
        buf, self._pending = self._pending + text, ""
        thinking: list[str] = []
        content: list[str] = []
        i = 0
        while i < len(buf):
            o = buf.find(_OPEN, i)
            c = buf.find(_CLOSE, i) if self._depth else -1
            hits = [x for x in (o, c) if x >= 0]
            if hits:
                j = min(hits)
                if self._depth:
                    thinking.append(buf[i:j])
                else:
                    content.append(self._answer(buf[i:j]))
                if j == o:
                    if self._depth:
                        thinking.append(_OPEN)  # quoted inside the reasoning
                    self._depth += 1
                    i = j + len(_OPEN)
                else:
                    self._depth -= 1
                    if self._depth:
                        thinking.append(_CLOSE)
                    else:
                        self._after_block = True
                    i = j + len(_CLOSE)
                continue
            rest = buf[i:]
            k = max(_held_prefix(rest, _OPEN), _held_prefix(rest, _CLOSE) if self._depth else 0)
            if self._depth:
                thinking.append(rest[:len(rest) - k])
            else:
                content.append(self._answer(rest[:len(rest) - k]))
            self._pending = rest[len(rest) - k:] if k else ""
            break
        return "".join(thinking), "".join(content)


def split_text(text: str, *, starts_inside: bool = False, harmony: bool = False) -> tuple[str, str]:
    """A whole reply, split: (thinking, content)."""
    splitter = ReasoningSplitter(starts_inside=starts_inside, harmony=harmony)
    t1, c1 = splitter.feed(text)
    t2, c2 = splitter.flush()
    return t1 + t2, c1 + c2


def structured_callback(stream_callback: Callable, splitter: ReasoningSplitter) -> Callable:
    """The caller's callback, fed {thinking, content} chunks instead of text.

    For an engine whose generation calls back from a worker thread, wrap
    THIS in its thread-safe bridge (not the other way round), so the splitter
    runs on the event loop and sees the tokens in order. `raw` keeps the exact text for the
    web door's Continue. `flush_reasoning()` sends what the splitter holds.
    """
    def _emit(thinking: str, content: str, raw: str) -> None:
        if thinking or content or raw:
            stream_callback(structured_chunk(content, thinking, raw=raw))

    def callback(token):
        if not isinstance(token, str):
            stream_callback(token)
            return
        thinking, content = splitter.feed(token)
        _emit(thinking, content, token)

    def flush_reasoning() -> None:
        thinking, content = splitter.flush()
        _emit(thinking, content, "")

    callback.flush_reasoning = flush_reasoning  # type: ignore[attr-defined]
    return callback


def wrap_for_split(stream_callback: Optional[Callable], split: Optional[dict]):
    """(callback to bridge, structured callback or None) for an engine's turn.

    The engine bridges the FIRST to its worker thread; the second, when the
    turn is split, is what `finish_split` flushes.
    """
    if split is None or not stream_callback:
        return stream_callback, None
    cb = structured_callback(stream_callback, ReasoningSplitter(**split))
    return cb, cb


def finish_split(structured_cb: Optional[Callable], split: Optional[dict], text: str) -> tuple[str, str]:
    """Flush the stream's splitter, and split the whole reply: (thinking, answer).

    Called on the event loop after the worker returned: its last tokens were
    queued there before the result was, so they have all been fed.
    """
    if structured_cb is not None:
        structured_cb.flush_reasoning()  # type: ignore[attr-defined]
    if split is None:
        return "", text
    return split_text(text, **split)
