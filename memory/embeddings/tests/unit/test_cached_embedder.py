"""
────────────────────────────────────
Server Nexe
Version: 0.8
Author: Jordi Goy 
Location: memory/embeddings/tests/unit/test_cached_embedder.py
Description: Tests unitaris per CachedEmbedder.

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
  """Directori temporal per L2 cache"""
  temp_dir = tempfile.mkdtemp()
  yield Path(temp_dir)
  shutil.rmtree(temp_dir, ignore_errors=True)

@pytest.fixture
async def mock_async_embedder():
  """Mock AsyncEmbedder per tests"""
  mock = Mock(spec=AsyncEmbedder)
  mock.model_name = "test-model"
  mock.device = "cpu"

  async def mock_encode(text, normalize=True):
    hash_val = hash(text) % 384
    return [float(hash_val + i) for i in range(384)]

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
  Fixture: CachedEmbedder amb mock encoder i cache temporal.
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
  Test 1: Cache hit en segon request.

  Checks:
  - Primer request: cache miss
  - Segon request: cache hit
  - Mateix embedding retornat
  """
  request = EmbeddingRequest(text="hello world", use_cache=True)

  response1 = await cached_embedder.encode(request)
  assert not response1.cache_hit, "Primer request hauria de ser cache miss"

  response2 = await cached_embedder.encode(request)
  assert response2.cache_hit, "Segon request hauria de ser cache hit"

  assert response1.embedding == response2.embedding, "Embeddings haurien de ser iguals"

@pytest.mark.asyncio
async def test_cache_miss(cached_embedder):
  """
  Test 2: Cache miss per texts diferents.

  Checks:
  - Cada text diferent és cache miss
  """
  request1 = EmbeddingRequest(text="hello", use_cache=True)
  request2 = EmbeddingRequest(text="world", use_cache=True)

  response1 = await cached_embedder.encode(request1)
  response2 = await cached_embedder.encode(request2)

  assert not response1.cache_hit, "Primer text hauria de ser miss"
  assert not response2.cache_hit, "Segon text (diferent) hauria de ser miss"
  assert response1.embedding != response2.embedding, "Embeddings diferents per texts diferents"

@pytest.mark.asyncio
async def test_cache_disabled(mock_async_embedder, temp_cache_dir):
  """
  Test 3: Cache disabled → sempre genera embedding.

  Checks:
  - Amb cache_enabled=False no usa cache
  - Sempre cache_hit=False
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
  Test 4: Batch amb mix cache hits/misses.

  Checks:
  - Només genera embeddings per cache misses
  - Cache hits optimitzats
  """
  request1 = BatchEmbeddingRequest(
    texts=["text1", "text2", "text3"],
    use_cache=True
  )

  response1 = await cached_embedder.encode_batch(request1)
  assert response1.cache_hits == 0, "Primer batch tot misses"
  assert response1.count == 3

  request2 = BatchEmbeddingRequest(
    texts=["text1", "text2", "text4"],
    use_cache=True
  )

  response2 = await cached_embedder.encode_batch(request2)
  assert response2.cache_hits == 2, "Hauria de tenir 2 cache hits"
  assert response2.count == 3

@pytest.mark.asyncio
async def test_stats_tracking(cached_embedder):
  """
  Test 5: Stats tracking correcte.

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

  assert stats.total_encodings == 8, "Hauria de tenir 8 requests totals"
  assert stats.cache_hit_rate == 3/8, "Hit rate hauria de ser 3/8"
  assert stats.avg_latency_ms >= 0, "Latency hauria de ser >= 0"

@pytest.mark.asyncio
async def test_clear_cache(cached_embedder):
  """
  Test 6: Clear cache elimina tot.

  Checks:
  - Després de clear, cache hits = 0
  """
  request = EmbeddingRequest(text="test", use_cache=True)
  response1 = await cached_embedder.encode(request)
  assert not response1.cache_hit

  response2 = await cached_embedder.encode(request)
  assert response2.cache_hit

  await cached_embedder.clear_cache()

  response3 = await cached_embedder.encode(request)
  assert not response3.cache_hit, "Després de clear hauria de ser miss"

@pytest.mark.asyncio
async def test_response_metadata(cached_embedder):
  """
  Test 7: Response conté metadata correcte.

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

  assert response.dimensions == 384, "Dimensions hauria de ser 384"
  assert response.model == "test-model"
  assert response.normalized == True
  assert response.latency_ms > 0, "Latency hauria de ser > 0"
  assert len(response.embedding) == 384

@pytest.mark.asyncio
async def test_batch_response_stats(cached_embedder):
  """
  Test 8: Batch response amb stats correctes.

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
✅ test_cache_hit - Cache hit funcional
✅ test_cache_miss - Cache miss per texts diferents
✅ test_cache_disabled - Cache disabled mode
✅ test_batch_cache_optimization - Batch amb mix hits/misses
✅ test_stats_tracking - Stats correctes (hit rate, latencies)
✅ test_clear_cache - Clear cache funciona
✅ test_response_metadata - Response metadata complet
✅ test_batch_response_stats - Batch response stats

Total: 8 test cases
Target coverage: >85%
"""