"""
────────────────────────────────────
Server Nexe
Version: 0.8
Author: Jordi Goy 
Location: memory/embeddings/core/vectorstore.py
Description: No description available.

www.jgoy.net
────────────────────────────────────
"""

from typing import Protocol, List, Dict, Optional, Any
from pydantic import BaseModel, Field, field_validator
from typing_extensions import Literal

class VectorSearchRequest(BaseModel):
  """
  Petició de cerca semàntica en un vector store.

  Attributes:
    query_vector: Vector d'embedding per cercar (e.g. 384 dimensions)
    top_k: Nombre màxim de resultats a retornar (default: 10)
    filters: Filtres opcionals sobre metadades (e.g. {"source": "pdf"})
    metric: Mètrica de distància a utilitzar (default: "cosine")

  Exemples:
    >>> request = VectorSearchRequest(
    ...   query_vector=[0.1, 0.2, 0.3, ...],
    ...   top_k=5,
    ...   filters={"language": "ca"}
    ... )
  """
  query_vector: List[float] = Field(
    ...,
    description="Vector d'embedding per cercar",
    min_length=1
  )
  top_k: int = Field(
    default=10,
    description="Nombre màxim de resultats a retornar",
    ge=1,
    le=1000
  )
  filters: Optional[Dict[str, Any]] = Field(
    default=None,
    description="Filtres sobre metadades (e.g. {'source': 'pdf'})"
  )
  metric: Literal["cosine", "euclidean", "dot"] = Field(
    default="cosine",
    description="Mètrica de distància per la cerca"
  )

  @field_validator('query_vector')
  @classmethod
  def validate_vector_dimensions(cls, v: List[float]) -> List[float]:
    """Valida que el vector tingui dimensions vàlides."""
    if len(v) == 0:
      raise ValueError("query_vector no pot estar buit")
    if not all(isinstance(x, (int, float)) for x in v):
      raise ValueError("query_vector ha de contenir només números")
    return v

class VectorSearchHit(BaseModel):
  """
  Resultat individual d'una cerca semàntica.

  Attributes:
    id: Identificador únic del vector/document
    score: Puntuació de similitud (més alt = més similar)
    text: Text original associat al vector
    metadata: Metadades addicionals del document

  Exemples:
    >>> hit = VectorSearchHit(
    ...   id="doc-123",
    ...   score=0.95,
    ...   text="Aquest és el text del document",
    ...   metadata={"source": "pdf", "page": 1}
    ... )
  """
  id: str = Field(
    ...,
    description="Identificador únic del vector/document",
    min_length=1
  )
  score: float = Field(
    ...,
    description="Puntuació de similitud (més alt = més similar)",
    ge=0.0,
    le=1.0
  )
  text: str = Field(
    ...,
    description="Text original associat al vector"
  )
  metadata: Dict[str, Any] = Field(
    default_factory=dict,
    description="Metadades addicionals del document"
  )

class VectorStore(Protocol):
  """
  Protocol per implementacions de vector stores intercanviables.

  Aquest protocol defineix la interfície que han de complir totes les
  implementacions de vector databases (Qdrant, FAISS, etc.)
  per garantir que es poden utilitzar de forma intercanviable.

  Implementacions conegudes:
    - memory.memory.tools.qdrant.QdrantAdapter
    - memory.tools.faiss.adapter.FAISSAdapter (futur)

  Exemples:
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
    Afegir múltiples vectors al store.

    Args:
      vectors: Llista de vectors d'embeddings (e.g. [[0.1, 0.2, ...], ...])
      texts: Llista de textos originals corresponents
      metadatas: Llista de diccionaris amb metadades per cada vector

    Returns:
      Llista d'IDs generats per cada vector afegit

    Raises:
      ValueError: Si les llistes no tenen la mateixa longitud
      RuntimeError: Si hi ha un error en guardar al vector store

    Exemples:
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
    Cercar vectors similars al query vector.

    Args:
      request: Petició de cerca amb query_vector, top_k, filters, etc.

    Returns:
      Llista de resultats ordenats per similitud (més alt primer)

    Raises:
      ValueError: Si el query_vector té dimensions incorrectes
      RuntimeError: Si hi ha un error en la cerca

    Exemples:
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
    Eliminar vectors per IDs.

    Args:
      ids: Llista d'IDs de vectors a eliminar

    Returns:
      Nombre de vectors eliminats correctament

    Raises:
      RuntimeError: Si hi ha un error en eliminar

    Exemples:
      >>> num_deleted = store.delete(["doc-1", "doc-2", "doc-3"])
      >>> print(f"Eliminats {num_deleted} documents")
      Eliminats 3 documents
    """
    ...

  def health(self) -> Dict[str, Any]:
    """
    Obtenir estat de salut del vector store.

    Returns:
      Diccionari amb informació d'estat:
        - status: "healthy" | "degraded" | "unhealthy"
        - num_vectors: Nombre total de vectors
        - storage_size: Mida en bytes (opcional)
        - last_updated: Timestamp última actualització (opcional)

    Exemples:
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