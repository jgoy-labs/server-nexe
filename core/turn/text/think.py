"""
────────────────────────────────────
Server Nexe
Author: Jordi Goy
Location: core/turn/text/think.py
Description: Thinking, separated from the answer: whole text and stream (C4.4, moved from routes_chat.py).

www.jgoy.net · https://server-nexe.org
────────────────────────────────────
"""

from typing import Any

from core.turn.text.chunks import normalize_content
from core.turn.text.harmony import HarmonyStreamFilter


def _memoria_re():
    """Deferred (see core/turn/text/clean.py): the extractor's [MEMORIA:] regex."""
    from core.memory_facts import extract as memory_extract
    return memory_extract._MEMORIA_RE


class _Passthrough:
    """The visible buffer for a door that has none: text in, same text out."""

    def feed(self, text: str) -> str:
        return text

    def flush(self) -> str:
        return ""


def process_content_think_tags(content: str, in_think: bool) -> tuple[str, bool, bool]:
    """Split the visible part of a chunk with embedded <think> tags (qwq:32b, etc.).

    Returns (visible, in_think_new, found_thinking).
    """
    if '<think>' not in content and '</think>' not in content and not in_think:
        return content, False, False
    vis_parts: list[str] = []
    sc = 0
    found_thinking = False
    while sc < len(content):
        if in_think:
            te = content.find('</think>', sc)
            if te >= 0:
                in_think = False
                sc = te + 8
            else:
                break
        else:
            ts = content.find('<think>', sc)
            if ts >= 0:
                if ts > sc:
                    vis_parts.append(content[sc:ts])
                in_think = True
                found_thinking = True
                sc = ts + 7
            else:
                vis_parts.append(content[sc:])
                break
    return ''.join(vis_parts), in_think, found_thinking


class StreamThinkParser:
    """Per-request streaming FSM extracted from response_generator (MC-027 F1).

    Owns the cross-chunk think / content-think / harmony / latex state and turns
    each engine chunk's ``(content, thinking)`` into ``(wire_tokens, full_delta)``:

      - ``wire_tokens``: the strings to yield to the client — already ``<think>``
        wrapped, harmony filtered, the door's visible buffer applied and ``[MEMORIA: ...]`` stripped (visible).
      - ``full_delta``: the raw text to append to ``full_response`` — think tags
        included, pre-latex — what ``clean_full_response`` later strips at persist.

    The visible/raw split is load-bearing (INV-HIGH-07): the wire shows the buffered
    visible form while ``full_response`` keeps the raw content so think/harmony tags
    can be removed at persist time. ``feed()`` and ``flush()`` both return
    ``(wire, full_delta)``; ``flush()`` closes any open harmony ``<think>`` (B027a)
    and drains the pending latex buffer. Behaviour is byte-equivalent to the inline
    loop it replaces.
    """

    def __init__(self, model_name: "str | None", visible_buffer: Any = None) -> None:
        self._model_name = model_name
        self._in_thinking = False
        self._in_content_think = False
        # C4.4: the visible text goes through the DOOR's buffer (the web UI
        # passes its LaTeX one — presentation, not the model's format). None
        # passes the text through unchanged.
        self._latex_buf = visible_buffer if visible_buffer is not None else _Passthrough()
        # B027a: gpt-oss emits harmony channel tags (<|channel|>analysis<|message|>…)
        # split across chunks — a stateless replace cannot pair them and the
        # reasoning leaked into the visible bubble. Stateful filter → canonical
        # <think>. Only instantiated for gpt-oss; other models use normalize_content.
        self._harmony_buf = (
            HarmonyStreamFilter()
            if "gpt-oss" in str(model_name).lower() else None
        )
        self.has_any_thinking = False

    def feed(self, content: str, thinking: str) -> "tuple[list[str], str]":
        wire: list[str] = []
        full = ""
        # Stream thinking tokens wrapped in <think> tags (open/close on transition)
        if thinking:
            if not self._in_thinking:
                self._in_thinking = True
                self.has_any_thinking = True
                wire.append("<think>")
                full += "<think>"
            wire.append(thinking)
            full += thinking
        elif self._in_thinking:
            # Transition: thinking done, close tag
            self._in_thinking = False
            wire.append("</think>")
            full += "</think>"

        if content:
            if self._harmony_buf is not None:
                content = self._harmony_buf.feed(content)
            else:
                content = normalize_content(content, self._model_name)
        if content:
            full += content
            # Separate embedded <think> blocks in content (qwq:32b, etc.)
            visible, self._in_content_think, _found_thinking = process_content_think_tags(
                content, self._in_content_think
            )
            if _found_thinking:
                self.has_any_thinking = True
            # Bug B-mem-visible: strip [MEMORIA: ...] from visible output — gpt-oss:20b
            # emits this tag instead of [MEM_SAVE: ...]. Processed in clean_response;
            # here we hide it from the user.
            if visible and _memoria_re().search(visible):
                visible = _memoria_re().sub('', visible)
            if visible:
                emit = self._latex_buf.feed(visible)
                if emit:
                    wire.append(emit)
        return wire, full

    def flush(self) -> "tuple[list[str], str]":
        wire: list[str] = []
        full = ""
        # Flush harmony leftovers (closes an open <think>)
        if self._harmony_buf is not None:
            _harmony_tail = self._harmony_buf.flush()
            if _harmony_tail:
                full += _harmony_tail
                _h_visible, self._in_content_think, _f = process_content_think_tags(
                    _harmony_tail, self._in_content_think
                )
                if _h_visible:
                    emit = self._latex_buf.feed(_h_visible)
                    if emit:
                        wire.append(emit)
        # Flush any buffered LaTeX pending at end of stream
        _latex_tail = self._latex_buf.flush()
        if _latex_tail:
            wire.append(_latex_tail)
        return wire, full


def extract_reprompt_chunk_content(chunk) -> tuple[str, bool]:
    """Extract text content from a reprompt chunk. Returns (content, skip).

    skip=True means the chunk is a pure thinking token and should be discarded.
    """
    if isinstance(chunk, dict) and "message" in chunk:
        if chunk["message"].get("thinking", ""):
            return "", True
        return chunk["message"].get("content", ""), False
    if isinstance(chunk, dict):
        return chunk.get("content", chunk.get("response", "")) or "", False  # type: ignore[return-value]
    if isinstance(chunk, str):
        return chunk, False
    return "", False


def filter_reprompt_think_tags(content: str, in_think: bool) -> tuple[str, bool]:
    """Strip <think>…</think> tags inline, updating in_think state. Returns (filtered_content, in_think).

    B124: a chunk that carries a COMPLETE ``<think>…</think>`` plus trailing
    visible text must keep that visible text. The close tag is matched on the
    ORIGINAL chunk (previously it was searched in the already-truncated
    pre-``<think>`` slice, so the text after ``</think>`` was discarded and
    in_think wrongly stayed True — the visible reply was lost).
    """
    before = content.split('<think>')[0] if '<think>' in content else ""
    if '<think>' in content:
        in_think = True
    if '</think>' in content:
        # visible = text before this chunk's <think> (if any) + text after </think>
        return before + content.split('</think>')[-1], False
    if in_think:
        return "", True
    return content, in_think
