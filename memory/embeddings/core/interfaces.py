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

from memory.embeddings.constants import DEFAULT_EMBEDDING_MODEL

class EmbeddingRequest(BaseModel):
  """
  Request to generate an embedding for a text.

  Attributes:
    text: Text to convert to embedding (1-10K chars)
    model: Embeddings model name
    normalize: Whether to normalize the embedding (L2 norm)
    use_cache: Whether to use multi-level cache
    cache_version: Cache version (for invalidation)
  """
  text: str = Field(..., min_length=1, max_length=10000)
  model: str = Field(default=DEFAULT_EMBEDDING_MODEL)
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
  Response with generated embedding and metadata.

  Attributes:
    embedding: Embedding vector (768 dimensions by default)
    dimensions: Number of vector dimensions
    model: Model used
    normalized: Whether the embedding is normalized
    cache_hit: Whether the response came from cache
    latency_ms: Generation latency in ms
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
  Request to generate a batch of embeddings.

  Attributes:
    texts: List of texts (max 100 per batch)
    model: fastembed model (e.g. sentence-transformers/paraphrase-multilingual-mpnet-base-v2)
    normalize: Whether to normalize embeddings
    use_cache: Whether to use cache
    batch_size: Internal batch size (for fastembed TextEmbedding)
  """
  texts: List[str] = Field(..., min_length=1, max_length=100)
  model: str = Field(default=DEFAULT_EMBEDDING_MODEL)
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
  Response with batch of embeddings and stats.

  Attributes:
    embeddings: List of embeddings (same order as texts)
    count: Number of generated embeddings
    cache_hits: Number of cache hits
    total_latency_ms: Total batch latency
    avg_latency_ms: Average latency per embedding
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
  Protocol for async encoders (do not block the event loop).

  Any class that implements this protocol can be used
  as an encoder in the embeddings system.

  Methods:
    encode_async: Encode a single text
    encode_batch_async: Encode batch of texts
    shutdown: Resource cleanup
  """

  async def encode_async(
    self,
    text: str,
    normalize: bool = True
  ) -> List[float]:
    """
    Encode a text async.

    Args:
      text: Text to convert
      normalize: Whether to normalize (L2 norm)

    Returns:
      Embedding vector
    """
    ...

  async def encode_batch_async(
    self,
    texts: List[str],
    normalize: bool = True,
    batch_size: int = 32
  ) -> List[List[float]]:
    """
    Encode batch of texts async.

    Args:
      texts: List of texts
      normalize: Whether to normalize
      batch_size: Internal batch size

    Returns:
      List of embeddings (same order)
    """
    ...

  async def shutdown(self) -> None:
    """Resource cleanup (ThreadPool, loaded models)"""
    ...

@runtime_checkable
class CacheProvider(Protocol):
  """
  Protocol for cache providers.

  Allows using different cache backends (memory, Redis, etc.)
  while maintaining the same interface.
  """

  async def get(
    self,
    text: str,
    model: str,
    version: str = "v1"
  ) -> Optional[List[float]]:
    """Get embedding from cache"""
    ...

  async def put(
    self,
    text: str,
    model: str,
    embedding: List[float],
    version: str = "v1"
  ) -> None:
    """Store embedding in cache"""
    ...

  async def clear(self) -> None:
    """Clear all cache"""
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
  Chunked document with all chunks and metadata.

  Attributes:
    document_id: Document ID
    original_length: Length of the original document
    chunks: List of chunks
    chunk_count: Number of chunks
    created_at: Creation timestamp
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
  Encoder statistics.

  Attributes:
    model_name: Name of the loaded model
    device: Device (cpu, mps, cuda)
    total_encodings: Total encodings generated
    total_requests: Alias for total_encodings (compatibility)
    cache_hit_rate: Cache hit ratio (0.0-1.0)
    avg_latency_ms: Average latency
    p90_latency_ms: P90 latency
    p99_latency_ms: P99 latency
    active_since: Start timestamp
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