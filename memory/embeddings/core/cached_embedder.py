"""
────────────────────────────────────
Server Nexe
Version: 0.8
Author: Jordi Goy 
Location: memory/embeddings/core/cached_embedder.py
Description: CachedEmbedder: Integrates AsyncEmbedder with MultiLevelCache to optimise latency.

www.jgoy.net · https://server-nexe.org
────────────────────────────────────
"""

import time
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
  Embedder amb cache multi-nivell integrat.

  Combina AsyncEmbedder (async encoding) amb MultiLevelCache (L1+L2)
  per optimitzar latència i reduir càrrega del model.

  Features:
  - Cache L1 (memòria): Hit rate >80% en producció
  - Cache L2 (disc): Quota 5GB, TTL 72h
  - Batch optimization: Agrupa requests per eficiència
  - Stats tracking: Hit rate, latencies, throughput
  - Versioning: Suport per invalidar cache al canviar model

  Attributes:
    encoder: AsyncEmbedder instance
    cache: MultiLevelCache instance
    model_name: Nom del model
    cache_enabled: Si cache activa globalment
    _stats: Estadístiques acumulades
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
      cache_enabled: Si activar cache (False per debug)
      l1_max_size: Màxim items L1 cache
      l2_max_size_gb: Quota màxima L2 (GB)
      l2_ttl_hours: TTL per items L2
    """
    self.encoder = encoder
    self.model_name = encoder.model_name
    self.cache_enabled = cache_enabled

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
    self._latencies = []

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
    Encode text amb cache.

    Pipeline:
    1. Check cache (si enabled)
    2. Generate embedding (si cache miss)
    3. Store to cache
    4. Return response amb metadata

    Args:
      request: EmbeddingRequest

    Returns:
      EmbeddingResponse amb embedding i stats
    """
    start = time.time()
    cache_hit = False

    if self.cache_enabled and request.use_cache:
      cached = await self.cache.get(
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

        await self.cache.put(
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

  async def encode_batch(
    self,
    request: BatchEmbeddingRequest
  ) -> BatchEmbeddingResponse:
    """
    Encode batch amb cache optimization.

    Pipeline:
    1. Check cache per cada text
    2. Generate embeddings només per cache misses (batch)
    3. Store nous embeddings al cache
    4. Return batch response

    Args:
      request: BatchEmbeddingRequest

    Returns:
      BatchEmbeddingResponse amb embeddings i stats
    """
    start = time.time()
    embeddings = []
    cache_hits = 0

    if self.cache_enabled and request.use_cache:
      to_generate = []
      cached_embeddings = {}

      for i, text in enumerate(request.texts):
        cached = await self.cache.get(
          text=text,
          model=request.model,
          version="v1"
        )

        if cached is not None:
          cached_embeddings[i] = cached
          cache_hits += 1
        else:
          to_generate.append((i, text))

      if to_generate:
        texts_to_gen = [text for _, text in to_generate]
        new_embeddings = await self.encoder.encode_batch_async(
          texts=texts_to_gen,
          normalize=request.normalize,
          batch_size=request.batch_size
        )

        for (idx, text), embedding in zip(to_generate, new_embeddings):
          await self.cache.put(
            text=text,
            model=request.model,
            embedding=embedding,
            version="v1"
          )
          cached_embeddings[idx] = embedding

      embeddings = [cached_embeddings[i] for i in range(len(request.texts))]

    else:
      embeddings = await self.encoder.encode_batch_async(
        texts=request.texts,
        normalize=request.normalize,
        batch_size=request.batch_size
      )

    total_latency_ms = (time.time() - start) * 1000
    avg_latency_ms = total_latency_ms / len(request.texts)

    self._total_requests += len(request.texts)
    self._cache_hits += cache_hits
    self._latencies.extend([avg_latency_ms] * len(request.texts))

    if len(self._latencies) > 1000:
      self._latencies = self._latencies[-1000:]

    logger.info(
      "batch_encode_completed",
      model=request.model,
      count=len(request.texts),
      cache_hits=cache_hits,
      total_latency_ms=total_latency_ms,
      avg_latency_ms=avg_latency_ms
    )

    ops, hits, misses = _get_metrics()
    if ops:
      ops.labels(operation="batch_encode").inc()
    if hits and cache_hits > 0:
      for _ in range(cache_hits):
        hits.inc()
    if misses and cache_hits < len(request.texts):
      for _ in range(len(request.texts) - cache_hits):
        misses.inc()

    return BatchEmbeddingResponse(
      embeddings=embeddings,
      count=len(embeddings),
      cache_hits=cache_hits,
      total_latency_ms=total_latency_ms,
      avg_latency_ms=avg_latency_ms
    )

  def get_stats(self) -> EncoderStats:
    """
    Get estadístiques acumulades del encoder.

    Returns:
      EncoderStats amb hit rate, latencies, etc.
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
      cache_hit_rate=hit_rate,
      avg_latency_ms=avg_latency,
      p90_latency_ms=p90_latency,
      p99_latency_ms=p99_latency
    )

  async def clear_cache(self):
    """Clear tot el cache (L1 + L2)"""
    if self.cache:
      await self.cache.clear()
      logger.info("cache_cleared", model=self.model_name)

  async def shutdown(self):
    """Graceful shutdown"""
    if self.cache:
      await self.cache.shutdown()
    await self.encoder.shutdown()
    logger.info("cached_embedder_shutdown", model=self.model_name)
