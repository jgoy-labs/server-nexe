"""
────────────────────────────────────
Server Nexe
Author: Jordi Goy
Location: core/turn/text/captions.py
Description: A caption naming the source, dropped when all it held was the
             prompt's section labels (#1124).

Seen live 02/10 with Qwen3.5-9B on MLX: "Sí, el teu nom és Jordi.\n\nFont:".
The model wrote "Font: [MEMORIA DE L'USUARI]" and the label went (#1086),
leaving the caption. The source belongs to the badge under the message, never
to its text (Jordi, 02/10).

A caption starts with a source word and its colon — "Font:", "**Fonts:**",
"- Fuente:", "Sources:" — at the start of a line, after a space or after "(".
What follows it is its REGION while it is only labels, list and emphasis
marks, punctuation, "i"/"y"/"and", line breaks and memory tags. The region is
dropped when it held at least one label and ends where the reply does, where
a line break is followed by real text, or at the ")" that closes it. When real
text follows on the caption's own line ("Font: m'ho vas dir tu", "Fonts:" over
a list the user asked for), nothing is dropped. Memory tags inside a dropped
region are kept: the web client reads them for its badges.

ONE implementation for the live stream and the stored reply:
`clean_model_text` runs the whole reply through the same filter, so what was
shown and what is stored cannot drift apart. Fed one character at a time or
all at once, it gives the same text.

www.jgoy.net · https://server-nexe.org
────────────────────────────────────
"""
from __future__ import annotations

import re
from collections import deque

from core.turn.text.clean import CTX_HEADERS_RE

_WORDS = ("font", "fonts", "fuente", "fuentes", "source", "sources")
_CONNECTORS = ("i", "y", "and")
_MARKERS = "-*+>•"
_FILLER = frozenset(" \t\r*_.,;:&/>+•·–—-«»\"'`")
# A numbered list item or a heading mark: "1.", "2)", "###".
_ITEM_RE = re.compile(r"\d{1,3}[.)]|#{1,6}(?=[ \t])")
# The same while it is still being written.
_ITEM_SO_FAR = re.compile(r"\d{1,3}|#{1,6}")
# A memory tag inside a region is not text, and it is not dropped either.
_MEMORY_TAG_RE = re.compile(r"\[(?:MEM_[A-Z_]+|MEMORIA|OLVIDA|OBLIT|FORGET):[^\]\n]{0,260}\]", re.IGNORECASE)
# Longer than this, a region is prose: released.
_MAX = 400


def _skip(held: str, i: int, chars: str) -> int:
    while i < len(held) and held[i] in chars:
        i += 1
    return i


def _lead_end(held: str, kind: str) -> int:
    """Past what may come before the source word: the "(" of a bracketed
    caption, or a line's indent and list or quote mark."""
    if kind == "paren":
        return _skip(held, 1, " \t")
    if kind != "line":
        return 0
    i = _skip(held, 0, " \t")
    item = _ITEM_RE.match(held, i)
    if item:
        return _skip(held, item.end(), " \t")
    if i < len(held) and held[i] in _MARKERS:
        i = _skip(held, i + 1, " \t")
    return i


def _head_end(held: str, kind: str):
    """Where the caption's head (source word + colon) ends in `held`: an index,
    "maybe" while it still can become one, or None when it cannot."""
    if kind == "line" and _ITEM_SO_FAR.fullmatch(held.lstrip(" \t")):
        return "maybe"
    i = _skip(held, _lead_end(held, kind), "*_")
    j = i
    while j < len(held) and held[j].isalpha():
        j += 1
    word = held[i:j].lower()
    if j == len(held):
        return "maybe" if any(w.startswith(word) for w in _WORDS) else None
    if word not in _WORDS:
        return None
    j = _skip(held, j, " \t*_")
    if j == len(held):
        return "maybe"
    return j + 1 if held[j] == ":" else None


def _bracket(held: str, pos: int, final: bool):
    """At a "[": a label, a memory tag, "open" while it may still become one,
    or None (it is text)."""
    m = CTX_HEADERS_RE.match(held, pos)
    if m:
        return "label", m.end()
    m = _MEMORY_TAG_RE.match(held, pos)
    if m:
        return "tag", m.end()
    if not final and "]" not in held[pos:] and len(held) - pos <= 280:
        return "open", pos
    return None, pos


def _connector(held: str, pos: int, final: bool):
    """At a letter: "i"/"y"/"and" between labels, "open" while the word may
    still become one, or None (it is text)."""
    j = pos
    while j < len(held) and held[j].isalpha():
        j += 1
    word = held[pos:j].lower()
    if j == len(held) and not final and any(c.startswith(word) for c in _CONNECTORS):
        return "open", pos
    if word in _CONNECTORS:
        return "skip", j
    return None, pos


def _token(held: str, pos: int, final: bool):
    ch = held[pos]
    if ch in _FILLER:
        return "skip", pos + 1
    item = _ITEM_RE.match(held, pos)
    if item:
        return "skip", item.end()
    if not final and _ITEM_SO_FAR.fullmatch(held, pos):
        return "open", pos
    if ch == "[":
        return _bracket(held, pos, final)
    if ch.isalpha():
        return _connector(held, pos, final)
    return None, pos


def _cut_at_text(held: str, kind: str, last_nl, labels: list):
    """Real text after the region: it ended at its last line break, if it had
    one with a label before it."""
    if kind != "paren" and last_nl is not None and any(at < last_nl for at in labels):
        return (last_nl, "".join(m.group() for m in _MEMORY_TAG_RE.finditer(held, 0, last_nl)))
    return "keep"


def _at_end(held: str, kind: str, labels: list, tags: list, final: bool):
    """The region reached the end of what is held."""
    if not final:
        return "open"
    if kind == "paren" or not labels:
        return "keep"
    return (len(held), "".join(tags))


def _region(held: str, start: int, kind: str, final: bool):
    """What to do with a caption whose head ends at `start`.

    Returns "open" (only filler so far: wait), "keep" (real text on the
    caption's own line, or no label in it), or `(cut, kept)`: drop `held[:cut]`
    but for the memory tags in `kept`.
    """
    labels: list[int] = []
    tags: list[str] = []
    last_nl = None
    pos = start
    while pos < len(held):
        ch = held[pos]
        if ch == "\n":
            if kind == "paren":
                return "keep"
            last_nl = pos
            pos += 1
            continue
        if ch == ")" and kind == "paren":
            return (pos + 1, "".join(tags)) if labels else "keep"
        what, end = _token(held, pos, final)
        if what == "open":
            return "open"
        if what is None:
            return _cut_at_text(held, kind, last_nl, labels)
        if what == "label":
            labels.append(pos)
        elif what == "tag":
            tags.append(held[pos:end])
        pos = end
    return _at_end(held, kind, labels, tags, final)


class CaptionFilter:
    """Drops source captions that only held labels, from a stream or a whole text."""

    def __init__(self) -> None:
        self._held = ""
        self._kind = ""
        self._head: int | None = None
        self._line_start = True
        self._after_space = False
        # What was dropped, in order.
        self.dropped: list[str] = []

    def feed(self, text: str) -> str:
        return self._run(deque(text), final=False)

    def flush(self) -> str:
        if not self._held:
            return ""
        return self._run(deque(), final=True)

    def _run(self, todo: deque, *, final: bool) -> str:
        out: list[str] = []
        while True:
            if self._held:
                verdict = self._decide(final=final and not todo)
                if verdict is not None:
                    emit, again = verdict
                    out.append(emit)
                    todo.extendleft(reversed(again))
                    continue
                if not todo:
                    break
                self._held += todo.popleft()
                continue
            if not todo:
                break
            ch = todo.popleft()
            kind = "paren" if ch == "(" else "line" if self._line_start else "space" if self._after_space else ""
            self._line_start = ch == "\n"
            self._after_space = ch in " \t"
            if kind and ch != "\n":
                self._held, self._kind, self._head = ch, kind, None
            else:
                out.append(ch)
        return "".join(out)

    def _decide(self, *, final: bool):
        """None to keep holding, or (text out now, text to read again)."""
        held = self._held
        if self._head is None:
            end = _head_end(held, self._kind)
            if end == "maybe" and not final and len(held) < _MAX:
                return None
            if not isinstance(end, int):
                return self._release(held)
            self._head = end
        verdict = _region(held, self._head, self._kind, final)
        if verdict == "open" and len(held) < _MAX:
            return None
        if not isinstance(verdict, tuple):
            return self._release(held)
        cut, kept = verdict
        self.dropped.append(held[:cut])
        self._reset()
        self._line_start, self._after_space = False, False
        return kept, held[cut:]

    def _release(self, held: str):
        """The first character goes out as it is; the rest is read again, so a
        caption that starts inside it is still found."""
        self._reset()
        first = held[0]
        self._line_start = first == "\n"
        self._after_space = first in " \t"
        return first, held[1:]

    def _reset(self) -> None:
        self._held, self._kind, self._head = "", "", None


def drop_source_captions(text: str) -> str:
    """The whole reply through the stream's filter (#1124)."""
    f = CaptionFilter()
    return f.feed(text) + f.flush()
