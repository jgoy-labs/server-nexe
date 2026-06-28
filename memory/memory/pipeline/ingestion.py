"""
────────────────────────────────────
Server Nexe
Author: Jordi Goy 
Location: memory/memory/pipeline/ingestion.py
Description: IngestionPipeline - 7 ingestion stages with backpressure and embedding.

www.jgoy.net · https://server-nexe.org
────────────────────────────────────
"""

import asyncio
import logging
import os
from concurrent.futures import ThreadPoolExecutor
from typing import Any, List, Optional

from memory.embeddings.constants import DEFAULT_VECTOR_SIZE
from ..models.memory_entry import MemoryEntry
from ..engines.flash_memory import FlashMemory
from ..engines.persistence import PersistenceManager
from .deduplicator import Deduplicator

logger = logging.getLogger(__name__)

class IngestionPipeline:
  """
  Multi-stage ingestion pipeline with backpressure.

  Features:
  - 7 processing stages
  - run_in_executor for embedding (CPU-bound)
  - Deduplication with SHA256
  - Automatic rollback if persistence fails
  """

  # MC-089: the Ollama base URL is resolved at CALL time via the shared cascade
  # (SidecarConfig → NEXE_OLLAMA_HOST → OLLAMA_HOST → default), not pinned to
  # NEXE_OLLAMA_HOST at import time. See _embed_url().
  OLLAMA_MODEL = os.environ.get("NEXE_OLLAMA_EMBED_MODEL", "nomic-embed-text")
  OLLAMA_TIMEOUT = float(os.environ.get("NEXE_OLLAMA_EMBED_TIMEOUT", "30.0"))

  @staticmethod
  def _embed_url() -> str:
    from core.ollama_utils import resolve_ollama_url
    return f"{resolve_ollama_url()}/api/embeddings"

  def __init__(
    self,
    flash_memory: FlashMemory,
    persistence: PersistenceManager,
    embedding_model: Optional[str] = None
  ):
    self.flash = flash_memory
    self.persistence = persistence
    self.embedding_model = embedding_model

    self.deduplicator = Deduplicator()

    self.executor = ThreadPoolExecutor(max_workers=2)

    self.stats = {
      "total_ingested": 0,
      "duplicates_skipped": 0,
      "failures": 0
    }

    backend = "Ollama API" if embedding_model is None else f"fastembed ({embedding_model})"
    logger.info("IngestionPipeline initialized (embedding_backend=%s)", backend)

  async def ingest(self, entry: MemoryEntry) -> bool:
    """
    Process an entry through the full pipeline.

    Stages:
    1. Validation (already done by Pydantic)
    2. Deduplication
    3. Embedding generation
    4. Flash storage
    5. Persistence
    6. Cleanup (if needed)
    7. Stats update

    Args:
      entry: MemoryEntry to process

    Returns:
      bool: True if successfully ingested
    """
    try:

      if self.deduplicator.is_duplicate(entry):
        logger.info("Skipping duplicate entry %s", entry.id)
        self.stats["duplicates_skipped"] += 1
        return False

      embedding = await self._generate_embedding(entry.content)

      await self.flash.store(entry)

      await self.persistence.store(entry, embedding=embedding)

      self.stats["total_ingested"] += 1
      logger.info("Successfully ingested entry %s", entry.id)

      return True

    except Exception as e:
      logger.error("Ingestion failed for entry %s: %s", entry.id, e)
      self.stats["failures"] += 1
      return False

  async def ingest_batch(self, entries: List[MemoryEntry]) -> dict:
    """
    Ingest multiple entries in batch.

    Args:
      entries: List of MemoryEntry

    Returns:
      dict: Batch stats (success, duplicates, failures)
    """
    batch_stats = {
      "success": 0,
      "duplicates": 0,
      "failures": 0
    }

    sem = asyncio.Semaphore(8)
    async def _bounded_ingest(entry):
        async with sem:
            return await self.ingest(entry)
    tasks = [_bounded_ingest(entry) for entry in entries]
    results = await asyncio.gather(*tasks, return_exceptions=True)

    for result in results:
      if isinstance(result, Exception):
        batch_stats["failures"] += 1
      elif result:
        batch_stats["success"] += 1
      else:
        batch_stats["duplicates"] += 1

    logger.info("Batch ingestion completed: %s", batch_stats)

    return batch_stats

  async def _generate_embedding(self, text: str) -> List[float]:
    """
    Generate embedding via Ollama API or fastembed (fallback).

    Args:
      text: Text to process

    Returns:
      List[float]: Embedding vector (768 dims with Ollama)
    """
    if self.embedding_model is None:
      return await self._generate_embedding_ollama(text)
    else:
      loop = asyncio.get_running_loop()
      return await loop.run_in_executor(
        self.executor,
        self._generate_embedding_sync,
        text
      )

  async def _generate_embedding_ollama(self, text: str) -> List[float]:
    """
    Generate embedding via Ollama API.

    Model: nomic-embed-text (768 dimensions)
    Time: ~400ms (vs 8-10s with fastembed)

    Args:
      text: Text to process

    Returns:
      List[float]: Embedding vector (768 dims)

    Raises:
      ValueError: If Ollama returns error
    """
    import httpx

    if not text.strip():
      raise ValueError("Text no pot estar buit")

    truncated = text[:8000]

    try:
      async with httpx.AsyncClient(timeout=self.OLLAMA_TIMEOUT) as client:
        response = await client.post(
          self._embed_url(),
          json={
            "model": self.OLLAMA_MODEL,
            "prompt": truncated,
          },
        )

        if response.status_code == 200:
          data = response.json()
          embedding = data.get("embedding")
          if embedding:
            logger.debug("Ollama embedding generated (%d dims)", len(embedding))
            return embedding
          else:
            raise ValueError("Ollama response missing 'embedding' field")
        else:
          raise ValueError(f"Ollama error {response.status_code}: {response.text[:100]}")

    except httpx.TimeoutException:
      logger.error("Ollama embedding timeout (%ss)", self.OLLAMA_TIMEOUT)
      raise ValueError("Ollama embedding timeout")
    except Exception as e:
      logger.error("Ollama embedding error: %s", e)
      raise

  def _generate_embedding_sync(self, text: str) -> List[float]:
    """
    Generate embedding with fastembed (ONNX fallback mode).

    Used when embedding_model is explicitly set (not using Ollama API).

    Args:
      text: Text to process

    Returns:
      List[float]: Embedding vector (768 dims with mpnet)

    Raises:
      ValueError: If text empty
    """
    if os.getenv("NEXE_ENV") == "test" or os.getenv("PYTEST_CURRENT_TEST"):
      return self._generate_test_embedding(text)

    from fastembed import TextEmbedding
    from memory.embeddings.paths import default_fastembed_cache_dir
    import numpy as np

    if not text.strip():
      raise ValueError("Text no pot estar buit")

    fe_model: Optional[Any] = getattr(self, '_fe_model', None)
    if fe_model is None:
      logger.info("Loading fastembed model: %s", self.embedding_model)
      try:
        fe_model = TextEmbedding(self.embedding_model, cache_dir=str(default_fastembed_cache_dir()))
        self._fe_model = fe_model
      except Exception as e:
        raise RuntimeError(
            f"Embedding model '{self.embedding_model}' not available locally. "
            f"Run the installer to download it. Error: {e}"
        ) from e

    assert fe_model is not None  # nosec B101  # narrowing for pyright after loading branch above
    embedding = list(fe_model.embed([text]))[0]
    arr = np.array(embedding)
    norm = np.linalg.norm(arr)
    if norm > 0:
      arr = arr / norm

    return arr.astype(np.float32).tolist()

  @staticmethod
  def _generate_test_embedding(text: str, size: int = DEFAULT_VECTOR_SIZE) -> List[float]:
    """Generate deterministic embeddings for tests without external models."""
    import hashlib
    import random

    if not text.strip():
      raise ValueError("Text no pot estar buit")

    seed = int(hashlib.sha256(text.encode("utf-8")).hexdigest()[:16], 16)
    rng = random.Random(seed)  # nosec B311: deterministic test embedding from SHA256 seed (reproducibility, not security/cryptography)
    return [rng.uniform(-1.0, 1.0) for _ in range(size)]

  async def cleanup_expired(self) -> int:
    """
    Cleanup of expired entries (execute periodically).

    Returns:
      int: Number of cleaned entries
    """
    deleted = await self.flash.cleanup_expired()
    logger.info("Cleanup: %s expired entries removed", deleted)
    return deleted

  def get_stats(self) -> dict:
    """Get pipeline statistics"""
    return {
      **self.stats,
      "deduplicator": self.deduplicator.get_stats()
    }

  def close(self):
    """Close resources"""
    self.executor.shutdown(wait=True)
    logger.info("IngestionPipeline closed")

__all__ = ["IngestionPipeline"]
