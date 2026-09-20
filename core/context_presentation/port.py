"""
────────────────────────────────────
Server Nexe
Author: Jordi Goy
Location: core/context_presentation/port.py
Description: How retrieved context presents itself to the model, as a Protocol.

ADR-007 §5: the core defines the port, the organ brings the adapter. This is
the other half of ADR-008, which said it out loud and deferred it — "a source
plugs in to RETRIEVE, but not to PRESENT itself". Retrieval got its port
(`core/rag/source.py`); this is presentation's.

A `Protocol`, not an ABC, because that is what this repo's ports are
(`core/rag/source.py`, `core/memory_facts/port.py`, `AsyncEncoder`,
`VectorStore`). One method, not three: there is exactly ONE caller — the
`budget` step, at two doors — and a port is defined by what the caller needs.
The day a source wants a voice of its own (E3), it grows with a real
implementation behind it, not with stubs on day one.

**It returns DATA, and receives a SHAPE.** The presenter chooses what to say;
the CORE chooses where it goes. Two fields and not one because they sit on
different sides of the B030 delimiters, and that position is a security
decision the core keeps: `legend` is the server introducing the block, and
`closing` is the server saying what to do with it once read.

**What this port never sees: the wrapper.** No `[CONTEXT <nonce>]`, no security
notice, no acknowledgement turn. A plugin will be able to change how context
PRESENTS itself; never how it is DELIMITED. That asymmetry is the whole reason
this is a port returning strings instead of a hook assembling messages.

**What it does not receive, and why:** which collections answered. The default
presenter would not use it, and it would be dead surface on day one — exactly
what ADR-002 had to go and bury. It arrives with E3, with a caller behind it.

Synchronous on purpose: this is text selection, not I/O. `MemoryPort` and
`RAGSource.search` are async because they reach a store; there is one place to
change if that ever stops being true here.

www.jgoy.net · https://server-nexe.org
────────────────────────────────────
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional, Protocol, runtime_checkable


@dataclass(frozen=True)
class ContextShape:
    """What the turn found, without what it found.

    The presenter is told the SHAPE of this turn's context — is there a
    document, is there retrieval — and never the content. Framing prose that
    varied with the retrieved text would be prose a document could steer,
    which is the thing B030 exists to prevent.

    `lang` is the turn's reply language (`ctx.lang`). `None` means "no turn
    language in hand", and the default presenter falls back to the server's
    `NEXE_LANG` — the behaviour #1072 settled, kept here deliberately rather
    than reinvented.

    `has_image` (#1081) does not carry a delimited block the way `has_document`
    and `has_rag` do — the image itself never enters the text prompt, it
    travels to the engine as `images=[...]`. It is here because the ONE
    sentence that says so is still server scaffolding that must not speak with
    the user's authority (B030 layer 2d applies to trusted prose too, not only
    untrusted data) — see `ContextFraming.note`.
    """

    lang: Optional[str] = None
    has_document: bool = False
    has_rag: bool = False
    has_image: bool = False


@dataclass(frozen=True)
class ContextFraming:
    """The server's own trusted prose around a block of retrieved context.

    Both fields go OUTSIDE the nonce'd delimiters and inside the same user
    turn, one on each side:

        legend  ·  [CONTEXT n] notice + data [FI CONTEXT n]  ·  closing

    `closing` is where the sentence that cites the document belongs: it says
    "del bloc de context ANTERIOR", and that word is a position. Empty strings
    mean "say nothing here", which is the normal case for a turn that has one
    of the two kinds of context and not the other.

    `note` is neither: it is freestanding trusted prose with no delimited
    block to sit before or after (#1081, the image note). It still travels in
    its own turn, never glued to the user's message — the same B030 layer 2d
    rule, applied to a piece that has no data to wrap.
    """

    legend: str = ""
    closing: str = ""
    note: str = ""


@runtime_checkable
class ContextPresenter(Protocol):
    """Chooses the words that frame retrieved context for one turn."""

    def frame(self, shape: ContextShape) -> ContextFraming:
        """The prose for this turn's context, or empty strings.

        Never raises: framing that fails is a turn with a plainer prompt, not
        a failed turn — the same rule `RAGSource.search` follows for its own
        half (#899). A presenter that raised would put the chat's availability
        in the hands of whoever wrote the wording.
        """
        ...
