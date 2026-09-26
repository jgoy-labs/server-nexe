"""
────────────────────────────────────
Server Nexe
Author: Jordi Goy
Location: core/turn/text/tags.py
Description: Bracketed tags the model writes into its answer, dropped from a
             LIVE stream — split across chunks or not.

Two kinds, both copied by the model from what it was given or told:
- memory tags ([MEM_SAVE: …], [MEM_DELETE: …], [MEMORIA: …], [OLVIDA: …] …):
  instructions to the server, never text for the reader;
- section labels ([USER MEMORY], [MEMORIA DE L'USUARI], [CONTEXT a1b2c3d4] …):
  the prompt's own markers, echoed back (#1086; the RAG legend asks the
  model to name its source, and it names it by the label). The same set
  `CTX_HEADERS_RE` strips from the WHOLE reply — one definition.

A door chooses what to drop: /v1 drops both; the web UI drops only the
labels, because its client reads the memory tags to paint the saved/deleted
badges and strips them itself.

www.jgoy.net · https://server-nexe.org
────────────────────────────────────
"""
from __future__ import annotations

import re

from core.turn.text.clean import CTX_HEADERS_RE

# The longest memory tag the extractor accepts: "[MEM_DELETE: " + 250 + "]".
_MAX_TAG = 270
# Every memory tag name the extractor reads, and the ones it strips as
# invented ([MEM_*]).
_MEMORY_NAMES = ("MEM_", "MEMORIA:", "OLVIDA:", "OBLIT:", "FORGET:")
# What a section label can look like while it is still being written:
# uppercase words (accents and apostrophes included), then for [CONTEXT] a
# lowercase hex nonce. Anything else cannot become one — released at once.
_LABEL_SO_FAR = re.compile(r"[A-ZÀ-ÝÇ' ]*(?: [0-9a-f]{0,16})?")


def _may_become_memory_tag(held: str) -> bool:
    body = held[1:].upper()
    return any(name.startswith(body) or body.startswith(name) for name in _MEMORY_NAMES)


def _may_become_label(held: str) -> bool:
    return len(held) <= 48 and _LABEL_SO_FAR.fullmatch(held[1:]) is not None


def _is_memory_tag(tag: str) -> bool:
    """A complete `[…]`: a memory tag if the extractor reads it as one."""
    from core.memory_facts.extract import extract_memory_tags  # deferred, see clean.py

    clean, _facts, _deletes = extract_memory_tags(tag)
    return not clean.strip()


class TagStreamFilter:
    """Drops memory tags and/or section labels from a stream of text.

    Holds a `[` only while what follows can still become a tag it drops;
    releases it the moment it cannot (a newline, another `[`, a character no
    tag has, or too long).
    """

    def __init__(self, *, memory: bool = True, labels: bool = True) -> None:
        self._memory = memory
        self._labels = labels
        self._held = ""
        # What was dropped, in order — a door that still wants to SAY a fact
        # was saved (the CLI) reads it from here instead of from the text.
        self.dropped: list[str] = []

    def _may_become(self, held: str) -> bool:
        return (self._memory and _may_become_memory_tag(held)) or (
            self._labels and _may_become_label(held)
        )

    def _drop(self, tag: str) -> bool:
        return (self._labels and CTX_HEADERS_RE.fullmatch(tag) is not None) or (
            self._memory and _is_memory_tag(tag)
        )

    def feed(self, text: str) -> str:
        out: list[str] = []
        for ch in text:
            if self._held:
                self._held += ch
                if ch == "]":
                    held, self._held = self._held, ""
                    if self._drop(held):
                        self.dropped.append(held)
                    else:
                        out.append(held)
                elif ch in "\n\r[" or len(self._held) > _MAX_TAG or not self._may_become(self._held):
                    released, self._held = self._held, ""
                    if released.endswith("["):
                        out.append(released[:-1])
                        self._held = "["
                    else:
                        out.append(released)
            elif ch == "[":
                self._held = "["
            else:
                out.append(ch)
        return "".join(out)

    def flush(self) -> str:
        released, self._held = self._held, ""
        return released


def MemTagStreamFilter() -> TagStreamFilter:  # noqa: N802 — the name /v1's tests use
    """/v1's filter: memory tags and section labels."""
    return TagStreamFilter(memory=True, labels=True)
