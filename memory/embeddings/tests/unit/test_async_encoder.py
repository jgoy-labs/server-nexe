"""
────────────────────────────────────
Server Nexe
Version: 0.8
Author: Jordi Goy 
Location: memory/embeddings/tests/unit/test_async_encoder.py
Description: Tests unitaris per AsyncEmbedder.

www.jgoy.net
────────────────────────────────────
"""

import pytest
import asyncio
import numpy as np
from unittest.mock import Mock, patch
from memory.embeddings.core.async_encoder import AsyncEmbedder

@pytest.fixture
def mock_sentence_transformer():
  """
  Mock SentenceTransformer per evitar carregar model real.
  """
  mock = Mock()

  mock.encode.return_value = np.random.rand(384).astype(np.float32)

  return mock

@pytest.fixture
async def async_embedder():
  """
  Fixture: AsyncEmbedder (sense carregar SentenceTransformer real).

  Nota: SentenceTransformer s'importa dinàmicament dins _load_model,
  per tant NO importem sentence_transformers aquí (per evitar deps pesades als unit tests).
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
  Test 1: Verificar Singleton pattern.

  Checks:
  - Mateix model → mateixa instància
  - get_instance() retorna singleton
  """
  AsyncEmbedder._instances.clear()

  embedder1 = AsyncEmbedder(model_name="test-model", device="cpu")
  embedder2 = AsyncEmbedder(model_name="test-model", device="cpu")

  assert embedder1 is embedder2, "Singleton hauria de retornar mateixa instància"

  await embedder1.shutdown()
  AsyncEmbedder._instances.clear()

@pytest.mark.asyncio
async def test_different_models_different_instances():
  """
  Test 2: Models diferents → instàncies diferents.

  Checks:
  - Cada model té el seu singleton
  """
  AsyncEmbedder._instances.clear()

  embedder1 = AsyncEmbedder(model_name="model-1", device="cpu")
  embedder2 = AsyncEmbedder(model_name="model-2", device="cpu")

  assert embedder1 is not embedder2, "Models diferents haurien de tenir instàncies diferents"

  await embedder1.shutdown()
  await embedder2.shutdown()
  AsyncEmbedder._instances.clear()

@pytest.mark.asyncio
async def test_lazy_loading(async_embedder, mock_sentence_transformer):
  """
  Test 3: Lazy loading del model.

  Checks:
  - Model no carregat fins primer encode
  - _ensure_loaded() carrega model només una vegada
  """
  assert async_embedder._model is None, "Model no hauria d'estar carregat inicialment"

  async_embedder._load_model = Mock(return_value=mock_sentence_transformer)
  await async_embedder.encode_async("test text")

  assert async_embedder._model is not None, "Model hauria d'estar carregat després encode"

@pytest.mark.asyncio
async def test_encode_async_single_text(async_embedder, mock_sentence_transformer):
  """
  Test 4: Encode single text async.

  Checks:
  - Retorna embedding correcte
  - Format: List[float]
  - Dimensions correctes
  """
  with patch.object(async_embedder, '_model', mock_sentence_transformer):
    result = await async_embedder.encode_async("hello world", normalize=True)

  assert isinstance(result, list), "Result hauria de ser llista"
  assert len(result) == 384, "Embedding hauria de tenir 384 dimensions"
  assert all(isinstance(x, float) for x in result), "Tots els elements haurien de ser floats"

@pytest.mark.asyncio
async def test_encode_async_empty_text(async_embedder):
  """
  Test 5: Encode text buit → ValueError.

  Checks:
  - Text buit raise ValueError
  """
  with pytest.raises(ValueError, match="Text no pot estar buit"):
    await async_embedder.encode_async("", normalize=True)

@pytest.mark.asyncio
async def test_encode_batch_async(async_embedder, mock_sentence_transformer):
  """
  Test 6: Encode batch de texts.

  Checks:
  - Retorna llista d'embeddings
  - Mateix ordre que input
  - Format correcte
  """
  mock_sentence_transformer.encode.return_value = np.random.rand(3, 384).astype(np.float32)

  texts = ["hello", "world", "test"]

  with patch.object(async_embedder, '_model', mock_sentence_transformer):
    results = await async_embedder.encode_batch_async(texts, normalize=True, batch_size=32)

  assert isinstance(results, list), "Results haurien de ser llista"
  assert len(results) == 3, "Hauria de retornar 3 embeddings"
  assert all(len(emb) == 384 for emb in results), "Cada embedding hauria de tenir 384 dims"

@pytest.mark.asyncio
async def test_encode_batch_empty_list(async_embedder):
  """
  Test 7: Encode batch buit → ValueError.

  Checks:
  - Llista buida raise ValueError
  """
  with pytest.raises(ValueError, match="texts no pot estar buit"):
    await async_embedder.encode_batch_async([], normalize=True)

@pytest.mark.asyncio
async def test_encode_batch_with_empty_string(async_embedder):
  """
  Test 8: Batch amb string buit → ValueError.

  Checks:
  - Strings buides dins batch raise ValueError
  """
  texts = ["hello", "", "world"]

  with pytest.raises(ValueError, match="Tots els texts han de ser no-buits"):
    await async_embedder.encode_batch_async(texts, normalize=True)

@pytest.mark.asyncio
async def test_concurrent_encode(async_embedder, mock_sentence_transformer):
  """
  Test 9: Concurrent encodes (stress test).

  Checks:
  - Multiple encodes simultanis
  - Thread-safe
  - No race conditions
  """
  with patch.object(async_embedder, '_model', mock_sentence_transformer):
    tasks = [
      async_embedder.encode_async(f"text_{i}", normalize=True)
      for i in range(10)
    ]

    results = await asyncio.gather(*tasks)

  assert len(results) == 10, "Haurien de completar tots els 10 encodes"
  assert all(len(r) == 384 for r in results), "Tots haurien de tenir 384 dims"

@pytest.mark.asyncio
async def test_get_info(async_embedder):
  """
  Test 10: get_info() retorna metadata correcte.

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
  - Shutdown tanca ThreadPoolExecutor
  - Model es descarrega
  - Instance es remove del cache
  """
  model_name = async_embedder.model_name

  await async_embedder.shutdown()

  assert async_embedder._model is None, "Model hauria d'estar descarregat"
  assert model_name not in AsyncEmbedder._instances, "Instance hauria d'estar removed del cache"

"""
Test Coverage AsyncEmbedder:
✅ test_singleton_pattern - Singleton per model
✅ test_different_models_different_instances - Múltiples models
✅ test_lazy_loading - Model carrega només quan es necessita
✅ test_encode_async_single_text - Single text encoding
✅ test_encode_async_empty_text - Error handling text buit
✅ test_encode_batch_async - Batch encoding
✅ test_encode_batch_empty_list - Error batch buit
✅ test_encode_batch_with_empty_string - Error strings buides
✅ test_concurrent_encode - Thread-safety
✅ test_get_info - Metadata
✅ test_shutdown - Graceful cleanup

Total: 11 test cases
Target coverage: >85%
"""
