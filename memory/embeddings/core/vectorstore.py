"""
────────────────────────────────────
Server Nexe
Author: Jordi Goy 
Location: memory/embeddings/core/vectorstore.py
Description: No description available.

www.jgoy.net · https://server-nexe.org
────────────────────────────────────
"""

from typing import Protocol, List, Dict, Optional, Any
from pydantic import BaseModel, Field, field_validator
from typing_extensions import Literal

class VectorSearchRequest(BaseModel):
  """
  Semantic search request in a vector store.

  Attributes:
    query_vector: Embedding vector to search for (e.g. 768 dimensions)
    top_k: Maximum number of results to return (default: 10)
    filters: Optional metadata filters (e.g. {"source": "pdf"})
    metric: Distance metric to use (default: "cosine")

  Examples:
    >>> request = VectorSearchRequest(
    ...   query_vector=[0.1, 0.2, 0.3, ...],
    ...   top_k=5,
    ...   filters={"language": "ca"}
    ... )
  """
  query_vector: List[float] = Field(
    ...,
    description="Embedding vector to search for",
    min_length=1
  )
  top_k: int = Field(
    default=10,
    description="Maximum number of results to return (capped at 100 to prevent DoS)",
    ge=1,
    le=100
  )
  filters: Optional[Dict[str, Any]] = Field(
    default=None,
    description="Metadata filters (e.g. {'source': 'pdf'})"
  )
  metric: Literal["cosine", "euclidean", "dot"] = Field(
    default="cosine",
    description="Distance metric for search"
  )

  @field_validator('query_vector')
  @classmethod
  def validate_vector_dimensions(cls, v: List[float]) -> List[float]:
    """Validate that the vector has valid dimensions."""
    if len(v) == 0:
      raise ValueError("query_vector cannot be empty")
    if not all(isinstance(x, (int, float)) for x in v):
      raise ValueError("query_vector must contain only numbers")
    return v

class VectorSearchHit(BaseModel):
  """
  Individual result from a semantic search.

  Attributes:
    id: Unique vector/document identifier
    score: Similarity score (higher = more similar)
    text: Original text associated with the vector
    metadata: Additional document metadata

  Examples:
    >>> hit = VectorSearchHit(
    ...   id="doc-123",
    ...   score=0.95,
    ...   text="This is the document text",
    ...   metadata={"source": "pdf", "page": 1}
    ... )
  """
  id: str = Field(
    ...,
    description="Unique vector/document identifier",
    min_length=1
  )
  score: float = Field(
    ...,
    description="Similarity score (higher = more similar)",
    ge=0.0,
    le=1.0
  )
  text: str = Field(
    ...,
    description="Original text associated with the vector"
  )
  metadata: Dict[str, Any] = Field(
    default_factory=dict,
    description="Additional document metadata"
  )

class VectorStore(Protocol):
  """
  Protocol for interchangeable vector store implementations.

  This protocol defines the interface that all implementations of
  vector databases (Qdrant, FAISS, etc.) must comply with
  to guarantee they can be used interchangeably.

  Known implementations:
    - memory.memory.tools.qdrant.QdrantAdapter
    - memory.tools.faiss.adapter.FAISSAdapter (future)

  Examples:
    >>>
    >>> def create_vector_store(type: str) -> VectorStore:
    ...   if type == "qdrant":
    ...     return QdrantAdapter(collection_name="documents", path="./vectors")
    ...   elif type == "faiss":
    ...     return FAISSAdapter("./vectors")
    ...   raise ValueError(f"Unknown type: {type}")
    >>>
    >>> store = create_vector_store("qdrant")
    >>> ids = store.add_vectors(...)
  """

  def add_vectors(
    self,
    vectors: List[List[float]],
    texts: List[str],
    metadatas: List[Dict[str, Any]]
  ) -> List[str]:
    """
    Add multiple vectors to the store.

    Args:
      vectors: List of embedding vectors (e.g. [[0.1, 0.2, ...], ...])
      texts: List of corresponding original texts
      metadatas: List of dictionaries with metadata for each vector

    Returns:
      List of generated IDs for each added vector

    Raises:
      ValueError: If the lists do not have the same length
      RuntimeError: If there is an error saving to the vector store

    Examples:
      >>> ids = store.add_vectors(
      ...   vectors=[[0.1, 0.2, 0.3], [0.4, 0.5, 0.6]],
      ...   texts=["primer document", "segon document"],
      ...   metadatas=[{"source": "a"}, {"source": "b"}]
      ... )
      >>> print(ids)
      ['uuid-1', 'uuid-2']
    """
    ...

  def search(
    self,
    request: VectorSearchRequest
  ) -> List[VectorSearchHit]:
    """
    Search for vectors similar to the query vector.

    Args:
      request: Search request with query_vector, top_k, filters, etc.

    Returns:
      List of results sorted by similarity (highest first)

    Raises:
      ValueError: If the query_vector has incorrect dimensions
      RuntimeError: If there is an error in the search

    Examples:
      >>> request = VectorSearchRequest(
      ...   query_vector=[0.15, 0.25, 0.35],
      ...   top_k=5,
      ...   metric="cosine"
      ... )
      >>> hits = store.search(request)
      >>> for hit in hits:
      ...   print(f"{hit.id}: {hit.score:.3f} - {hit.text[:50]}")
      doc-1: 0.950 - Aquest document és molt similar...
      doc-2: 0.820 - Aquest altre també és rellevant...
    """
    ...

  def delete(self, ids: List[str]) -> int:
    """
    Delete vectors by IDs.

    Args:
      ids: List of vector IDs to delete

    Returns:
      Number of successfully deleted vectors

    Raises:
      RuntimeError: If there is an error deleting

    Examples:
      >>> num_deleted = store.delete(["doc-1", "doc-2", "doc-3"])
      >>> print(f"Eliminats {num_deleted} documents")
      Eliminats 3 documents
    """
    ...

  def health(self) -> Dict[str, Any]:
    """
    Get health status of the vector store.

    Returns:
      Dictionary with status information:
        - status: "healthy" | "degraded" | "unhealthy"
        - num_vectors: Total number of vectors
        - storage_size: Size in bytes (optional)
        - last_updated: Last update timestamp (optional)

    Examples:
      >>> health = store.health()
      >>> print(health)
      {
        'status': 'healthy',
        'num_vectors': 1234,
        'storage_size': 5242880,
        'db_path': './vectors/2025/'
      }
    """
    ...