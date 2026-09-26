"""
────────────────────────────────────
Server Nexe
Author: Jordi Goy
Location: core/turn/text/sse.py
Description: The /v1 stream, cleaned on its way out (C4.4-b).

Each engine forwarder (`core/endpoints/chat_engines/{mlx,llama_cpp,ollama}.py`)
writes OpenAI SSE chunks straight from the model's tokens. Until C4.4 nothing
between them and the client knew the model's format, so a /v1 client streamed
<think> blocks, harmony channels and [MEM_SAVE:] tags raw — the web door has
always hidden them. `SseCleaner` sits on the one seam all three share (the
`generate` adapter's body wrapper) and runs each chunk's `delta.content`
through the same stateful parser the web door uses, plus a memory-tag filter
that holds a `[` only while it can still become a tag.

www.jgoy.net · https://server-nexe.org
────────────────────────────────────
"""
from __future__ import annotations

import json
from typing import Any, Optional

from core.turn.reasoning import ReasoningSplitter
from core.turn.text.tags import MemTagStreamFilter  # noqa: F401 — re-exported for callers
from core.turn.text.tags import TagStreamFilter
from core.turn.text.think import StreamThinkParser

class ThinkTagStreamFilter:
    """Drops <think>…</think> from a stream, with the tags split anywhere.

    The answer half of `ReasoningSplitter` (ADR-010): nested blocks, split
    tags, an unclosed block at the end dropped.
    """

    def __init__(self) -> None:
        self._split = ReasoningSplitter()

    def feed(self, text: str) -> str:
        return self._split.feed(text)[1]

    def flush(self) -> str:
        return self._split.flush()[1]


class SseCleaner:
    """Rewrites /v1 SSE chunks: the answer clean in `content`, the reasoning
    in `reasoning` — kept only when the client asked for it (ADR-010).

    The engines already hand the reasoning apart (`delta.reasoning`). What a
    model still writes INTO the text — tags, harmony — is split here as a
    safety net and joins the reasoning, never the answer.
    """

    def __init__(self, model_name: Optional[str], keep_reasoning: bool = False) -> None:
        self._keep = keep_reasoning
        self._split = ReasoningSplitter(harmony="gpt-oss" in str(model_name or "").lower())
        self._think = StreamThinkParser(model_name)
        self._tags = TagStreamFilter(memory=True, labels=True)
        self._template: Optional[dict] = None
        self._flushed = False

    def _clean(self, content: str) -> tuple[str, str]:
        reasoning, answer = self._split.feed(content)
        wire, _full = self._think.feed(answer, "")
        return reasoning, self._tags.feed("".join(wire))

    def _tail(self) -> tuple[str, str]:
        reasoning, answer = self._split.flush()
        wire, _full = self._think.feed(answer, "")
        tail_wire, _full = self._think.flush()
        return reasoning, self._tags.feed("".join(wire) + "".join(tail_wire)) + self._tags.flush()

    def _tail_event(self) -> Optional[str]:
        """What the parsers still hold, as one more chunk — once."""
        if self._flushed:
            return None
        self._flushed = True
        reasoning, tail = self._tail()
        delta: dict = {}
        if tail:
            delta["content"] = tail
        if reasoning and self._keep:
            delta["reasoning"] = reasoning
        if not delta or self._template is None:
            return None
        obj = json.loads(json.dumps(self._template))
        obj["choices"][0]["delta"] = delta
        obj["choices"][0]["finish_reason"] = None
        return f"data: {json.dumps(obj)}\n\n"

    def _rewrite_delta(self, delta: dict) -> None:
        reasoning = delta.get("reasoning") if isinstance(delta.get("reasoning"), str) else ""
        content = delta.get("content")
        if isinstance(content, str):
            extra, delta["content"] = self._clean(content)
            reasoning += extra
            if not delta["content"]:
                del delta["content"]
        if reasoning and self._keep:
            delta["reasoning"] = reasoning
        else:
            delta.pop("reasoning", None)

    def _event(self, event: str) -> list[str]:
        if not event.startswith("data: "):
            return [event + "\n\n"]
        payload = event[len("data: "):]
        if payload.strip() == "[DONE]":
            tail = self._tail_event()
            return ([tail] if tail else []) + [event + "\n\n"]
        try:
            obj = json.loads(payload)
            choice = obj["choices"][0]
        except (ValueError, KeyError, IndexError, TypeError):
            return [event + "\n\n"]
        out: list[str] = []
        delta = choice.get("delta")
        if isinstance(delta, dict) and ("content" in delta or "reasoning" in delta):
            self._template = obj
            self._rewrite_delta(delta)
            if not delta and choice.get("finish_reason") is None:
                return []
        if choice.get("finish_reason") is not None:
            tail = self._tail_event()
            if tail:
                out.append(tail)
        out.append(f"data: {json.dumps(obj)}\n\n")
        return out

    def rewrite(self, chunk: Any) -> list[Any]:
        """One upstream chunk in, the chunks to send out (maybe none)."""
        as_bytes = isinstance(chunk, (bytes, bytearray))
        text = chunk.decode("utf-8") if as_bytes else chunk
        if not isinstance(text, str):
            return [chunk]
        events = [e for e in text.split("\n\n") if e]
        out: list[str] = []
        for event in events:
            out.extend(self._event(event))
        return [o.encode("utf-8") for o in out] if as_bytes else out

    def close(self) -> list[str]:
        """End of stream with no [DONE] or finish chunk: send what is held."""
        tail = self._tail_event()
        return [tail] if tail else []
