"""
────────────────────────────────────
Server Nexe
Author: Jordi Goy 
Location: memory/embeddings/core/interfaces.py
Description: Interfaces, protocols and Pydantic models for the Embeddings module.

www.jgoy.net · https://server-nexe.org
────────────────────────────────────
"""

from typing import List, Protocol, runtime_checkable, Optional, Dict, Any
from pydantic import BaseModel, Field, field_validator, ValidationInfo
from datetime import datetime

class EmbeddingRequest(BaseModel):
  """
  Request per generar embedding d'un text.

  Attributes:
    text: Text a convertir en embedding (1-10K chars)
    model: Nom del model sentence-transformers
    normalize: Si normalitzar l'embedding (L2 norm)
    use_cache: Si usar cache multi-nivell
    cache_version: Versió del cache (per invalidació)
  """
  text: str = Field(..., min_length=1, max_length=10000)
  model: str = Field(default="paraphrase-multilingual-mpnet-base-v2")
  normalize: bool = True
  use_cache: bool = True
  cache_version: str = "v1"

  @field_validator('text')
  @classmethod
  def text_not_empty(cls, v):
    if not v.strip():
      raise ValueError("Text cannot be empty or whitespace only")
    return v

class EmbeddingResponse(BaseModel):
  """
  Response amb embedding generat i metadata.

  Attributes:
    embedding: Vector d'embedding (768 dimensions per defecte)
    dimensions: Nombre de dimensions del vector
    model: Model utilitzat
    normalized: Si l'embedding està normalitzat
    cache_hit: Si la resposta ve del cache
    latency_ms: Latència de generació en ms
  """
  embedding: List[float]
  dimensions: int
  model: str
  normalized: bool
  cache_hit: bool = False
  latency_ms: float = 0.0

  @field_validator('embedding')
  @classmethod
  def embedding_not_empty(cls, v):
    if not v:
      raise ValueError("Embedding cannot be empty")
    return v

  @field_validator('dimensions')
  @classmethod
  def dimensions_match(cls, v, info: ValidationInfo):
    if 'embedding' in info.data and len(info.data['embedding']) != v:
      raise ValueError(f"Dimensions {v} does not match len(embedding)={len(info.data['embedding'])}")
    return v

class BatchEmbeddingRequest(BaseModel):
  """
  Request per generar batch d'embeddings.

  Attributes:
    texts: Llista de texts (màx 100 per batch)
    model: Model sentence-transformers
    normalize: Si normalitzar embeddings
    use_cache: Si usar cache
    batch_size: Mida del batch intern (per SentenceTransformer)
  """
  texts: List[str] = Field(..., min_length=1, max_length=100)
  model: str = Field(default="paraphrase-multilingual-mpnet-base-v2")
  normalize: bool = True
  use_cache: bool = True
  batch_size: int = Field(default=32, ge=1, le=128)

  @field_validator('texts')
  @classmethod
  def texts_not_empty(cls, v):
    for text in v:
      if not text.strip():
        raise ValueError("No text can be empty or whitespace only")
    return v

class BatchEmbeddingResponse(BaseModel):
  """
  Response amb batch d'embeddings i stats.

  Attributes:
    embeddings: Llista d'embeddings (mateix ordre que texts)
    count: Nombre d'embeddings generats
    cache_hits: Nombre de cache hits
    total_latency_ms: Latència total del batch
    avg_latency_ms: Latència mitjana per embedding
  """
  embeddings: List[List[float]]
  count: int
  cache_hits: int = 0
  total_latency_ms: float = 0.0
  avg_latency_ms: float = 0.0

  @field_validator('count')
  @classmethod
  def count_match(cls, v, info: ValidationInfo):
    if 'embeddings' in info.data and len(info.data['embeddings']) != v:
      raise ValueError(f"Count {v} does not match len(embeddings)={len(info.data['embeddings'])}")
    return v

@runtime_checkable
class AsyncEncoder(Protocol):
  """
  Protocol per encoders async (no bloquegen event loop).

  Qualsevol classe que implementi aquest protocol pot ser usada
  com encoder al sistema d'embeddings.

  Methods:
    encode_async: Encode un sol text
    encode_batch_async: Encode batch de texts
    shutdown: Cleanup de recursos
  """

  async def encode_async(
    self,
    text: str,
    normalize: bool = True
  ) -> List[float]:
    """
    Encode un text async.

    Args:
      text: Text a convertir
      normalize: Si normalitzar (L2 norm)

    Returns:
      Vector d'embedding
    """
    ...

  async def encode_batch_async(
    self,
    texts: List[str],
    normalize: bool = True,
    batch_size: int = 32
  ) -> List[List[float]]:
    """
    Encode batch de texts async.

    Args:
      texts: Llista de texts
      normalize: Si normalitzar
      batch_size: Mida del batch intern

    Returns:
      Llista d'embeddings (mateix ordre)
    """
    ...

  async def shutdown(self) -> None:
    """Cleanup de recursos (ThreadPool, models carregats)"""
    ...

@runtime_checkable
class CacheProvider(Protocol):
  """
  Protocol per providers de cache.

  Permet usar diferents backends de cache (memòria, Redis, etc.)
  mantenint la mateixa interface.
  """

  async def get(
    self,
    text: str,
    model: str,
    version: str = "v1"
  ) -> Optional[List[float]]:
    """Get embedding del cache"""
    ...

  async def put(
    self,
    text: str,
    model: str,
    embedding: List[float],
    version: str = "v1"
  ) -> None:
    """Store embedding al cache"""
    ...

  async def clear(self) -> None:
    """Clear tot el cache"""
    ...

  def get_stats(self) -> Dict[str, Any]:
    """Get cache statistics."""
    ...

class ChunkMetadata(BaseModel):
  """
  Metadata for a document chunk.

  Attributes:
    chunk_id: Unique chunk ID (UUID)
    document_id: Parent document ID
    chunk_index: Chunk index within the document (0-based)
    char_start: Start position in the original document
    char_end: End position in the original document
    section_title: Detected section title (optional)
    chunk_type: Chunk type (paragraph, header, code, list)
    token_count: Approximate token count
  """
  chunk_id: str
  document_id: str
  chunk_index: int
  char_start: int
  char_end: int
  section_title: Optional[str] = None
  chunk_type: str = "paragraph"
  token_count: Optional[int] = None

  @field_validator('chunk_index', 'char_start', 'char_end')
  @classmethod
  def non_negative(cls, v):
    if v < 0:
      raise ValueError("Indexes cannot be negative")
    return v

  @field_validator('char_end')
  @classmethod
  def end_after_start(cls, v, info: ValidationInfo):
    if 'char_start' in info.data and v <= info.data['char_start']:
      raise ValueError("char_end ha de ser > char_start")
    return v

class ChunkedDocument(BaseModel):
  """
  Document chunked amb tots els chunks i metadata.

  Attributes:
    document_id: ID del document
    original_length: Longitud del document original
    chunks: Llista de chunks
    chunk_count: Nombre de chunks
    created_at: Timestamp de creació
  """
  document_id: str
  original_length: int
  chunks: List[ChunkMetadata]
  chunk_count: int
  created_at: datetime = Field(default_factory=datetime.now)

  @field_validator('chunk_count')
  @classmethod
  def count_match(cls, v, info: ValidationInfo):
    if 'chunks' in info.data and len(info.data['chunks']) != v:
      raise ValueError(f"chunk_count {v} does not match len(chunks)={len(info.data['chunks'])}")
    return v

class EncoderStats(BaseModel):
  """
  Estadístiques d'un encoder.

  Attributes:
    model_name: Nom del model carregat
    device: Device (cpu, mps, cuda)
    total_encodings: Total encodings generats
    total_requests: Alias per total_encodings (compatibility)
    cache_hit_rate: Ràtio de cache hits (0.0-1.0)
    avg_latency_ms: Latència mitjana
    p90_latency_ms: P90 latency
    p99_latency_ms: P99 latency
    active_since: Timestamp d'inici
  """
  model_name: str
  device: str
  total_encodings: int = 0
  total_requests: int = 0
  cache_hit_rate: float = 0.0
  avg_latency_ms: float = 0.0
  p90_latency_ms: float = 0.0
  p99_latency_ms: float = 0.0
  active_since: datetime = Field(default_factory=datetime.now)

  @field_validator('cache_hit_rate')
  @classmethod
  def hit_rate_valid(cls, v):
    if not 0.0 <= v <= 1.0:
      raise ValueError("cache_hit_rate ha d'estar entre 0.0 i 1.0")
    return v

  model_config = {
    "protected_namespaces": ()
  }