"""
────────────────────────────────────
Server Nexe
Version: 0.8
Author: Jordi Goy 
Location: memory/embeddings/tests/unit/test_workflow_nodes.py
Description: Tests unitaris per workflow nodes (embedding_node, chunking_node).

www.jgoy.net · https://server-nexe.org
────────────────────────────────────
"""

import pytest
from unittest.mock import Mock
import numpy as np

from memory.embeddings.workflow.nodes import embedding_node, chunking_node
from memory.embeddings.module import EmbeddingsModule
from memory.embeddings.core.async_encoder import AsyncEmbedder

@pytest.fixture
def mock_sentence_transformer():
  """Mock SentenceTransformer"""
  mock = Mock()
  mock.encode.return_value = np.random.rand(384).astype(np.float32)
  return mock

@pytest.fixture
async def setup_module(mock_sentence_transformer):
  """
  Setup EmbeddingsModule per tests.

  NOTA: El mock es manté durant tot el test per lazy loading.
  """
  EmbeddingsModule._instance = None
  EmbeddingsModule._initialized = False
  AsyncEmbedder._instances.clear()

  module = EmbeddingsModule.get_instance()

  await module.initialize(config={"model_name": "test-model", "device": "cpu"})

  # Evitar importar sentence_transformers als unit tests (deps pesades a Linux)
  assert module._cached_embedder is not None
  module._cached_embedder.encoder._load_model = Mock(return_value=mock_sentence_transformer)

  yield module

  await module.shutdown()
  EmbeddingsModule._instance = None
  AsyncEmbedder._instances.clear()

@pytest.mark.asyncio
async def test_embedding_node(setup_module):
  """
  Test 1: embedding_node retorna format correcte.

  Checks:
  - Dict amb embedding, dimensions, cache_hit, etc.
  """
  result = await embedding_node(text="hello world", model="test-model")

  assert isinstance(result, dict), "Result hauria de ser dict"
  assert "embedding" in result
  assert "dimensions" in result
  assert "cache_hit" in result
  assert "latency_ms" in result
  assert "model" in result

  assert isinstance(result["embedding"], list)
  assert result["dimensions"] == 384
  assert isinstance(result["cache_hit"], bool)
  assert result["latency_ms"] >= 0

@pytest.mark.asyncio
async def test_embedding_node_with_params(setup_module):
  """
  Test 2: embedding_node amb paràmetres custom.

  Checks:
  - Paràmetres passats correctament
  """
  result = await embedding_node(
    text="test",
    model="test-model",
    use_cache=True,
    normalize=True,
    cache_version="v2"
  )

  assert result["model"] == "test-model"
  assert "embedding" in result

@pytest.mark.asyncio
async def test_chunking_node():
  """
  Test 3: chunking_node retorna format correcte.

  Checks:
  - Dict amb document_id, chunk_count, chunks, etc.
  """
  content = """
Títol

Paràgraf 1 amb contingut suficient.

Paràgraf 2 també amb contingut adequat.
  """.strip()

  result = await chunking_node(content=content, document_id="doc_test")

  assert isinstance(result, dict), "Result hauria de ser dict"
  assert "document_id" in result
  assert "chunk_count" in result
  assert "chunks" in result
  assert "original_length" in result
  assert "created_at" in result

  assert result["document_id"] == "doc_test"
  assert result["chunk_count"] > 0
  assert isinstance(result["chunks"], list)
  assert result["original_length"] == len(content)

@pytest.mark.asyncio
async def test_chunking_node_with_params():
  """
  Test 4: chunking_node amb paràmetres custom.

  Checks:
  - max_chunk_size, overlap, min_size passats correctament
  """
  content = "Test content amb múltiples frases. Cada frase pot ser un chunk. Això permet validar paràmetres."

  result = await chunking_node(
    content=content,
    document_id="doc_test",
    max_chunk_size=50,
    chunk_overlap=10,
    min_chunk_size=5
  )

  assert result["document_id"] == "doc_test"
  assert result["chunk_count"] > 0

@pytest.mark.asyncio
async def test_chunking_node_chunk_metadata():
  """
  Test 5: Chunks tenen metadata correcte.

  Checks:
  - chunk_id, chunk_index, char_start, char_end, etc.
  """
  content = "Paràgraf 1.\n\nParàgraf 2.\n\nParàgraf 3."

  result = await chunking_node(content=content, document_id="doc_test")

  chunks = result["chunks"]
  assert len(chunks) > 0

  for i, chunk in enumerate(chunks):
    assert "chunk_id" in chunk
    assert "chunk_index" in chunk
    assert "char_start" in chunk
    assert "char_end" in chunk
    assert "section_title" in chunk
    assert "chunk_type" in chunk

    assert chunk["chunk_index"] == i
    assert chunk["char_start"] >= 0
    assert chunk["char_end"] > chunk["char_start"]

"""
Test Coverage Workflow Nodes:
✅ test_embedding_node - Output format correcte
✅ test_embedding_node_with_params - Paràmetres custom
✅ test_chunking_node - Output format correcte
✅ test_chunking_node_with_params - Paràmetres custom
✅ test_chunking_node_chunk_metadata - Chunks metadata

Total: 5 test cases
Target coverage: >80%
"""
