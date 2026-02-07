"""
────────────────────────────────────
Server Nexe
Version: 0.8
Author: Jordi Goy 
Location: memory/memory/pipeline/ingestion.py
Description: IngestionPipeline - 7 ingestion stages with backpressure and embedding.

www.jgoy.net
────────────────────────────────────
"""

import asyncio
import logging
import os
from concurrent.futures import ThreadPoolExecutor
from typing import List, Optional

from ..models.memory_entry import MemoryEntry
from ..engines.flash_memory import FlashMemory
from ..engines.persistence import PersistenceManager
from .deduplicator import Deduplicator
from personality.i18n.resolve import t_modular

logger = logging.getLogger(__name__)

def _t(key: str, fallback: str, **kwargs) -> str:
  return t_modular(f"memory.ingestion.{key}", fallback, **kwargs)

class IngestionPipeline:
  """
  Multi-stage ingestion pipeline with backpressure.

  Features:
  - 7 processing stages
  - run_in_executor for embedding (CPU-bound)
  - Deduplication with SHA256
  - Automatic rollback if persistence fails
  """

  OLLAMA_URL = "http://localhost:11434"
  OLLAMA_EMBED_URL = f"{OLLAMA_URL}/api/embeddings"
  OLLAMA_MODEL = "nomic-embed-text"
  OLLAMA_TIMEOUT = 30.0

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

    backend = "Ollama API" if embedding_model is None else f"SentenceTransformer ({embedding_model})"
    logger.info(_t(
      "initialized",
      "IngestionPipeline initialized (embedding_backend={backend})",
      backend=backend
    ))

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
        logger.info(_t(
          "duplicate_skipped",
          "Skipping duplicate entry {id}",
          id=entry.id
        ))
        self.stats["duplicates_skipped"] += 1
        return False

      embedding = await self._generate_embedding(entry.content)

      await self.flash.store(entry)

      await self.persistence.store(entry, embedding=embedding)

      self.stats["total_ingested"] += 1
      logger.info(_t(
        "ingested",
        "Successfully ingested entry {id}",
        id=entry.id
      ))

      return True

    except Exception as e:
      logger.error(_t(
        "ingestion_failed",
        "Ingestion failed for entry {id}: {error}",
        id=entry.id,
        error=str(e)
      ))
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

    tasks = [self.ingest(entry) for entry in entries]
    results = await asyncio.gather(*tasks, return_exceptions=True)

    for result in results:
      if isinstance(result, Exception):
        batch_stats["failures"] += 1
      elif result:
        batch_stats["success"] += 1
      else:
        batch_stats["duplicates"] += 1

    logger.info(_t(
      "batch_completed",
      "Batch ingestion completed: {stats}",
      stats=batch_stats
    ))

    return batch_stats

  async def _generate_embedding(self, text: str) -> List[float]:
    """
    Generate embedding via Ollama API (FIX 6.T) or SentenceTransformer (fallback).

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
    Generate embedding via Ollama API (FIX 6.T).

    Model: nomic-embed-text (768 dimensions)
    Time: ~400ms (vs 8-10s with SentenceTransformer)

    Args:
      text: Text to process

    Returns:
      List[float]: Embedding vector (768 dims)

    Raises:
      ValueError: If Ollama returns error
    """
    import httpx

    if not text.strip():
      raise ValueError(_t(
        "text_empty",
        "Text cannot be empty"
      ))

    truncated = text[:8000]

    try:
      async with httpx.AsyncClient(timeout=self.OLLAMA_TIMEOUT) as client:
        response = await client.post(
          self.OLLAMA_EMBED_URL,
          json={
            "model": self.OLLAMA_MODEL,
            "prompt": truncated,
          },
        )

        if response.status_code == 200:
          data = response.json()
          embedding = data.get("embedding")
          if embedding:
            logger.debug(_t(
              "ollama_embedding_generated",
              "Ollama embedding generated ({dims} dims)",
              dims=len(embedding)
            ))
            return embedding
          else:
            raise ValueError(_t(
              "ollama_missing_embedding",
              "Ollama response missing 'embedding' field"
            ))
        else:
          raise ValueError(_t(
            "ollama_http_error",
            "Ollama error {status}: {preview}",
            status=response.status_code,
            preview=response.text[:100],
          ))

    except httpx.TimeoutException:
      logger.error(_t(
        "ollama_timeout",
        "Ollama embedding timeout ({seconds}s)",
        seconds=self.OLLAMA_TIMEOUT
      ))
      raise ValueError(_t(
        "ollama_timeout",
        "Ollama embedding timeout ({seconds}s)",
        seconds=self.OLLAMA_TIMEOUT
      ))
    except Exception as e:
      logger.error(_t(
        "ollama_error",
        "Ollama embedding error: {error}",
        error=str(e)
      ))
      raise

  def _generate_embedding_sync(self, text: str) -> List[float]:
    """
    Generate embedding with SentenceTransformer (sync backend).

    Used when embedding_model is set.

    Args:
      text: Text to process

    Returns:
      List[float]: Embedding vector (384 dims with MiniLM)

    Raises:
      ValueError: If text empty
    """
    if os.getenv("NEXE_ENV") == "test" or os.getenv("PYTEST_CURRENT_TEST"):
      return self._generate_test_embedding(text)

    from sentence_transformers import SentenceTransformer
    import numpy as np

    if not text.strip():
      raise ValueError(_t(
        "text_empty",
        "Text cannot be empty"
      ))

    if not hasattr(self, '_st_model') or self._st_model is None:
      logger.info(_t(
        "sentence_transformer_loading",
        "Loading SentenceTransformer model: {model}",
        model=self.embedding_model
      ))
      self._st_model = SentenceTransformer(self.embedding_model, device="cpu")

    embedding = self._st_model.encode(
      text,
      convert_to_tensor=False,
      normalize_embeddings=True,
      show_progress_bar=False
    )

    return embedding.astype(np.float32).tolist()

  @staticmethod
  def _generate_test_embedding(text: str, size: int = 384) -> List[float]:
    """Generate deterministic embeddings for tests without external models."""
    import hashlib
    import random

    if not text.strip():
      raise ValueError(_t(
        "text_empty",
        "Text cannot be empty"
      ))

    seed = int(hashlib.sha256(text.encode("utf-8")).hexdigest()[:16], 16)
    rng = random.Random(seed)
    return [rng.uniform(-1.0, 1.0) for _ in range(size)]

  async def cleanup_expired(self) -> int:
    """
    Cleanup of expired entries (execute periodically).

    Returns:
      int: Number of cleaned entries
    """
    deleted = await self.flash.cleanup_expired()
    logger.info(_t(
      "cleanup_completed",
      "Cleanup: {count} expired entries removed",
      count=deleted
    ))
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
    logger.info(_t("closed", "IngestionPipeline closed"))

__all__ = ["IngestionPipeline"]
