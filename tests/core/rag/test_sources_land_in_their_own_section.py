"""
────────────────────────────────────
Server Nexe — test
Author: Jordi Goy
Location: tests/core/rag/test_sources_land_in_their_own_section.py
Description: ADR-008 D4 — a retrieved hit is filed into one of the three
             labelled sections BY ITS `collection` attribute, and a hit
             without one lands in the knowledge drawer WITHOUT ANY ERROR.

             That silence is the point of this file. `_format_results`
             (`core/endpoints/chat_rag.py`) buckets with
             `getattr(r, "collection", None)`, and today every hit has it
             because they come from `MemoryAPI` (`SearchResult.collection`
             is a required field). The day a source returns the RAG module's
             `SearchHit` instead — which has no `collection` field at all —
             the WHOLE context would quietly move under
             [DOCUMENTACIO TECNICA], the system prompt would be citing
             sections that no longer describe what is under them, and not a
             single test would have gone red. So the mute case is pinned
             here, with its name, next to the one that works.

www.jgoy.net · https://server-nexe.org
────────────────────────────────────
"""

from core.endpoints.chat_rag import _RAG_CONTEXT_LABELS, _format_results
from core.memory_access import (
    DOCS_COLLECTION,
    KNOWLEDGE_COLLECTION,
    MEMORY_COLLECTION,
)


class _Hit:
    """A hit shaped like MemoryAPI's `SearchResult`."""

    def __init__(self, collection: str, text: str):
        self.collection = collection
        self.text = text
        self.score = 0.9
        self.metadata = {"source": "provaX"}


class _HitWithoutCollection:
    """A hit shaped like the RAG module's `SearchHit`: no `collection`."""

    def __init__(self, text: str):
        self.text = text
        self.score = 0.9
        self.metadata = {"source": "provaX"}


def test_each_source_lands_in_its_own_labelled_section():
    """One source, one drawer. The labels are not decoration: the system
    prompt (`personality/server.toml`, six keys) tells the model to look for
    them by name, so a hit filed under the wrong one is a hit the model is
    told to read as something else."""
    labels = _RAG_CONTEXT_LABELS["ca"]
    out = _format_results(
        [
            _Hit(DOCS_COLLECTION, "que diu el manual"),
            _Hit(KNOWLEDGE_COLLECTION, "que diu el meu PDF"),
            _Hit(MEMORY_COLLECTION, "el gat es diu Mite"),
        ],
        "ca",
    )

    for key, text in (
        ("docs", "que diu el manual"),
        ("knowledge", "que diu el meu PDF"),
        ("memory", "el gat es diu Mite"),
    ):
        section = f"[{labels[key]}]"
        assert section in out, f"missing section {section}"
        # The text must sit UNDER its own header, not merely somewhere in
        # the context: the drawer is what the model is told to trust.
        after = out.index(section)
        following = out[after:]
        next_header = min(
            (following.index(f"[{labels[k]}]") for k in ("docs", "knowledge", "memory")
             if k != key and f"[{labels[k]}]" in following),
            default=len(following),
        )
        assert text in following[:next_header], (
            f"{text!r} was filed outside [{labels[key]}]"
        )


def test_a_hit_without_a_collection_is_filed_as_knowledge_in_silence():
    """ADR-008 D4, the mute regression, pinned.

    This is NOT the behaviour anyone wants — it is the behaviour there is,
    and it fails silently. If this test ever has to change because a source
    started returning hits without a `collection`, read it as the alarm: give
    `SearchHit` the field (D4) rather than teaching the formatter to guess.
    """
    labels = _RAG_CONTEXT_LABELS["ca"]
    out = _format_results([_HitWithoutCollection("un fet sense col·leccio")], "ca")

    assert f"[{labels['knowledge']}]" in out
    assert f"[{labels['docs']}]" not in out
    assert f"[{labels['memory']}]" not in out
