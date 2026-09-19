"""
────────────────────────────────────
Server Nexe
Author: Jordi Goy
Location: core/rag/source.py
Description: What the turn needs from a retrieval source, as a Protocol.

ADR-008. The shape of the contract is the one NAT's `BaseRAGSource` already
uses, rewritten here against this repo's own vocabulary: no code is imported
from there.

Two methods, not four. A port is defined by what the caller needs, and the
only thing the turn asks a source for is a search. Ingest goes through
another door entirely (`core/ingest/` + `MemoryAPI.remember`), so putting
`add_document()` here would mean three sources implementing a stub on day
one — exactly the kind of dead surface ADR-002 had to go and bury. The day a
source really ingests (E3, the document module), the port grows with a real
implementation behind it.

A `Protocol`, not an ABC, because that is what this repo's ports are:
`core/memory_facts/port.py::MemoryPort`, `memory/embeddings/core/interfaces.py`
(`AsyncEncoder`, `CacheProvider`) and `memory/embeddings/core/vectorstore.py`
(`VectorStore`). A source satisfies it by shape and stays free to inherit
whatever it likes.

`memory` travels as an ARGUMENT and never as an import: that is what keeps
`core/rag/` from reaching into `memory/`, and keeps the coupling visible to
the layering gate instead of hidden behind a deferred import (the gate does
not see those — it says so itself: "96 deferred cross-package imports, real
coupling the freeze does not see").

www.jgoy.net · https://server-nexe.org
────────────────────────────────────
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, List, Optional, Protocol, runtime_checkable


@dataclass(frozen=True)
class RAGQuery:
    """One turn's question, prepared once and asked of every source.

    `text` arrives ALREADY NFKC-normalized: the orchestrator normalizes once
    to mirror the ingest path (`MemoryService.remember()`), and a source must
    not do it again. `embedding` is the query vector precomputed once and
    shared across sources (MC-001) — `None` when the precompute failed, which
    is not an error: each source then lets the store embed the text itself.

    `threshold_override` applies the SAME threshold to every source (the UI's
    per-turn slider, also a CLI flag); `None` keeps each source's tuned one.
    """

    text: str
    lang: str = "en"
    embedding: Optional[List[float]] = None
    threshold_override: Optional[float] = None


@runtime_checkable
class RAGSource(Protocol):
    """A place the turn can retrieve context from."""

    def name(self) -> str:
        """The source's id. For a collection-backed source it IS the
        collection name: the UI destructures `[collection, score]` out of
        `rag_items` (`nexe-stats.js:132`) and the CLI prints the same, so the
        two are deliberately the same string."""
        ...

    async def search(self, memory: Any, query: RAGQuery) -> List[Any]:
        """Retrieve for this turn, or return [] — never raise.

        Retrieval that fails is a turn WITHOUT context, never a failed turn
        (#899), and `memory/` is degradable by decision (#888, see
        `core/memory_access.py`). A source that raises would put the chat's
        availability in the hands of its own store, which is the thing
        `RAGModule.search` does and the reason it never reached the turn.
        """
        ...
