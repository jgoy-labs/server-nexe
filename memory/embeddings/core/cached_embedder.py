"""
────────────────────────────────────
Server Nexe
Author: Jordi Goy 
Location: memory/embeddings/core/cached_embedder.py
Description: CachedEmbedder: Integrates AsyncEmbedder with MultiLevelCache to optimise latency.

www.jgoy.net · https://server-nexe.org
────────────────────────────────────
"""

import time
from typing import List, Optional

import structlog

from memory.shared.cache import MultiLevelCache
from memory.embeddings.core.async_encoder import AsyncEmbedder
from memory.embeddings.core.interfaces import (
  EmbeddingRequest,
  EmbeddingResponse,
  BatchEmbeddingRequest,
  BatchEmbeddingResponse,
  EncoderStats,
)

logger = structlog.get_logger()

_metrics_imported = False
_EMBEDDING_OPERATIONS = None
_EMBEDDING_CACHE_HITS = None
_EMBEDDING_CACHE_MISSES = None

def _get_metrics():
  """Lazy import Prometheus metrics."""
  global _metrics_imported, _EMBEDDING_OPERATIONS, _EMBEDDING_CACHE_HITS, _EMBEDDING_CACHE_MISSES
  if not _metrics_imported:
    try:
      from core.metrics.registry import (
        EMBEDDING_OPERATIONS,
        EMBEDDING_CACHE_HITS,
        EMBEDDING_CACHE_MISSES,
      )
      _EMBEDDING_OPERATIONS = EMBEDDING_OPERATIONS
      _EMBEDDING_CACHE_HITS = EMBEDDING_CACHE_HITS
      _EMBEDDING_CACHE_MISSES = EMBEDDING_CACHE_MISSES
      _metrics_imported = True
    except ImportError:
      _metrics_imported = True
  return _EMBEDDING_OPERATIONS, _EMBEDDING_CACHE_HITS, _EMBEDDING_CACHE_MISSES

class CachedEmbedder:
  """
  Embedder with integrated multi-level cache.

  Combines AsyncEmbedder (async encoding) with MultiLevelCache (L1+L2)
  to optimize latency and reduce model load.

  Features:
  - Cache L1 (memory): Hit rate >80% in production
  - Cache L2 (disk): Quota 5GB, TTL 72h
  - Batch optimization: Groups requests for efficiency
  - Stats tracking: Hit rate, latencies, throughput
  - Versioning: Support for invalidating cache when changing model

  Attributes:
    encoder: AsyncEmbedder instance
    cache: MultiLevelCache instance
    model_name: Model name
    cache_enabled: Whether cache is globally enabled
    _stats: Accumulated statistics
  """

  def __init__(
    self,
    encoder: AsyncEmbedder,
    cache_enabled: bool = True,
    l1_max_size: int = 1000,
    l2_max_size_gb: float = 5.0,
    l2_ttl_hours: int = 72
  ):
    """
    Init CachedEmbedder.

    Args:
      encoder: AsyncEmbedder instance
      cache_enabled: Whether to enable cache (False for debug)
      l1_max_size: Maximum L1 cache items
      l2_max_size_gb: Maximum L2 quota (GB)
      l2_ttl_hours: TTL for L2 items
    """
    self.encoder = encoder
    self.model_name = encoder.model_name
    self.cache_enabled = cache_enabled

    self.cache: Optional[MultiLevelCache]
    if cache_enabled:
      self.cache = MultiLevelCache(
        l1_max_size=l1_max_size,
        l2_max_size_gb=l2_max_size_gb,
        l2_ttl_hours=l2_ttl_hours
      )
    else:
      self.cache = None

    self._total_requests = 0
    self._cache_hits = 0
    self._latencies: List[float] = []

    logger.info(
      "cached_embedder_initialized",
      model=self.model_name,
      cache_enabled=cache_enabled,
      l1_max=l1_max_size,
      l2_max_gb=l2_max_size_gb
    )

  async def encode(
    self,
    request: EmbeddingRequest
  ) -> EmbeddingResponse:
    """
    Encode text with cache.

    Pipeline:
    1. Check cache (if enabled)
    2. Generate embedding (if cache miss)
    3. Store to cache
    4. Return response with metadata

    Args:
      request: EmbeddingRequest

    Returns:
      EmbeddingResponse with embedding and stats
    """
    start = time.time()
    cache_hit = False

    if self.cache_enabled and self.cache is not None and request.use_cache:
      cache = self.cache
      cached = await cache.get(
        text=request.text,
        model=request.model,
        version=request.cache_version
      )

      if cached is not None:
        cache_hit = True
        embedding = cached
        logger.debug(
          "cache_hit",
          model=request.model,
          text_len=len(request.text)
        )
      else:
        embedding = await self.encoder.encode_async(
          text=request.text,
          normalize=request.normalize
        )

        await cache.put(
          text=request.text,
          model=request.model,
          embedding=embedding,
          version=request.cache_version
        )

        logger.debug(
          "cache_miss",
          model=request.model,
          text_len=len(request.text)
        )
    else:
      embedding = await self.encoder.encode_async(
        text=request.text,
        normalize=request.normalize
      )

    latency_ms = (time.time() - start) * 1000

    self._total_requests += 1
    if cache_hit:
      self._cache_hits += 1
    self._latencies.append(latency_ms)

    if len(self._latencies) > 1000:
      self._latencies = self._latencies[-1000:]

    ops, hits, misses = _get_metrics()
    if ops:
      ops.labels(operation="encode").inc()
    if cache_hit and hits:
      hits.inc()
    elif not cache_hit and misses:
      misses.inc()

    return EmbeddingResponse(
      embedding=embedding,
      dimensions=len(embedding),
      model=request.model,
      normalized=request.normalize,
      cache_hit=cache_hit,
      latency_ms=latency_ms
    )

  async def _batch_with_cache(self, request: "BatchEmbeddingRequest") -> tuple:
    """Resolve embeddings using cache, generating only for misses. Returns (embeddings, cache_hits)."""
    cache = self.cache
    assert cache is not None  # nosec B101 — caller guards with self.cache_enabled and self.cache is not None
    to_generate = []
    cached_embeddings = {}
    cache_hits = 0

    for i, text in enumerate(request.texts):
      cached = await cache.get(text=text, model=request.model, version="v1")
      if cached is not None:
        cached_embeddings[i] = cached
        cache_hits += 1
      else:
        to_generate.append((i, text))

    if to_generate:
      texts_to_gen = [text for _, text in to_generate]
      new_embeddings = await self.encoder.encode_batch_async(
        texts=texts_to_gen, normalize=request.normalize, batch_size=request.batch_size
      )
      for (idx, text), embedding in zip(to_generate, new_embeddings):
        await cache.put(text=text, model=request.model, embedding=embedding, version="v1")
        cached_embeddings[idx] = embedding

    embeddings = [cached_embeddings[i] for i in range(len(request.texts))]
    return embeddings, cache_hits

  async def _batch_without_cache(self, request: "BatchEmbeddingRequest") -> tuple:
    """Generate all embeddings directly without cache. Returns (embeddings, cache_hits=0)."""
    embeddings = await self.encoder.encode_batch_async(
      texts=request.texts, normalize=request.normalize, batch_size=request.batch_size
    )
    return embeddings, 0

  def _batch_update_stats(self, count: int, cache_hits: int, total_latency_ms: float, avg_latency_ms: float) -> None:
    """Update internal counters and trim latency window."""
    self._total_requests += count
    self._cache_hits += cache_hits
    self._latencies.extend([avg_latency_ms] * count)
    if len(self._latencies) > 1000:
      self._latencies = self._latencies[-1000:]

  def _batch_emit_metrics(self, count: int, cache_hits: int) -> None:
    """Emit Prometheus metrics for a batch encode."""
    ops, hits, misses = _get_metrics()
    if ops:
      ops.labels(operation="batch_encode").inc()
    if hits and cache_hits > 0:
      for _ in range(cache_hits):
        hits.inc()
    if misses and cache_hits < count:
      for _ in range(count - cache_hits):
        misses.inc()

  async def encode_batch(
    self,
    request: "BatchEmbeddingRequest"
  ) -> "BatchEmbeddingResponse":
    """
    Encode batch with cache optimization.

    Pipeline:
    1. Check cache for each text
    2. Generate embeddings only for cache misses (batch)
    3. Store new embeddings to cache
    4. Return batch response

    Args:
      request: BatchEmbeddingRequest

    Returns:
      BatchEmbeddingResponse with embeddings and stats
    """
    start = time.time()

    if self.cache_enabled and self.cache is not None and request.use_cache:
      embeddings, cache_hits = await self._batch_with_cache(request)
    else:
      embeddings, cache_hits = await self._batch_without_cache(request)

    total_latency_ms = (time.time() - start) * 1000
    avg_latency_ms = total_latency_ms / len(request.texts)

    self._batch_update_stats(len(request.texts), cache_hits, total_latency_ms, avg_latency_ms)

    logger.info(
      "batch_encode_completed",
      model=request.model,
      count=len(request.texts),
      cache_hits=cache_hits,
      total_latency_ms=total_latency_ms,
      avg_latency_ms=avg_latency_ms
    )

    self._batch_emit_metrics(len(request.texts), cache_hits)

    return BatchEmbeddingResponse(
      embeddings=embeddings,
      count=len(embeddings),
      cache_hits=cache_hits,
      total_latency_ms=total_latency_ms,
      avg_latency_ms=avg_latency_ms
    )

  def get_stats(self) -> EncoderStats:
    """
    Get accumulated encoder statistics.

    Returns:
      EncoderStats with hit rate, latencies, etc.
    """
    hit_rate = self._cache_hits / self._total_requests if self._total_requests > 0 else 0.0

    if self._latencies:
      sorted_latencies = sorted(self._latencies)
      p90_idx = int(len(sorted_latencies) * 0.9)
      p99_idx = int(len(sorted_latencies) * 0.99)

      avg_latency = sum(self._latencies) / len(self._latencies)
      p90_latency = sorted_latencies[p90_idx]
      p99_latency = sorted_latencies[p99_idx]
    else:
      avg_latency = 0.0
      p90_latency = 0.0
      p99_latency = 0.0

    return EncoderStats(
      model_name=self.model_name,
      device=self.encoder.device,
      total_encodings=self._total_requests,
      total_requests=self._total_requests,
      cache_hits=self._cache_hits,
      cache_misses=self._total_requests - self._cache_hits,
      cache_hit_rate=hit_rate,
      avg_latency_ms=avg_latency,
      p90_latency_ms=p90_latency,
      p99_latency_ms=p99_latency
    )

  async def clear_cache(self):
    """Clear the entire cache (L1 + L2)"""
    if self.cache:
      await self.cache.clear()
      logger.info("cache_cleared", model=self.model_name)

  async def shutdown(self):
    """Graceful shutdown"""
    if self.cache:
      await self.cache.shutdown()
    await self.encoder.shutdown()
    logger.info("cached_embedder_shutdown", model=self.model_name)
