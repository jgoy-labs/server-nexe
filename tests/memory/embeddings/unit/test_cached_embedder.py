"""
────────────────────────────────────
Server Nexe
Author: Jordi Goy
Location: memory/embeddings/tests/unit/test_cached_embedder.py
Description: Unit tests for CachedEmbedder.

www.jgoy.net · https://server-nexe.org
────────────────────────────────────
"""

import pytest
import tempfile
import shutil
from pathlib import Path
from unittest.mock import Mock

from memory.embeddings.core.async_encoder import AsyncEmbedder
from memory.embeddings.core.cached_embedder import CachedEmbedder
from memory.embeddings.core.interfaces import (
  EmbeddingRequest,
  BatchEmbeddingRequest,
)

@pytest.fixture
async def temp_cache_dir():
  """Temporary directory for L2 cache"""
  temp_dir = tempfile.mkdtemp()
  yield Path(temp_dir)
  shutil.rmtree(temp_dir, ignore_errors=True)

@pytest.fixture
async def mock_async_embedder():
  """Mock AsyncEmbedder for tests"""
  mock = Mock(spec=AsyncEmbedder)
  mock.model_name = "test-model"
  mock.device = "cpu"

  async def mock_encode(text, normalize=True):
    hash_val = hash(text) % 768
    return [float(hash_val + i) for i in range(768)]

  mock.encode_async = mock_encode

  async def mock_encode_batch(texts, normalize=True, batch_size=32):
    return [await mock_encode(text, normalize) for text in texts]

  mock.encode_batch_async = mock_encode_batch

  async def mock_shutdown():
    pass

  mock.shutdown = mock_shutdown

  return mock

@pytest.fixture
async def cached_embedder(mock_async_embedder, temp_cache_dir):
  """
  Fixture: CachedEmbedder with mock encoder and temporary cache.
  """
  embedder = CachedEmbedder(
    encoder=mock_async_embedder,
    cache_enabled=True,
    l1_max_size=10,
    l2_max_size_gb=0.001,
    l2_ttl_hours=1
  )

  if embedder.cache:
    embedder.cache.l2_cache_dir = temp_cache_dir

  yield embedder

  await embedder.shutdown()

@pytest.mark.asyncio
async def test_cache_hit(cached_embedder):
  """
  Test 1: Cache hit on second request.

  Checks:
  - First request: cache miss
  - Second request: cache hit
  - Same embedding returned
  """
  request = EmbeddingRequest(text="hello world", use_cache=True)

  response1 = await cached_embedder.encode(request)
  assert not response1.cache_hit, "First request should be a cache miss"

  response2 = await cached_embedder.encode(request)
  assert response2.cache_hit, "Second request should be a cache hit"

  assert response1.embedding == response2.embedding, "Embeddings should be equal"

@pytest.mark.asyncio
async def test_cache_miss(cached_embedder):
  """
  Test 2: Cache miss for different texts.

  Checks:
  - Each different text is a cache miss
  """
  request1 = EmbeddingRequest(text="hello", use_cache=True)
  request2 = EmbeddingRequest(text="world", use_cache=True)

  response1 = await cached_embedder.encode(request1)
  response2 = await cached_embedder.encode(request2)

  assert not response1.cache_hit, "First text should be a miss"
  assert not response2.cache_hit, "Second text (different) should be a miss"
  assert response1.embedding != response2.embedding, "Different embeddings for different texts"

@pytest.mark.asyncio
async def test_cache_disabled(mock_async_embedder, temp_cache_dir):
  """
  Test 3: Cache disabled → always generates embedding.

  Checks:
  - With cache_enabled=False does not use cache
  - Always cache_hit=False
  """
  embedder = CachedEmbedder(
    encoder=mock_async_embedder,
    cache_enabled=False
  )

  request = EmbeddingRequest(text="test", use_cache=True)

  response1 = await embedder.encode(request)
  response2 = await embedder.encode(request)

  assert not response1.cache_hit
  assert not response2.cache_hit

  await embedder.shutdown()

@pytest.mark.asyncio
async def test_batch_cache_optimization(cached_embedder):
  """
  Test 4: Batch with mix of cache hits/misses.

  Checks:
  - Only generates embeddings for cache misses
  - Cache hits optimized
  """
  request1 = BatchEmbeddingRequest(
    texts=["text1", "text2", "text3"],
    use_cache=True
  )

  response1 = await cached_embedder.encode_batch(request1)
  assert response1.cache_hits == 0, "First batch all misses"
  assert response1.count == 3

  request2 = BatchEmbeddingRequest(
    texts=["text1", "text2", "text4"],
    use_cache=True
  )

  response2 = await cached_embedder.encode_batch(request2)
  assert response2.cache_hits == 2, "Should have 2 cache hits"
  assert response2.count == 3

@pytest.mark.asyncio
async def test_stats_tracking(cached_embedder):
  """
  Test 5: Correct stats tracking.

  Checks:
  - total_encodings
  - cache_hit_rate
  - latencies tracking
  """
  for i in range(5):
    request = EmbeddingRequest(text=f"text_{i}", use_cache=True)
    await cached_embedder.encode(request)

  for i in range(3):
    request = EmbeddingRequest(text=f"text_{i}", use_cache=True)
    await cached_embedder.encode(request)

  stats = cached_embedder.get_stats()

  assert stats.total_encodings == 8, "Should have 8 total requests"
  assert stats.cache_hit_rate == 3/8, "Hit rate should be 3/8"
  assert stats.avg_latency_ms >= 0, "Latency should be >= 0"
  # MEM-005: EncoderStats must expose cache_hits / cache_misses (the CLI
  # `stats` subcommand reads them; without these fields it crashes).
  assert stats.cache_hits == 3, "Should report 3 cache hits"
  assert stats.cache_misses == 5, "Should report 5 cache misses"
  assert stats.cache_hits + stats.cache_misses == stats.total_requests

@pytest.mark.asyncio
async def test_clear_cache(cached_embedder):
  """
  Test 6: Clear cache removes everything.

  Checks:
  - After clear, cache hits = 0
  """
  request = EmbeddingRequest(text="test", use_cache=True)
  response1 = await cached_embedder.encode(request)
  assert not response1.cache_hit

  response2 = await cached_embedder.encode(request)
  assert response2.cache_hit

  await cached_embedder.clear_cache()

  response3 = await cached_embedder.encode(request)
  assert not response3.cache_hit, "After clear should be a miss"

@pytest.mark.asyncio
async def test_response_metadata(cached_embedder):
  """
  Test 7: Response contains correct metadata.

  Checks:
  - dimensions
  - model
  - normalized
  - latency_ms
  """
  request = EmbeddingRequest(
    text="test",
    model="test-model",
    normalize=True,
    use_cache=True
  )

  response = await cached_embedder.encode(request)

  assert response.dimensions == 768, "Dimensions should be 768"
  assert response.model == "test-model"
  assert response.normalized == True
  assert response.latency_ms > 0, "Latency should be > 0"
  assert len(response.embedding) == 768

@pytest.mark.asyncio
async def test_batch_response_stats(cached_embedder):
  """
  Test 8: Batch response with correct stats.

  Checks:
  - count
  - cache_hits
  - total_latency_ms
  - avg_latency_ms
  """
  request = BatchEmbeddingRequest(
    texts=["text1", "text2", "text3"],
    use_cache=True
  )

  response = await cached_embedder.encode_batch(request)

  assert response.count == 3
  assert response.cache_hits == 0
  assert response.total_latency_ms > 0
  assert response.avg_latency_ms > 0
  assert len(response.embeddings) == 3

"""
Test Coverage CachedEmbedder:
✅ test_cache_hit - Functional cache hit
✅ test_cache_miss - Cache miss for different texts
✅ test_cache_disabled - Cache disabled mode
✅ test_batch_cache_optimization - Batch with mix of hits/misses
✅ test_stats_tracking - Correct stats (hit rate, latencies)
✅ test_clear_cache - Clear cache works
✅ test_response_metadata - Complete response metadata
✅ test_batch_response_stats - Batch response stats

Total: 8 test cases
Target coverage: >85%
"""