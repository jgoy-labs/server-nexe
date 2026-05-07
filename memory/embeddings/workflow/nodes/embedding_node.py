"""
────────────────────────────────────
Server Nexe
Author: Jordi Goy 
Location: memory/embeddings/workflow/nodes/embedding_node.py
Description: Workflow node per generar embeddings.

www.jgoy.net · https://server-nexe.org
────────────────────────────────────
"""

from typing import Dict, Any
from memory.embeddings.module import EmbeddingsModule
from memory.embeddings.core.interfaces import EmbeddingRequest
from memory.embeddings.constants import DEFAULT_EMBEDDING_MODEL

async def embedding_node(
  text: str,
  model: str = DEFAULT_EMBEDDING_MODEL,
  use_cache: bool = True,
  normalize: bool = True,
  cache_version: str = "v1"
) -> Dict[str, Any]:
  """
  Workflow node: Generates embedding for a text.

  Args:
    text: Text to convert
    model: fastembed model (e.g. sentence-transformers/paraphrase-multilingual-mpnet-base-v2)
    use_cache: Whether to use multi-level cache
    normalize: Whether to normalize embedding
    cache_version: Cache version

  Returns:
    Dict with:
    - embedding: Vector
    - dimensions: int
    - cache_hit: bool
    - latency_ms: float
    - model: str
  """
  module = EmbeddingsModule.get_instance()

  request = EmbeddingRequest(
    text=text,
    model=model,
    use_cache=use_cache,
    normalize=normalize,
    cache_version=cache_version
  )

  response = await module.encode(request)

  return {
    "embedding": response.embedding,
    "dimensions": response.dimensions,
    "cache_hit": response.cache_hit,
    "latency_ms": response.latency_ms,
    "model": response.model,
    "normalized": response.normalized
  }