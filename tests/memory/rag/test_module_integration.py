"""
────────────────────────────────────
Server Nexe
Author: Jordi Goy 
Location: memory/rag/tests/test_module_integration.py
Description: No description available.

www.jgoy.net · https://server-nexe.org
────────────────────────────────────
"""

import pytest

from memory.rag.module import RAGModule
from memory.rag_sources.base import (
  AddDocumentRequest,
  SearchRequest
)

@pytest.fixture
def clean_rag_module():
  """
  Fixture to create a clean RAGModule instance.

  Resets singleton for each test.
  """
  RAGModule._instance = None
  RAGModule._initialized = False

  yield RAGModule.get_instance()

  RAGModule._instance = None
  RAGModule._initialized = False

@pytest.mark.asyncio
async def test_module_initialize_loads_personality_rag(clean_rag_module):
  """
  Test that initialize() loads PersonalityRAG correctly.
  """
  module = clean_rag_module

  assert not module._initialized
  assert len(module._sources) == 0

  result = await module.initialize()

  assert result is True
  assert module._initialized
  assert "personality" in module._sources
  assert module._sources["personality"] is not None

  from memory.rag_sources.personality import PersonalityRAG
  assert isinstance(module._sources["personality"], PersonalityRAG)

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
async def test_module_add_document_e2e(clean_rag_module):
  """
  Test add_document() via RAGModule end-to-end.
  """
  module = clean_rag_module
  await module.initialize()

  request = AddDocumentRequest(
    text="Test document about Python programming language",
    metadata={"source": "test"}
  )

  doc_id = await module.add_document(request)

  assert doc_id is not None
  assert doc_id.startswith("personality-")
  assert module._stats["documents_added"] == 1

@pytest.mark.asyncio
async def test_module_search_e2e(clean_rag_module):
  """
  Test search() via RAGModule end-to-end.
  """
  module = clean_rag_module
  await module.initialize()

  add_request = AddDocumentRequest(
    text="Python is a high-level programming language. "
       "It is known for its clear syntax and readability. "
       "Python is widely used in data science and machine learning.",
    metadata={}
  )
  await module.add_document(add_request)

  search_request = SearchRequest(
    query="programming language syntax",
    top_k=3
  )
  results = await module.search(search_request)

  assert len(results) > 0
  assert module._stats["searches_performed"] == 1

  top_result = results[0]
  assert hasattr(top_result, 'score')
  assert hasattr(top_result, 'text')
  assert hasattr(top_result, 'metadata')
  assert top_result.score > 0.0

@pytest.mark.asyncio
async def test_module_add_document_not_initialized(clean_rag_module):
  """
  Test that add_document() errors if not initialized.
  """
  module = clean_rag_module

  request = AddDocumentRequest(text="Test", metadata={})

  with pytest.raises(RuntimeError, match="not initialized"):
    await module.add_document(request)

@pytest.mark.asyncio
async def test_module_search_not_initialized(clean_rag_module):
  """
  Test that search() errors if not initialized.
  """
  module = clean_rag_module

  request = SearchRequest(query="test", top_k=3)

  with pytest.raises(RuntimeError, match="not initialized"):
    await module.search(request)

@pytest.mark.asyncio
async def test_module_invalid_source(clean_rag_module):
  """
  Test that error occurs if source is unknown.
  """
  module = clean_rag_module
  await module.initialize()

  request = AddDocumentRequest(text="Test", metadata={})

  with pytest.raises(ValueError, match="Unknown RAG source"):
    await module.add_document(request, source="invalid_source")

@pytest.mark.asyncio
async def test_module_get_source(clean_rag_module):
  """
  Test get_source() returns the correct source.
  """
  module = clean_rag_module
  await module.initialize()

  source = module.get_source("personality")

  assert source is not None
  from memory.rag_sources.personality import PersonalityRAG
  assert isinstance(source, PersonalityRAG)

@pytest.mark.asyncio
async def test_module_list_sources(clean_rag_module):
  """
  Test list_sources() returns available sources.
  """
  module = clean_rag_module

  sources_before = module.list_sources()
  assert len(sources_before) == 0

  await module.initialize()
  sources_after = module.list_sources()

  assert len(sources_after) == 1
  assert "personality" in sources_after

@pytest.mark.asyncio
async def test_module_get_info(clean_rag_module):
  """
  Test get_info() returns correct metadata.
  """
  module = clean_rag_module
  await module.initialize()

  info = module.get_info()

  assert info["name"] == "rag"
  assert "version" in info
  assert info["initialized"] is True
  assert "personality" in info["sources"]
  assert "stats" in info
  assert info["stats"]["documents_added"] == 0

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
async def test_module_stats_tracking(clean_rag_module):
  """
  Test that stats are tracked correctly.
  """
  module = clean_rag_module
  await module.initialize()

  assert module._stats["documents_added"] == 0
  assert module._stats["searches_performed"] == 0

  for i in range(3):
    request = AddDocumentRequest(
      text=f"Document {i}",
      metadata={}
    )
    await module.add_document(request)

  assert module._stats["documents_added"] == 3

  for i in range(2):
    request = SearchRequest(query=f"query {i}", top_k=3)
    await module.search(request)

  assert module._stats["searches_performed"] == 2

@pytest.mark.asyncio
async def test_module_multiple_documents_search(clean_rag_module):
  """
  Test search with multiple documents.
  """
  module = clean_rag_module
  await module.initialize()

  docs = [
    "Python is a programming language",
    "JavaScript is used for web development",
    "Rust is a systems programming language"
  ]

  for doc in docs:
    request = AddDocumentRequest(text=doc, metadata={})
    await module.add_document(request)

  search_request = SearchRequest(query="programming language", top_k=5)
  results = await module.search(search_request)

  assert len(results) > 0
  assert results[0].score > 0.0
