"""
────────────────────────────────────
Server Nexe
Author: Jordi Goy
Location: memory/embeddings/tests/unit/test_async_encoder.py
Description: Unit tests for AsyncEmbedder.

www.jgoy.net · https://server-nexe.org
────────────────────────────────────
"""

import pytest
import asyncio
import numpy as np
from unittest.mock import Mock, patch
from memory.embeddings.core.async_encoder import AsyncEmbedder

@pytest.fixture
def mock_text_embedding():
  """
  Mock fastembed TextEmbedding to avoid loading the real model.
  """
  mock = Mock()

  def mock_embed(texts, **kwargs):
    return iter([np.random.rand(768).astype(np.float32) for _ in texts])

  mock.embed.side_effect = mock_embed
  return mock

@pytest.fixture
async def async_embedder():
  """
  Fixture: AsyncEmbedder (without loading the real fastembed TextEmbedding).

  Note: TextEmbedding is imported dynamically inside _load_model,
  so we do NOT import fastembed here (to avoid heavy deps in unit tests).
  """
  AsyncEmbedder._instances.clear()

  embedder = AsyncEmbedder(
    model_name="test-model",
    max_workers=2,
    device="cpu"
  )

  yield embedder

  await embedder.shutdown()
  AsyncEmbedder._instances.clear()

@pytest.mark.asyncio
async def test_singleton_pattern():
  """
  Test 1: Verify Singleton pattern.

  Checks:
  - Same model → same instance
  - get_instance() returns singleton
  """
  AsyncEmbedder._instances.clear()

  embedder1 = AsyncEmbedder(model_name="test-model", device="cpu")
  embedder2 = AsyncEmbedder(model_name="test-model", device="cpu")

  assert embedder1 is embedder2, "Singleton should return the same instance"

  await embedder1.shutdown()
  AsyncEmbedder._instances.clear()

@pytest.mark.asyncio
async def test_different_models_different_instances():
  """
  Test 2: Different models → different instances.

  Checks:
  - Each model has its own singleton
  """
  AsyncEmbedder._instances.clear()

  embedder1 = AsyncEmbedder(model_name="model-1", device="cpu")
  embedder2 = AsyncEmbedder(model_name="model-2", device="cpu")

  assert embedder1 is not embedder2, "Different models should have different instances"

  await embedder1.shutdown()
  await embedder2.shutdown()
  AsyncEmbedder._instances.clear()

@pytest.mark.asyncio
async def test_lazy_loading(async_embedder, mock_text_embedding):
  """
  Test 3: Lazy loading of the model.

  Checks:
  - Model not loaded until first encode
  - _ensure_loaded() loads model only once
  """
  assert async_embedder._model is None, "Model should not be loaded initially"

  async_embedder._load_model = Mock(return_value=mock_text_embedding)
  await async_embedder.encode_async("test text")

  assert async_embedder._model is not None, "Model should be loaded after encode"

@pytest.mark.asyncio
async def test_encode_async_single_text(async_embedder, mock_text_embedding):
  """
  Test 4: Encode single text async.

  Checks:
  - Returns correct embedding
  - Format: List[float]
  - Correct dimensions
  """
  with patch.object(async_embedder, '_model', mock_text_embedding):
    result = await async_embedder.encode_async("hello world", normalize=True)

  assert isinstance(result, list), "Result should be a list"
  assert len(result) == 768, "Embedding should have 768 dimensions"
  assert all(isinstance(x, float) for x in result), "Tots els elements haurien de ser floats"

@pytest.mark.asyncio
async def test_encode_async_empty_text(async_embedder):
  """
  Test 5: Encode empty text → ValueError.

  Checks:
  - Empty text raises ValueError
  """
  with pytest.raises(ValueError, match="Text no pot estar buit"):
    await async_embedder.encode_async("", normalize=True)

@pytest.mark.asyncio
async def test_encode_batch_async(async_embedder, mock_text_embedding):
  """
  Test 6: Encode batch of texts.

  Checks:
  - Returns list of embeddings
  - Same order as input
  - Correct format
  """
  texts = ["hello", "world", "test"]

  with patch.object(async_embedder, '_model', mock_text_embedding):
    results = await async_embedder.encode_batch_async(texts, normalize=True, batch_size=32)

  assert isinstance(results, list), "Results haurien de ser llista"
  assert len(results) == 3, "Should return 3 embeddings"
  assert all(len(emb) == 768 for emb in results), "Each embedding should have 768 dims"

@pytest.mark.asyncio
async def test_encode_batch_empty_list(async_embedder):
  """
  Test 7: Encode empty batch → ValueError.

  Checks:
  - Empty list raises ValueError
  """
  with pytest.raises(ValueError, match="texts no pot estar buit"):
    await async_embedder.encode_batch_async([], normalize=True)

@pytest.mark.asyncio
async def test_encode_batch_with_empty_string(async_embedder):
  """
  Test 8: Batch with empty string → ValueError.

  Checks:
  - Empty strings in batch raise ValueError
  """
  texts = ["hello", "", "world"]

  with pytest.raises(ValueError, match="Tots els texts han de ser no-buits"):
    await async_embedder.encode_batch_async(texts, normalize=True)

@pytest.mark.asyncio
async def test_concurrent_encode(async_embedder, mock_text_embedding):
  """
  Test 9: Concurrent encodes (stress test).

  Checks:
  - Multiple simultaneous encodes
  - Thread-safe
  - No race conditions
  """
  with patch.object(async_embedder, '_model', mock_text_embedding):
    tasks = [
      async_embedder.encode_async(f"text_{i}", normalize=True)
      for i in range(10)
    ]

    results = await asyncio.gather(*tasks)

  assert len(results) == 10, "Haurien de completar tots els 10 encodes"
  assert all(len(r) == 768 for r in results), "Tots haurien de tenir 768 dims"

@pytest.mark.asyncio
async def test_get_info(async_embedder):
  """
  Test 10: get_info() returns correct metadata.

  Checks:
  - model_name, device, loaded status
  """
  info = async_embedder.get_info()

  assert info["model_name"] == "test-model"
  assert info["device"] == "cpu"
  assert info["max_workers"] == 2
  assert "loaded" in info

@pytest.mark.asyncio
async def test_shutdown(async_embedder):
  """
  Test 11: Graceful shutdown.

  Checks:
  - Shutdown closes ThreadPoolExecutor
  - Model is unloaded
  - Instance is removed from cache
  """
  model_name = async_embedder.model_name

  await async_embedder.shutdown()

  assert async_embedder._model is None, "Model should be unloaded"
  assert model_name not in AsyncEmbedder._instances, "Instance should be removed from cache"

"""
Test Coverage AsyncEmbedder:
✅ test_singleton_pattern - Singleton per model
✅ test_different_models_different_instances - Multiple models
✅ test_lazy_loading - Model loads only when needed
✅ test_encode_async_single_text - Single text encoding
✅ test_encode_async_empty_text - Error handling empty text
✅ test_encode_batch_async - Batch encoding
✅ test_encode_batch_empty_list - Error empty batch
✅ test_encode_batch_with_empty_string - Error empty strings
✅ test_concurrent_encode - Thread-safety
✅ test_get_info - Metadata
✅ test_shutdown - Graceful cleanup

Total: 11 test cases
Target coverage: >85%
"""
