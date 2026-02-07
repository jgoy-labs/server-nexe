"""
────────────────────────────────────
Server Nexe
Version: 0.8
Author: Jordi Goy 
Location: memory/embeddings/core/interfaces.py
Description: Interfaces, protocols, and Pydantic models for the Embeddings module.

www.jgoy.net
────────────────────────────────────
"""

from typing import List, Protocol, runtime_checkable, Optional, Dict, Any
from pydantic import BaseModel, Field, field_validator, ValidationInfo
from datetime import datetime
from personality.i18n import get_i18n


def _t(key: str, fallback: str, **kwargs) -> str:
  try:
    return get_i18n().t(key, fallback, **kwargs)
  except Exception:
    if kwargs:
      try:
        return fallback.format(**kwargs)
      except (KeyError, ValueError):
        return fallback
    return fallback

class EmbeddingRequest(BaseModel):
  """
  Request to generate an embedding from text.

  Attributes:
    text: Text to convert into an embedding (1-10K chars)
    model: Sentence-transformers model name
    normalize: Whether to normalize the embedding (L2 norm)
    use_cache: Whether to use multi-level cache
    cache_version: Cache version (for invalidation)
  """
  text: str = Field(..., min_length=1, max_length=10000)
  model: str = Field(default="paraphrase-multilingual-MiniLM-L12-v2")
  normalize: bool = True
  use_cache: bool = True
  cache_version: str = "v1"

  @field_validator('text')
  @classmethod
  def text_not_empty(cls, v):
    if not v.strip():
      raise ValueError(
        _t(
          "embeddings.validation.text_blank",
          "Text cannot be empty or only whitespace"
        )
      )
    return v

class EmbeddingResponse(BaseModel):
  """
  Response with generated embedding and metadata.

  Attributes:
    embedding: Embedding vector (384 dimensions by default)
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
      raise ValueError(
        _t(
          "embeddings.validation.embedding_empty",
          "Embedding cannot be empty"
        )
      )
    return v

  @field_validator('dimensions')
  @classmethod
  def dimensions_match(cls, v, info: ValidationInfo):
    if 'embedding' in info.data and len(info.data['embedding']) != v:
      raise ValueError(
        _t(
          "embeddings.validation.dimensions_mismatch",
          "Dimensions {dimensions} do not match len(embedding)={embedding_len}",
          dimensions=v,
          embedding_len=len(info.data['embedding'])
        )
      )
    return v

class BatchEmbeddingRequest(BaseModel):
  """
  Request to generate a batch of embeddings.

  Attributes:
    texts: List of texts (max 100 per batch)
    model: Sentence-transformers model
    normalize: Whether to normalize embeddings
    use_cache: Whether to use cache
    batch_size: Internal batch size (for SentenceTransformer)
  """
  texts: List[str] = Field(..., min_length=1, max_length=100)
  model: str = Field(default="paraphrase-multilingual-MiniLM-L12-v2")
  normalize: bool = True
  use_cache: bool = True
  batch_size: int = Field(default=32, ge=1, le=128)

  @field_validator('texts')
  @classmethod
  def texts_not_empty(cls, v):
    for text in v:
      if not text.strip():
        raise ValueError(
          _t(
            "embeddings.validation.texts_blank",
            "Each text must be non-empty and not just whitespace"
          )
        )
    return v

class BatchEmbeddingResponse(BaseModel):
  """
  Response with batch embeddings and stats.

  Attributes:
    embeddings: List of embeddings (same order as texts)
    count: Number of embeddings generated
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
      raise ValueError(
        _t(
          "embeddings.validation.count_mismatch",
          "Count {count} does not match len(embeddings)={embedding_len}",
          count=v,
          embedding_len=len(info.data['embeddings'])
        )
      )
    return v

@runtime_checkable
class AsyncEncoder(Protocol):
  """
  Protocol for async encoders (do not block the event loop).

  Any class implementing this protocol can be used
  as an encoder in the embeddings system.

  Methods:
    encode_async: Encode a single text
    encode_batch_async: Encode a batch of texts
    shutdown: Resource cleanup
  """

  async def encode_async(
    self,
    text: str,
    normalize: bool = True
  ) -> List[float]:
    """
    Encode text asynchronously.

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
    Encode a batch of texts asynchronously.

    Args:
      texts: List of texts
      normalize: Whether to normalize
      batch_size: Internal batch size

    Returns:
      List of embeddings (same order)
    """
    ...

  async def shutdown(self) -> None:
    """Cleanup resources (ThreadPool, loaded models)."""
    ...

@runtime_checkable
class CacheProvider(Protocol):
  """
  Protocol for cache providers.

  Allows using different cache backends (memory, Redis, etc.)
  while keeping the same interface.
  """

  async def get(
    self,
    text: str,
    model: str,
    version: str = "v1"
  ) -> Optional[List[float]]:
    """Get embedding from cache."""
    ...

  async def put(
    self,
    text: str,
    model: str,
    embedding: List[float],
    version: str = "v1"
  ) -> None:
    """Store embedding in cache."""
    ...

  async def clear(self) -> None:
    """Clear the entire cache."""
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
    token_count: Approximate number of tokens
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
      raise ValueError(
        _t(
          "embeddings.validation.indices_negative",
          "Indices cannot be negative"
        )
      )
    return v

  @field_validator('char_end')
  @classmethod
  def end_after_start(cls, v, info: ValidationInfo):
    if 'char_start' in info.data and v <= info.data['char_start']:
      raise ValueError(
        _t(
          "embeddings.validation.char_end_gt_start",
          "char_end must be > char_start"
        )
      )
    return v

class ChunkedDocument(BaseModel):
  """
  Chunked document with all chunks and metadata.

  Attributes:
    document_id: Document ID
    original_length: Original document length
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
      raise ValueError(
        _t(
          "embeddings.validation.chunk_count_mismatch",
          "chunk_count {count} does not match len(chunks)={chunk_len}",
          count=v,
          chunk_len=len(info.data['chunks'])
        )
      )
    return v

class EncoderStats(BaseModel):
  """
  Encoder statistics.

  Attributes:
    model_name: Loaded model name
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
      raise ValueError(
        _t(
          "embeddings.validation.cache_hit_rate_range",
          "cache_hit_rate must be between 0.0 and 1.0"
        )
      )
    return v

  model_config = {
    "protected_namespaces": ()
  }
