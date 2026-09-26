"""A registered source is asked by the turn, and the toggle can select it.

ADR-008 E1b. `test_registry.py` proves the registry answers; this proves the
ORCHESTRATOR uses it — the part that would have silently done nothing if
`_discover_collection_names` had not been unioned with the registered names.

Four cases, all through `build_rag_context` (the real entry both doors use):
  - a registered source is discovered and asked WITHOUT existing as a
    collection in the store (E3's document module is exactly this);
  - it survives a discovery failure;
  - `rag_collections` selects it by name, like any other source;
  - D6 survives: an empty toggle still means "search nowhere", and a
    registration does not sneak past an explicit opt-out.
"""

from unittest.mock import AsyncMock, MagicMock

import pytest

from core.endpoints.chat_rag import (
    _RAG_CONTEXT_LABELS,
    _discover_collection_names,
    build_rag_context,
)
from core.memory_access import DOCS_COLLECTION, KNOWLEDGE_COLLECTION, MEMORY_COLLECTION
from core.rag.registry import register_source

_ANSWER = "the registered source answered"


class _Info:
    def __init__(self, name):
        self.name = name


class _Hit:
    def __init__(self, text, score=0.9, collection="plugin_notes"):
        self.text = text
        self.score = score
        self.collection = collection
        self.metadata = {}


class _RegisteredSource:
    """Not collection-backed: it never touches `memory`."""

    def __init__(self, name="plugin_notes", hits=None):
        self._name = name
        self._hits = hits if hits is not None else [_Hit(_ANSWER)]
        self.asked = 0

    def name(self) -> str:
        return self._name

    async def search(self, memory, query):
        self.asked += 1
        return self._hits


def _memory(collections=(DOCS_COLLECTION, KNOWLEDGE_COLLECTION, MEMORY_COLLECTION)):
    api = MagicMock()
    api.list_collections = AsyncMock(return_value=[_Info(n) for n in collections])
    api.embed_query = AsyncMock(return_value=[0.1, 0.2])
    api.collection_exists = AsyncMock(return_value=True)
    api.search = AsyncMock(return_value=[])
    return api


def _install(monkeypatch, api):
    monkeypatch.setattr("memory.memory.api.v1.get_memory_api", AsyncMock(return_value=api))


@pytest.mark.asyncio
async def test_a_registered_source_is_discovered_without_being_a_collection():
    register_source(_RegisteredSource())
    names = await _discover_collection_names(_memory())
    assert "plugin_notes" in names


@pytest.mark.asyncio
async def test_it_survives_a_discovery_failure():
    """The store hiccups and we fall back to the system defaults — a
    registered source must not disappear with it."""
    register_source(_RegisteredSource())
    api = _memory()
    api.list_collections = AsyncMock(side_effect=RuntimeError("store down"))
    names = await _discover_collection_names(api)
    assert "plugin_notes" in names
    assert MEMORY_COLLECTION in names, "the defaults are still there"


@pytest.mark.asyncio
async def test_the_turn_asks_it_and_its_text_reaches_the_context(monkeypatch):
    src = _RegisteredSource()
    register_source(src)
    _install(monkeypatch, _memory())
    context, rag_items = await build_rag_context(
        "anything", app_state=None, server_lang="en",
    )
    assert src.asked == 1
    assert _ANSWER in context
    assert any(name == "plugin_notes" for name, _score in rag_items)


@pytest.mark.asyncio
async def test_the_toggle_can_select_it_by_name(monkeypatch):
    src = _RegisteredSource()
    register_source(src)
    _install(monkeypatch, _memory())
    context, _ = await build_rag_context(
        "anything", app_state=None, server_lang="en", collections=["plugin_notes"],
    )
    assert src.asked == 1
    assert _ANSWER in context


class _HitWithoutCollection:
    """What a source that is not collection-backed can easily return."""

    def __init__(self, text):
        self.text = text
        self.score = 0.9
        self.metadata = {}


@pytest.mark.asyncio
async def test_a_registered_hit_without_collection_is_stamped_with_its_source(monkeypatch):
    """The D4 alarm, sealed at E2.

    Until E1b nobody outside this package could produce a hit without a
    `collection` (`SearchResult.collection` is required); the registry made it
    reachable, and this test pinned the mute result: text filed under the
    knowledge label and `?` in the stats. ADR-008 §D4 said it changes at E2,
    and it has: the orchestrator stamps `collection = source.name()` on a hit
    that lacks one, so the stats name the source it came from.

    The SECTION does not change, on purpose: `plugin_notes` is not one of the
    system collections, so it is still filed as knowledge — the formatter
    must not guess a drawer from an unknown name. And the source's own object
    is not mutated: the stamp goes on a copy.
    """
    hit = _HitWithoutCollection(_ANSWER)
    register_source(_RegisteredSource(hits=[hit]))
    _install(monkeypatch, _memory())
    context, rag_items = await build_rag_context(
        "anything", app_state=None, server_lang="en",
    )
    labels = _RAG_CONTEXT_LABELS["en"]
    assert _ANSWER in context
    assert labels["knowledge"] in context, "an unknown source name is still filed as knowledge"
    assert labels["docs"] not in context and labels["memory"] not in context
    assert rag_items == [("plugin_notes", 0.9)], "the stats name the source, not '?'"
    assert not hasattr(hit, "collection"), "the source's own hit must not be mutated"


@pytest.mark.asyncio
async def test_an_empty_toggle_still_means_nowhere_d6(monkeypatch):
    src = _RegisteredSource()
    register_source(src)
    _install(monkeypatch, _memory())
    context, rag_items = await build_rag_context(
        "anything", app_state=None, server_lang="en", collections=[],
    )
    assert src.asked == 0, "an explicit opt-out must not be widened by a registration"
    assert context == "" and rag_items == []
