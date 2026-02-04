"""
────────────────────────────────────
Server Nexe
Version: 0.8
Author: Jordi Goy 
Location: memory/embeddings/tests/test_vectorstore_protocol.py
Description: No description available.

www.jgoy.net
────────────────────────────────────
"""

import pytest
from typing import List, Dict, Any
from pydantic import ValidationError

from memory.embeddings.core.vectorstore import (
  VectorStore,
  VectorSearchRequest,
  VectorSearchHit
)

class TestVectorSearchRequest:
  """Tests per el model VectorSearchRequest."""

  def test_valid_request(self):
    """Test creació request vàlid."""
    request = VectorSearchRequest(
      query_vector=[0.1, 0.2, 0.3],
      top_k=10
    )
    assert request.query_vector == [0.1, 0.2, 0.3]
    assert request.top_k == 10
    assert request.metric == "cosine"
    assert request.filters is None

  def test_request_with_filters(self):
    """Test request amb filtres."""
    request = VectorSearchRequest(
      query_vector=[0.1, 0.2],
      top_k=5,
      filters={"source": "pdf", "language": "ca"}
    )
    assert request.filters == {"source": "pdf", "language": "ca"}

  def test_request_with_different_metrics(self):
    """Test request amb diferents mètriques."""
    for metric in ["cosine", "euclidean", "dot"]:
      request = VectorSearchRequest(
        query_vector=[0.1, 0.2],
        metric=metric
      )
      assert request.metric == metric

  def test_invalid_metric(self):
    """Test mètrica invàlida."""
    with pytest.raises(ValidationError) as exc_info:
      VectorSearchRequest(
        query_vector=[0.1, 0.2],
        metric="invalid"
      )
    assert "metric" in str(exc_info.value)

  def test_empty_query_vector(self):
    """Test vector buit rebutjat."""
    with pytest.raises(ValidationError) as exc_info:
      VectorSearchRequest(query_vector=[])
    assert "query_vector" in str(exc_info.value)

  def test_invalid_top_k_zero(self):
    """Test top_k=0 rebutjat."""
    with pytest.raises(ValidationError) as exc_info:
      VectorSearchRequest(
        query_vector=[0.1, 0.2],
        top_k=0
      )
    assert "top_k" in str(exc_info.value)

  def test_invalid_top_k_negative(self):
    """Test top_k negatiu rebutjat."""
    with pytest.raises(ValidationError) as exc_info:
      VectorSearchRequest(
        query_vector=[0.1, 0.2],
        top_k=-5
      )
    assert "top_k" in str(exc_info.value)

  def test_invalid_top_k_too_large(self):
    """Test top_k massa gran rebutjat."""
    with pytest.raises(ValidationError) as exc_info:
      VectorSearchRequest(
        query_vector=[0.1, 0.2],
        top_k=2000
      )
    assert "top_k" in str(exc_info.value)

  def test_query_vector_with_non_numbers(self):
    """Test query_vector amb no-números rebutjat."""
    with pytest.raises(ValidationError) as exc_info:
      VectorSearchRequest(
        query_vector=[0.1, "invalid", 0.3]
      )

class TestVectorSearchHit:
  """Tests per el model VectorSearchHit."""

  def test_valid_hit(self):
    """Test creació hit vàlid."""
    hit = VectorSearchHit(
      id="doc-123",
      score=0.95,
      text="Aquest és el text del document",
      metadata={"source": "pdf", "page": 1}
    )
    assert hit.id == "doc-123"
    assert hit.score == 0.95
    assert hit.text == "Aquest és el text del document"
    assert hit.metadata == {"source": "pdf", "page": 1}

  def test_hit_with_empty_metadata(self):
    """Test hit amb metadata buida."""
    hit = VectorSearchHit(
      id="doc-1",
      score=0.8,
      text="Text"
    )
    assert hit.metadata == {}

  def test_hit_score_boundaries(self):
    """Test score als límits (0.0 i 1.0)."""
    hit_min = VectorSearchHit(id="1", score=0.0, text="Min")
    assert hit_min.score == 0.0

    hit_max = VectorSearchHit(id="2", score=1.0, text="Max")
    assert hit_max.score == 1.0

  def test_invalid_score_negative(self):
    """Test score negatiu rebutjat."""
    with pytest.raises(ValidationError) as exc_info:
      VectorSearchHit(
        id="doc-1",
        score=-0.1,
        text="Text"
      )
    assert "score" in str(exc_info.value)

  def test_invalid_score_too_large(self):
    """Test score >1.0 rebutjat."""
    with pytest.raises(ValidationError) as exc_info:
      VectorSearchHit(
        id="doc-1",
        score=1.5,
        text="Text"
      )
    assert "score" in str(exc_info.value)

  def test_empty_id(self):
    """Test id buit rebutjat."""
    with pytest.raises(ValidationError) as exc_info:
      VectorSearchHit(
        id="",
        score=0.5,
        text="Text"
      )
    assert "id" in str(exc_info.value)

class TestVectorStoreProtocol:
  """Tests per el Protocol VectorStore."""

  def test_protocol_cannot_be_instantiated(self):
    """Test que el Protocol no es pot instanciar directament."""

    expected_methods = ['add_vectors', 'search', 'delete', 'health']
    for method in expected_methods:
      assert hasattr(VectorStore, method), f"Protocol manca mètode: {method}"

  def test_mock_implementation_complies(self):
    """Test que una implementació mock compleix el protocol."""

    class MockVectorStore:
      """Mock implementation per testing."""

      def add_vectors(
        self,
        vectors: List[List[float]],
        texts: List[str],
        metadatas: List[Dict[str, Any]]
      ) -> List[str]:
        return [f"id-{i}" for i in range(len(vectors))]

      def search(
        self,
        request: VectorSearchRequest
      ) -> List[VectorSearchHit]:
        return [
          VectorSearchHit(
            id="mock-1",
            score=0.95,
            text="Mock result 1",
            metadata={}
          )
        ]

      def delete(self, ids: List[str]) -> int:
        return len(ids)

      def health(self) -> Dict[str, Any]:
        return {"status": "healthy", "num_vectors": 0}

    store = MockVectorStore()

    ids = store.add_vectors(
      vectors=[[0.1, 0.2], [0.3, 0.4]],
      texts=["text1", "text2"],
      metadatas=[{}, {}]
    )
    assert len(ids) == 2
    assert ids[0] == "id-0"

    request = VectorSearchRequest(query_vector=[0.5, 0.6])
    hits = store.search(request)
    assert len(hits) == 1
    assert hits[0].id == "mock-1"
    assert hits[0].score == 0.95

    num_deleted = store.delete(["id-1", "id-2"])
    assert num_deleted == 2

    health = store.health()
    assert health["status"] == "healthy"
    assert "num_vectors" in health

  def test_protocol_type_checking(self):
    """Test que el protocol funciona amb type checking."""

    def use_vector_store(store: VectorStore) -> int:
      """Funció que usa el protocol."""
      health = store.health()
      return health.get("num_vectors", 0)

    class SimpleStore:
      def add_vectors(self, vectors, texts, metadatas):
        return []
      def search(self, request):
        return []
      def delete(self, ids):
        return 0
      def health(self):
        return {"num_vectors": 42}

    store = SimpleStore()
    result = use_vector_store(store)
    assert result == 42

class TestVectorStoreIntegration:
  """Tests d'integració entre components."""

  def test_request_and_hit_compatibility(self):
    """Test que Request i Hit són compatibles."""

    request = VectorSearchRequest(
      query_vector=[0.1, 0.2, 0.3],
      top_k=5,
      filters={"language": "ca"}
    )

    hits = [
      VectorSearchHit(
        id=f"doc-{i}",
        score=0.9 - (i * 0.1),
        text=f"Document {i}",
        metadata={"language": "ca", "index": i}
      )
      for i in range(request.top_k)
    ]

    assert len(hits) == 5
    assert hits[0].score > hits[1].score
    assert hits[1].score > hits[2].score

    for hit in hits:
      assert hit.metadata.get("language") == "ca"

  def test_serialization_deserialization(self):
    """Test serialització/deserialització Pydantic."""

    request = VectorSearchRequest(
      query_vector=[0.1, 0.2, 0.3],
      top_k=5,
      metric="cosine"
    )
    request_dict = request.model_dump()
    request_restored = VectorSearchRequest(**request_dict)
    assert request_restored == request

    hit = VectorSearchHit(
      id="doc-1",
      score=0.95,
      text="Test",
      metadata={"key": "value"}
    )
    hit_dict = hit.model_dump()
    hit_restored = VectorSearchHit(**hit_dict)
    assert hit_restored == hit