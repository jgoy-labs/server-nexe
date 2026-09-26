"""The source registry: a fourth source can exist, and cannot hijack a system one.

ADR-008 E1b. Until this, `source_for` read a literal dict and built a generic
source for anything else, so a plugin's collection was searchable but could
never bring its own tuned parameters — and nothing outside `core/rag/` could
add a source at all.

Every test here asserts BEHAVIOUR reachable from the turn (`source_for`,
`_discover_collection_names`), not the shape of the registry's internals.
"""

import pytest

from core.memory_access import KNOWLEDGE_COLLECTION, MEMORY_COLLECTION
from core.rag.collections import RAG_KNOWLEDGE_THRESHOLD, source_for
from core.rag.registry import (
    register_source,
    registered_names,
    unregister_source,
)
from core.rag.source import RAGQuery, RAGSource


class _FakeSource:
    """A source that is not collection-backed, like E3's document module."""

    def __init__(self, name: str, hits=None):
        self._name = name
        self._hits = hits or []
        self.asked = 0

    def name(self) -> str:
        return self._name

    async def search(self, memory, query: RAGQuery):
        self.asked += 1
        return self._hits


def test_a_registered_source_answers_for_its_own_name():
    src = _FakeSource("plugin_notes")
    register_source(src)
    assert source_for("plugin_notes") is src


def test_it_satisfies_the_port_by_shape():
    # `RAGSource` is a runtime_checkable Protocol: a source inherits nothing.
    assert isinstance(_FakeSource("x"), RAGSource)


def test_without_a_registration_the_896_fallback_still_searches_the_collection():
    # The behaviour a plugin's collection has today must not disappear.
    src = source_for("some_plugin_collection")
    assert src.name() == "some_plugin_collection"
    assert src.threshold == RAG_KNOWLEDGE_THRESHOLD
    assert src.top_k == 3
    assert src.filter_by_lang is False


def test_a_registered_source_brings_its_own_parameters_instead_of_the_middle_ground():
    class _Tuned(_FakeSource):
        threshold = 0.9
        top_k = 1

    register_source(_Tuned("strict_collection"))
    got = source_for("strict_collection")
    assert got.threshold == 0.9 and got.top_k == 1


@pytest.mark.parametrize("system", [MEMORY_COLLECTION, KNOWLEDGE_COLLECTION])
def test_a_registration_cannot_shadow_a_system_collection(system):
    """The hijack this refusal exists to prevent: a plugin answering for
    `personal_memory` would read the user's memory through a door meant for
    its own collection."""
    with pytest.raises(ValueError, match="system collection"):
        register_source(_FakeSource(system))
    # and the real one still answers
    assert source_for(system).name() == system


def test_the_same_name_cannot_be_registered_twice():
    register_source(_FakeSource("once"))
    with pytest.raises(ValueError, match="already registered"):
        register_source(_FakeSource("once"))


def test_an_empty_name_is_refused():
    with pytest.raises(ValueError, match="non-empty name"):
        register_source(_FakeSource(""))


def test_unregistering_gives_the_name_back_to_the_fallback():
    register_source(_FakeSource("temporary"))
    assert unregister_source("temporary") is True
    assert unregister_source("temporary") is False
    # back to the #896 generic source, not to the fake
    assert source_for("temporary").threshold == RAG_KNOWLEDGE_THRESHOLD


def test_registered_names_are_what_the_orchestrator_unions():
    register_source(_FakeSource("b_source"))
    register_source(_FakeSource("a_source"))
    assert registered_names() == ["a_source", "b_source"]
