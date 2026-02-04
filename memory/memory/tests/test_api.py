"""
────────────────────────────────────
Server Nexe
Version: 0.8
Author: Jordi Goy 
Location: memory/memory/tests/test_api.py
Description: Tests per Memory API.

www.jgoy.net
────────────────────────────────────
"""

import pytest
from datetime import datetime, timedelta, timezone

from memory.memory.api import (
  MemoryAPI,
  Document,
  SearchResult,
  CollectionInfo,
  MemoryAPIError,
  CollectionNotFoundError,
  InvalidCollectionNameError,
  DocumentNotFoundError,
  validate_collection_name,
  COLLECTION_NAME_PATTERN,
)

class TestNamingConvention:
  """Tests per la naming convention de collections."""

  def test_valid_simple_name(self):
    """Test nom vàlid simple."""
    validate_collection_name("nexe_knowledge")

  def test_valid_with_numbers(self):
    """Test nom vàlid amb números."""
    validate_collection_name("module1_data2")

  def test_valid_multiple_underscores(self):
    """Test nom vàlid amb múltiples underscores."""
    validate_collection_name("memory_rag_sources")

  def test_invalid_uppercase(self):
    """Test que rebutja majúscules."""
    with pytest.raises(InvalidCollectionNameError):
      validate_collection_name("Nexe_Knowledge")

  def test_invalid_no_underscore(self):
    """Test que rebutja noms sense underscore."""
    with pytest.raises(InvalidCollectionNameError):
      validate_collection_name("memory")

  def test_invalid_starts_with_number(self):
    """Test que rebutja noms que comencen amb número."""
    with pytest.raises(InvalidCollectionNameError):
      validate_collection_name("1module_data")

  def test_invalid_starts_with_underscore(self):
    """Test que rebutja noms que comencen amb underscore."""
    with pytest.raises(InvalidCollectionNameError):
      validate_collection_name("_test_data")

  def test_invalid_hyphen(self):
    """Test que rebutja noms amb guió."""
    with pytest.raises(InvalidCollectionNameError):
      validate_collection_name("context-roads")

  def test_invalid_space(self):
    """Test que rebutja noms amb espais."""
    with pytest.raises(InvalidCollectionNameError):
      validate_collection_name("context roads")

  def test_invalid_empty_after_underscore(self):
    """Test que rebutja noms amb underscore final sense res."""
    with pytest.raises(InvalidCollectionNameError):
      validate_collection_name("context_")

  def test_pattern_valid_examples(self):
    """Test exemples vàlids del pattern."""
    valid_names = [
      "nexe_knowledge",
      "memory_sources",
      "system_logs",
      "demo_embeddings",
      "module1_cache",
      "a_b",
      "test_data123",
    ]
    for name in valid_names:
      assert COLLECTION_NAME_PATTERN.match(name), f"{name} should be valid"

  def test_pattern_invalid_examples(self):
    """Test exemples invàlids del pattern."""
    invalid_names = [
      "Nexe_Knowledge",
      "memory",
      "1module_data",
      "_test",
      "test-data",
      "test data",
      "test_",
      "",
      "UPPERCASE",
    ]
    for name in invalid_names:
      assert not COLLECTION_NAME_PATTERN.match(name), f"{name} should be invalid"

class TestDocumentModel:
  """Tests per Document dataclass."""

  def test_document_not_expired_no_expires_at(self):
    """Test document permanent (sense expires_at)."""
    doc = Document(
      id="test123",
      text="Test content",
      collection="test_data",
    )
    assert not doc.is_expired
    assert doc.ttl_remaining is None

  def test_document_not_expired_future_date(self):
    """Test document amb expires_at futur."""
    future = datetime.now(timezone.utc) + timedelta(hours=1)
    doc = Document(
      id="test123",
      text="Test content",
      collection="test_data",
      expires_at=future,
    )
    assert not doc.is_expired
    assert doc.ttl_remaining > 0
    assert doc.ttl_remaining <= 3600

  def test_document_expired_past_date(self):
    """Test document amb expires_at passat."""
    past = datetime.now(timezone.utc) - timedelta(hours=1)
    doc = Document(
      id="test123",
      text="Test content",
      collection="test_data",
      expires_at=past,
    )
    assert doc.is_expired
    assert doc.ttl_remaining == 0

  def test_document_metadata_default(self):
    """Test metadata per defecte."""
    doc = Document(
      id="test123",
      text="Test content",
      collection="test_data",
    )
    assert doc.metadata == {}

  def test_document_with_metadata(self):
    """Test document amb metadata."""
    doc = Document(
      id="test123",
      text="Test content",
      collection="test_data",
      metadata={"type": "test", "source": "api"},
    )
    assert doc.metadata["type"] == "test"
    assert doc.metadata["source"] == "api"

class TestSearchResultModel:
  """Tests per SearchResult dataclass."""

  def test_search_result_basic(self):
    """Test SearchResult bàsic."""
    result = SearchResult(
      id="test123",
      score=0.95,
      collection="test_data",
    )
    assert result.id == "test123"
    assert result.score == 0.95
    assert result.text is None
    assert result.metadata == {}

  def test_search_result_with_text(self):
    """Test SearchResult amb text."""
    result = SearchResult(
      id="test123",
      score=0.85,
      collection="test_data",
      text="Contingut trobat",
    )
    assert result.text == "Contingut trobat"

  def test_search_result_with_metadata(self):
    """Test SearchResult amb metadata."""
    result = SearchResult(
      id="test123",
      score=0.75,
      collection="test_data",
      metadata={"type": "document"},
    )
    assert result.metadata["type"] == "document"

class TestCollectionInfoModel:
  """Tests per CollectionInfo dataclass."""

  def test_collection_info_basic(self):
    """Test CollectionInfo bàsic."""
    info = CollectionInfo(
      name="test_data",
      vector_size=384,
      points_count=100,
    )
    assert info.name == "test_data"
    assert info.vector_size == 384
    assert info.points_count == 100
    assert info.created_at is None

class TestMemoryAPIInit:
  """Tests d'inicialització de MemoryAPI."""

  def test_init_default_values(self):
    """Test inicialització amb valors per defecte."""
    api = MemoryAPI()
    assert api.embedding_model == "all-MiniLM-L6-v2"
    assert api.vector_size == 768  # DEFAULT_VECTOR_SIZE
    assert not api._initialized

  def test_init_custom_model(self):
    """Test inicialització amb model personalitzat."""
    api = MemoryAPI(embedding_model="custom-model")
    assert api.embedding_model == "custom-model"

  def test_ensure_initialized_raises(self):
    """Test que _ensure_initialized llança error si no inicialitzat."""
    api = MemoryAPI()
    with pytest.raises(RuntimeError, match="not initialized"):
      api._ensure_initialized()

class TestMemoryAPIHelpers:
  """Tests per helpers de MemoryAPI."""

  def test_hex_to_uuid_basic(self):
    """Test conversió hex a UUID."""
    result = MemoryAPI._hex_to_uuid("abc123")
    assert "-" in result
    assert len(result) == 36

  def test_hex_to_uuid_16_chars(self):
    """Test conversió hex 16 chars a UUID."""
    result = MemoryAPI._hex_to_uuid("0123456789abcdef")
    assert len(result) == 36

  def test_hex_to_uuid_padding(self):
    """Test que padeja correctament."""
    short = MemoryAPI._hex_to_uuid("abc")
    long = MemoryAPI._hex_to_uuid("abc" + "0" * 29)
    assert len(short) == 36
    assert len(long) == 36

class TestExceptions:
  """Tests per exceptions."""

  def test_memory_api_error_is_base(self):
    """Test que MemoryAPIError és la base."""
    assert issubclass(CollectionNotFoundError, MemoryAPIError)
    assert issubclass(InvalidCollectionNameError, MemoryAPIError)
    assert issubclass(DocumentNotFoundError, MemoryAPIError)

  def test_collection_not_found_error(self):
    """Test CollectionNotFoundError."""
    error = CollectionNotFoundError("test_collection")
    assert "test_collection" in str(error)

  def test_invalid_collection_name_error(self):
    """Test InvalidCollectionNameError."""
    error = InvalidCollectionNameError("BadName")
    assert "BadName" in str(error)

@pytest.fixture
async def memory_api(tmp_path):
  """Fixture que crea MemoryAPI amb Qdrant temporal."""
  qdrant_path = tmp_path / "qdrant"
  api = MemoryAPI(qdrant_path=qdrant_path)
  await api.initialize()
  yield api
  await api.close()

@pytest.mark.asyncio
class TestMemoryAPIIntegration:
  """Tests d'integració amb Qdrant real."""

  async def test_create_collection(self, memory_api):
    """Test crear collection."""
    result = await memory_api.create_collection("test_data")
    assert result is True

  async def test_create_collection_already_exists(self, memory_api):
    """Test crear collection que ja existeix."""
    await memory_api.create_collection("test_data")
    result = await memory_api.create_collection("test_data")
    assert result is False

  async def test_create_collection_invalid_name(self, memory_api):
    """Test crear collection amb nom invàlid."""
    with pytest.raises(InvalidCollectionNameError):
      await memory_api.create_collection("InvalidName")

  async def test_collection_exists(self, memory_api):
    """Test comprovar si collection existeix."""
    await memory_api.create_collection("test_data")
    assert await memory_api.collection_exists("test_data")
    assert not await memory_api.collection_exists("nonexistent_col")

  async def test_list_collections(self, memory_api):
    """Test llistar collections."""
    await memory_api.create_collection("test_data")
    await memory_api.create_collection("test_other")
    collections = await memory_api.list_collections()
    names = [c.name for c in collections]
    assert "test_data" in names
    assert "test_other" in names

  async def test_delete_collection(self, memory_api):
    """Test eliminar collection."""
    await memory_api.create_collection("test_data")
    result = await memory_api.delete_collection("test_data")
    assert result is True
    assert not await memory_api.collection_exists("test_data")

  async def test_delete_nonexistent_collection(self, memory_api):
    """Test eliminar collection inexistent."""
    result = await memory_api.delete_collection("nonexistent_col")
    assert result is False

  async def test_store_and_get(self, memory_api):
    """Test guardar i recuperar document."""
    await memory_api.create_collection("test_data")
    doc_id = await memory_api.store(
      text="Test content",
      collection="test_data",
      metadata={"type": "test"},
    )
    assert doc_id is not None

    doc = await memory_api.get(doc_id, "test_data")
    assert doc is not None
    assert doc.text == "Test content"
    assert doc.metadata["type"] == "test"

  async def test_store_nonexistent_collection(self, memory_api):
    """Test guardar en collection inexistent."""
    with pytest.raises(CollectionNotFoundError):
      await memory_api.store("text", "nonexistent_col")

  async def test_store_with_ttl(self, memory_api):
    """Test guardar amb TTL."""
    await memory_api.create_collection("test_data")
    doc_id = await memory_api.store(
      text="Temporary content",
      collection="test_data",
      ttl_seconds=3600,
    )

    doc = await memory_api.get(doc_id, "test_data")
    assert doc is not None
    assert doc.expires_at is not None
    assert not doc.is_expired

  async def test_search_basic(self, memory_api):
    """Test cerca bàsica."""
    await memory_api.create_collection("test_data")
    await memory_api.store("Python is a programming language", "test_data")
    await memory_api.store("JavaScript is also a language", "test_data")

    results = await memory_api.search("programming language", "test_data")
    assert len(results) > 0
    assert results[0].score > 0

  async def test_search_with_filter(self, memory_api):
    """Test cerca amb filtre."""
    await memory_api.create_collection("test_data")
    await memory_api.store("Doc type A", "test_data", metadata={"type": "A"})
    await memory_api.store("Doc type B", "test_data", metadata={"type": "B"})

    results = await memory_api.search(
      "Doc",
      "test_data",
      filter_metadata={"type": "A"},
    )
    for r in results:
      if r.metadata.get("type"):
        assert r.metadata["type"] == "A"

  async def test_search_nonexistent_collection(self, memory_api):
    """Test cerca en collection inexistent."""
    with pytest.raises(CollectionNotFoundError):
      await memory_api.search("query", "nonexistent_col")

  async def test_delete_document(self, memory_api):
    """Test eliminar document."""
    await memory_api.create_collection("test_data")
    doc_id = await memory_api.store("To delete", "test_data")

    result = await memory_api.delete(doc_id, "test_data")
    assert result is True

    doc = await memory_api.get(doc_id, "test_data")
    assert doc is None

  async def test_count(self, memory_api):
    """Test comptar documents."""
    await memory_api.create_collection("test_data")
    await memory_api.store("Doc 1", "test_data")
    await memory_api.store("Doc 2", "test_data")

    count = await memory_api.count("test_data")
    assert count == 2

  async def test_context_manager(self, tmp_path):
    """Test context manager."""
    qdrant_path = tmp_path / "qdrant2"
    async with MemoryAPI(qdrant_path=qdrant_path) as memory:
      await memory.create_collection("test_data")
      assert await memory.collection_exists("test_data")
    assert not memory._initialized

if __name__ == "__main__":
  pytest.main([__file__, "-v"])