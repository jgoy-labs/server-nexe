"""
────────────────────────────────────
Server Nexe — test
Author: Jordi Goy
Location: tests/core/rag/test_sources_land_in_their_own_section.py
Description: ADR-008 D4 — a retrieved hit is filed into one of the three
             labelled sections BY ITS `collection` attribute, and a hit
             whose collection is not a system one lands in the knowledge
             drawer.

             `_format_results` (`core/endpoints/chat_rag.py`) buckets with
             `getattr(r, "collection", None)`. Before E2 a hit WITHOUT the
             attribute (the retired `SearchHit`, or anything a registered
             source returns) moved there in silence, and this file pinned
             that mute case as the alarm. E2 sealed it upstream: the
             orchestrator stamps `collection = source.name()` on every hit
             that lacks one (`_stamp_collection`), so by the time the
             formatter runs every hit names its source. What stays pinned
             here is the rule the formatter still applies — an unknown name
             is knowledge, never a guess at docs or memory — and the stamp
             itself.

www.jgoy.net · https://server-nexe.org
────────────────────────────────────
"""

from dataclasses import dataclass, field

from core.endpoints.chat_rag import _RAG_CONTEXT_LABELS, _format_results, _stamp_collection
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
    """A hit with no `collection`, like the retired `SearchHit` or a
    registered source's own objects."""

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


def test_a_hit_from_an_unknown_source_is_filed_as_knowledge():
    """ADR-008 D4 after E2: an unknown source name is knowledge.

    The stamp gives a registered source's hit its source name
    (`plugin_notes`), which is not a system collection. The formatter must
    file it as knowledge — not in docs or memory, whose labels the system
    prompt tells the model to read as the manual and as the user's memory.
    """
    labels = _RAG_CONTEXT_LABELS["ca"]
    out = _format_results([_Hit("plugin_notes", "un fet d'un plugin")], "ca")

    assert f"[{labels['knowledge']}]" in out
    assert f"[{labels['docs']}]" not in out
    assert f"[{labels['memory']}]" not in out


def test_a_hit_without_a_collection_is_stamped_with_its_source_name():
    """The seal itself (E2): the hit that used to reach the formatter with no
    `collection` now reaches it with the source's name, on a COPY — the
    source's object is left as it was."""
    original = _HitWithoutCollection("un fet sense col·leccio")
    [stamped] = _stamp_collection([original], "plugin_notes")

    assert stamped.collection == "plugin_notes"
    assert stamped.text == "un fet sense col·leccio"
    assert not hasattr(original, "collection")


def test_a_hit_that_names_its_collection_is_passed_through_untouched():
    hit = _Hit(MEMORY_COLLECTION, "el gat es diu Mite")
    [out] = _stamp_collection([hit], "some_other_source")

    assert out is hit
    assert out.collection == MEMORY_COLLECTION


def test_a_frozen_hit_is_stamped_through_a_read_only_view():
    """A frozen hit cannot take the attribute, even on a copy. It must still
    come out named, with every other field readable, and the formatter must
    still file it by that name."""

    @dataclass(frozen=True)
    class _FrozenHit:
        text: str
        score: float = 0.5
        metadata: dict = field(default_factory=dict)

    original = _FrozenHit("un fet congelat")
    [stamped] = _stamp_collection([original], DOCS_COLLECTION)

    assert stamped.collection == DOCS_COLLECTION
    assert stamped.text == "un fet congelat" and stamped.score == 0.5
    labels = _RAG_CONTEXT_LABELS["ca"]
    assert f"[{labels['docs']}]" in _format_results([stamped], "ca")
