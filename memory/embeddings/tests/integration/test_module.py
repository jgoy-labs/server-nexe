"""
────────────────────────────────────
Server Nexe
Version: 0.8
Author: Jordi Goy 
Location: memory/embeddings/tests/integration/test_module.py
Description: Tests d'integració per EmbeddingsModule.

www.jgoy.net · https://server-nexe.org
────────────────────────────────────
"""

import pytest
from unittest.mock import Mock, patch
import numpy as np

from memory.embeddings.module import EmbeddingsModule
from memory.embeddings.core.interfaces import (
  EmbeddingRequest,
  BatchEmbeddingRequest,
)
from memory.embeddings.core.async_encoder import AsyncEmbedder

pytestmark = pytest.mark.integration

@pytest.fixture
def mock_sentence_transformer():
  """
  Mock SentenceTransformer per tests.

  IMPORTANT: encode() ha de retornar:
  - Single text: 1D array (768,)
  - Batch: 2D array (N, 768)
  """
  mock = Mock()

  def mock_encode(text_or_texts, **kwargs):
    if isinstance(text_or_texts, list):
      return np.random.rand(len(text_or_texts), 768).astype(np.float32)
    else:
      return np.random.rand(768).astype(np.float32)

  mock.encode.side_effect = mock_encode
  return mock

@pytest.fixture
async def embeddings_module(mock_sentence_transformer):
  """
  Fixture: EmbeddingsModule amb SentenceTransformer mockat.

  NOTA: El mock ha de mantenir-se durant tot el test perquè
  el model es carrega lazy durant encode().
  """
  EmbeddingsModule._instance = None
  EmbeddingsModule._initialized = False
  AsyncEmbedder._instances.clear()

  module = EmbeddingsModule.get_instance()

  with patch('sentence_transformers.SentenceTransformer',
        return_value=mock_sentence_transformer):
    await module.initialize(config={
      "model_name": "test-model",
      "device": "cpu",
      "cache_enabled": True,
      "l1_max_size": 10,
      "l2_max_size_gb": 0.001,
      "max_chunk_size": 150
    })

    yield module

  await module.shutdown()
  EmbeddingsModule._instance = None
  EmbeddingsModule._initialized = False
  AsyncEmbedder._instances.clear()

@pytest.mark.asyncio
async def test_singleton_pattern():
  """
  Test 1: EmbeddingsModule és Singleton.

  Checks:
  - get_instance() retorna mateixa instància
  """
  EmbeddingsModule._instance = None

  module1 = EmbeddingsModule.get_instance()
  module2 = EmbeddingsModule.get_instance()

  assert module1 is module2, "Hauria de retornar mateixa instància"

  EmbeddingsModule._instance = None

@pytest.mark.asyncio
async def test_initialize(embeddings_module):
  """
  Test 2: Initialize configura tots els components.

  Checks:
  - _cached_embedder creat
  - _chunker creat
  - _initialized = True
  """
  assert embeddings_module._initialized, "Hauria d'estar inicialitzat"
  assert embeddings_module._cached_embedder is not None, "CachedEmbedder hauria d'existir"
  assert embeddings_module._chunker is not None, "Chunker hauria d'existir"

@pytest.mark.asyncio
async def test_encode_single(embeddings_module):
  """
  Test 3: encode() retorna embedding correcte.

  Checks:
  - EmbeddingResponse complet
  - embedding amb dimensions correctes
  """
  request = EmbeddingRequest(text="hello world", use_cache=True)

  response = await embeddings_module.encode(request)

  assert len(response.embedding) == 768, "Embedding hauria de tenir 768 dims"
  assert response.dimensions == 768
  assert response.model in ["test-model", "paraphrase-multilingual-MiniLM-L12-v2"]
  assert response.latency_ms >= 0

@pytest.mark.asyncio
async def test_encode_batch(embeddings_module):
  """
  Test 4: encode_batch() retorna batch d'embeddings.

  Checks:
  - BatchEmbeddingResponse amb count correcte
  - embeddings en ordre correcte
  """
  import uuid
  unique_id = uuid.uuid4().hex[:8]
  request = BatchEmbeddingRequest(
    texts=[f"batch_text1_{unique_id}", f"batch_text2_{unique_id}", f"batch_text3_{unique_id}"],
    use_cache=True
  )

  response = await embeddings_module.encode_batch(request)

  assert response.count == 3, "Hauria de retornar 3 embeddings"
  assert len(response.embeddings) == 3
  assert all(len(emb) == 768 for emb in response.embeddings)

@pytest.mark.asyncio
async def test_chunk_document(embeddings_module):
  """
  Test 5: chunk_document() retorna chunks correctes.

  Checks:
  - ChunkedDocument amb metadata
  - Chunks enumerats correctament
  """
  content = """
Títol del Document

Aquest és el primer paràgraf amb contingut suficient.

Aquest és el segon paràgraf també amb contingut adequat.
  """.strip()

  result = await embeddings_module.chunk_document(content, document_id="doc_test")

  assert result.document_id == "doc_test"
  assert result.chunk_count > 0, "Hauria de generar chunks"
  assert result.original_length == len(content)
  assert all(chunk.chunk_index == i for i, chunk in enumerate(result.chunks))

@pytest.mark.asyncio
async def test_get_stats(embeddings_module):
  """
  Test 6: get_stats() retorna estadístiques correctes.

  Checks:
  - EncoderStats amb hit rate, latencies
  """
  for i in range(3):
    request = EmbeddingRequest(text=f"text_{i}", use_cache=True)
    await embeddings_module.encode(request)

  stats = embeddings_module.get_stats()

  assert stats.total_encodings == 3, "Hauria de tenir 3 encodings"
  assert stats.model_name == "test-model"
  assert stats.device == "cpu"
  assert stats.avg_latency_ms >= 0

@pytest.mark.asyncio
async def test_clear_cache(embeddings_module):
  """
  Test 7: clear_cache() neteja el cache.

  Checks:
  - Després de clear, cache hits canvien
  """
  import uuid
  unique_text = f"test_clear_cache_{uuid.uuid4().hex[:8]}"
  request = EmbeddingRequest(text=unique_text, use_cache=True)

  response1 = await embeddings_module.encode(request)
  assert not response1.cache_hit

  response2 = await embeddings_module.encode(request)
  assert response2.cache_hit

  await embeddings_module.clear_cache()

  response3 = await embeddings_module.encode(request)
  assert not response3.cache_hit

@pytest.mark.asyncio
async def test_get_health(embeddings_module):
  """
  Test 8: get_health() retorna estat correcte.

  Checks:
  - status, checks, metadata
  """
  health = embeddings_module.get_health()

  assert "status" in health
  assert "checks" in health
  assert isinstance(health["checks"], list)

@pytest.mark.asyncio
async def test_get_info(embeddings_module):
  """
  Test 9: get_info() retorna metadata completa.

  Checks:
  - module_id, name, version
  - config, stats
  """
  info = embeddings_module.get_info()

  assert "module_id" in info
  assert "name" in info
  assert "version" in info
  assert info["initialized"] == True
  assert "config" in info
  assert "stats" in info

@pytest.mark.asyncio
async def test_not_initialized_error():
  """
  Test 10: Cridar encode() abans de initialize() → RuntimeError.

  Checks:
  - RuntimeError si no inicialitzat
  """
  EmbeddingsModule._instance = None
  module = EmbeddingsModule.get_instance()

  request = EmbeddingRequest(text="test")

  with pytest.raises(RuntimeError, match="not.?initialized|no inicialitzat"):
    await module.encode(request)

  EmbeddingsModule._instance = None

@pytest.mark.asyncio
async def test_shutdown(embeddings_module):
  """
  Test 11: shutdown() neteja correctament.

  Checks:
  - _initialized = False
  - components = None
  """
  await embeddings_module.shutdown()

  assert not embeddings_module._initialized
  assert embeddings_module._cached_embedder is None
  assert embeddings_module._chunker is None

"""
Test Coverage EmbeddingsModule:
✅ test_singleton_pattern - Singleton correcte
✅ test_initialize - Inicialització components
✅ test_encode_single - Single embedding
✅ test_encode_batch - Batch embeddings
✅ test_chunk_document - Chunking funcional
✅ test_get_stats - Estadístiques
✅ test_clear_cache - Clear cache
✅ test_get_health - Health checks
✅ test_get_info - Module info
✅ test_not_initialized_error - Error handling
✅ test_shutdown - Graceful shutdown

Total: 11 test cases
Target coverage: >85%
"""
