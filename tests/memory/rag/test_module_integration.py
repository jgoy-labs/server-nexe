"""
────────────────────────────────────
Server Nexe
Author: Jordi Goy
Location: memory/rag/tests/test_module_integration.py
Description: RAGModule as a facade over the chat's sources (ADR-008 E2).

The module used to own a `PersonalityRAG` and search it; it now lists the
sources the turn uses (system collections + registry) and searches them the
way the turn does, `source_for(name).search(memory, RAGQuery(...))`. The
store is faked here (a MemoryAPI double); the sources are the real ones.

www.jgoy.net · https://server-nexe.org
────────────────────────────────────
"""

from unittest.mock import AsyncMock, MagicMock

import pytest

from core.memory_access import (
  DOCS_COLLECTION,
  KNOWLEDGE_COLLECTION,
  MEMORY_COLLECTION,
  SYSTEM_COLLECTIONS,
)
from core.rag.collections import DOCS_SOURCE, KNOWLEDGE_SOURCE
from core.rag.registry import clear_registered_sources, register_source
from memory.memory.api.models import SearchResult
from memory.rag.module import RAGModule


class _RegisteredSource:
  def __init__(self, name="plugin_notes", hits=None):
    self._name = name
    self._hits = hits if hits is not None else []
    self.queries = []

  def name(self):
    return self._name

  async def search(self, memory, query):
    self.queries.append(query)
    return self._hits


def _memory(results=None):
  api = MagicMock()
  api.collection_exists = AsyncMock(return_value=True)
  api.search = AsyncMock(return_value=results if results is not None else [])
  return api


@pytest.fixture
def clean_rag_module():
  """
  Fixture to create a clean RAGModule instance.

  Resets singleton (and the source registry) for each test.
  """
  RAGModule._instance = None
  RAGModule._initialized = False
  clear_registered_sources()

  yield RAGModule.get_instance()

  RAGModule._instance = None
  RAGModule._initialized = False
  clear_registered_sources()


@pytest.fixture
def fake_store(monkeypatch):
  """The MemoryAPI the module's search() obtains, faked."""
  api = _memory([
    SearchResult(id="1", score=0.9, collection=DOCS_COLLECTION, text="first"),
    SearchResult(id="2", score=0.8, collection=DOCS_COLLECTION, text="second"),
    SearchResult(id="3", score=0.7, collection=DOCS_COLLECTION, text="third"),
  ])
  monkeypatch.setattr("memory.memory.api.v1.get_memory_api", AsyncMock(return_value=api))
  return api


@pytest.mark.asyncio
async def test_module_initialize_needs_no_sources_of_its_own(clean_rag_module):
  """
  initialize() loads nothing (ADR-008 E2): the module owns no source, and
  once initialized it lists the three system collections.
  """
  module = clean_rag_module

  assert not module._initialized
  assert not hasattr(module, "_sources"), "the module must not keep its own sources again"

  result = await module.initialize()

  assert result is True
  assert module._initialized
  assert module.get_info()["sources"] == list(SYSTEM_COLLECTIONS)


@pytest.mark.asyncio
async def test_module_initialize_idempotent(clean_rag_module):
  """
  Test that initialize() is idempotent (no error if already initialized).
  """
  module = clean_rag_module

  result1 = await module.initialize()
  assert result1 is True

  result2 = await module.initialize()
  assert result2 is True

  assert module._initialized


@pytest.mark.asyncio
async def test_module_search_e2e(clean_rag_module, fake_store):
  """
  search() asks the real system source with the MemoryAPI, with that
  source's own parameters.
  """
  module = clean_rag_module
  await module.initialize()

  results = await module.search("programming language syntax", source=DOCS_COLLECTION)

  assert [r.text for r in results] == ["first", "second", "third"]
  assert module._stats["searches_performed"] == 1
  kwargs = fake_store.search.await_args.kwargs
  assert kwargs["collection"] == DOCS_COLLECTION
  assert kwargs["top_k"] == DOCS_SOURCE.top_k
  assert kwargs["threshold"] == DOCS_SOURCE.threshold


@pytest.mark.asyncio
async def test_module_search_goes_through_source_for(clean_rag_module, fake_store):
  """
  The same door as the chat: a REGISTERED source is asked, and the store is
  not searched for it (the registered source answers for its own name).
  """
  module = clean_rag_module
  await module.initialize()
  src = _RegisteredSource(hits=["hit"])
  register_source(src)

  results = await module.search("  café  ", source="plugin_notes", lang="ca")

  assert results == ["hit"]
  assert len(src.queries) == 1
  assert src.queries[0].lang == "ca"
  fake_store.search.assert_not_awaited()


@pytest.mark.asyncio
async def test_module_search_normalizes_like_the_turn(clean_rag_module, fake_store):
  """
  NFKC, like `build_rag_context` and the ingest path: the full-width query
  reaches the store as its plain form.
  """
  module = clean_rag_module
  await module.initialize()

  await module.search("ｃａｆé", source=KNOWLEDGE_COLLECTION, lang="en")

  kwargs = fake_store.search.await_args.kwargs
  assert kwargs["query"] == "café"
  assert kwargs["filter_metadata"] == {"lang": "en"}
  assert KNOWLEDGE_SOURCE.filter_by_lang


@pytest.mark.asyncio
async def test_module_search_not_initialized(clean_rag_module):
  """
  Test that search() errors if not initialized.
  """
  module = clean_rag_module

  with pytest.raises(RuntimeError, match="not initialized"):
    await module.search("test", source=DOCS_COLLECTION)


@pytest.mark.asyncio
async def test_module_invalid_source(clean_rag_module, fake_store):
  """
  An unknown source is an error before anything is searched.
  """
  module = clean_rag_module
  await module.initialize()

  with pytest.raises(ValueError, match="Unknown RAG source"):
    await module.search("test", source="invalid_source")

  fake_store.search.assert_not_awaited()
  assert module._stats["searches_performed"] == 0


@pytest.mark.asyncio
async def test_module_get_source(clean_rag_module):
  """
  get_source() returns what source_for() returns: the system source itself.
  """
  module = clean_rag_module
  await module.initialize()

  assert module.get_source(DOCS_COLLECTION) is DOCS_SOURCE


@pytest.mark.asyncio
async def test_module_get_source_unknown_raises(clean_rag_module):
  """
  source_for() never refuses (it builds #896's generic fallback), so the
  module must: a typo is an error, not a search of a phantom collection.
  """
  module = clean_rag_module

  with pytest.raises(ValueError, match="Unknown RAG source: nope"):
    module.get_source("nope")


@pytest.mark.asyncio
async def test_module_list_sources(clean_rag_module):
  """
  list_sources() = system collections ∪ registered names, system first.
  """
  module = clean_rag_module

  assert module.list_sources() == list(SYSTEM_COLLECTIONS)

  register_source(_RegisteredSource("plugin_notes"))
  sources = module.list_sources()

  assert sources == [*SYSTEM_COLLECTIONS, "plugin_notes"]
  assert module.get_source("plugin_notes").name() == "plugin_notes"
  assert {DOCS_COLLECTION, KNOWLEDGE_COLLECTION, MEMORY_COLLECTION} <= set(sources)


@pytest.mark.asyncio
async def test_module_get_info(clean_rag_module):
  """
  Test get_info() returns correct metadata.
  """
  module = clean_rag_module
  assert module.get_info()["sources"] == []  # nothing reported before init

  await module.initialize()

  info = module.get_info()

  assert info["name"] == "rag"
  assert "version" in info
  assert info["initialized"] is True
  assert info["sources"] == list(SYSTEM_COLLECTIONS)
  assert info["stats"] == {"searches_performed": 0}


@pytest.mark.asyncio
async def test_module_get_health(clean_rag_module):
  """
  Test get_health() returns correct status.
  """
  module = clean_rag_module
  await module.initialize()

  health = module.get_health()

  assert "status" in health
  assert health["status"] in ["healthy", "degraded", "unhealthy"]
  assert "checks" in health
  assert "metadata" in health

  check_names = [c["name"] for c in health["checks"]]
  assert "rag_sources" in check_names


@pytest.mark.asyncio
async def test_module_stats_tracking(clean_rag_module, fake_store):
  """
  Test that stats are tracked correctly.
  """
  module = clean_rag_module
  await module.initialize()

  assert module._stats["searches_performed"] == 0

  for i in range(2):
    await module.search(f"query {i}", source=DOCS_COLLECTION)

  assert module._stats["searches_performed"] == 2


@pytest.mark.asyncio
async def test_module_top_k_caps_results(clean_rag_module, fake_store):
  """
  top_k caps what the source returned; it cannot widen the source's own
  tuned top_k (that is what the store is asked for).
  """
  module = clean_rag_module
  await module.initialize()

  results = await module.search("programming language", source=DOCS_COLLECTION, top_k=2)

  assert [r.text for r in results] == ["first", "second"]
  assert fake_store.search.await_args.kwargs["top_k"] == DOCS_SOURCE.top_k
