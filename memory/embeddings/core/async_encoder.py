"""
────────────────────────────────────
Server Nexe
Author: Jordi Goy
Location: memory/embeddings/core/async_encoder.py
Description: AsyncEmbedder: Async wrapper for fastembed TextEmbedding that does NOT block the event loop.

www.jgoy.net · https://server-nexe.org
────────────────────────────────────
"""

import asyncio
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from typing import Any, Dict, List, Optional
import numpy as np
import structlog

logger = structlog.get_logger()


def _normalize(v: np.ndarray) -> List[float]:
  """L2-normalize a vector and return as list of floats."""
  norm = np.linalg.norm(v)
  if norm > 0:
    v = v / norm
  return v.astype(np.float32).tolist()


class AsyncEmbedder:
  """
  Async wrapper for fastembed TextEmbedding (does not block event loop).

  CRITICAL: fastembed is synchronous and blocking. This wrapper
  runs embed() in a ThreadPoolExecutor to avoid blocking FastAPI.

  Features:
  - Lazy loading of the model (only loads when needed)
  - Thread-safe with asyncio.Lock
  - Singleton per model (avoids multiple instances)
  - Graceful shutdown of the ThreadPool

  Attributes:
    model_name: Model name
    device: Device (ignored — fastembed uses ONNX runtime)
    max_workers: Maximum threads in the pool (2 for Mac due to thermal limits)
    _model: TextEmbedding instance (lazy loaded)
    _load_lock: Lock for thread-safe lazy loading
    executor: ThreadPoolExecutor for async encoding
  """

  _instances: Dict[str, "AsyncEmbedder"] = {}
  _instances_lock = threading.Lock()  # Thread-safe singleton creation across workers
  _initialized: bool = False

  def __new__(cls, model_name: str, **kwargs):
    """
    Singleton pattern: Returns existing instance if already loaded.

    Avoids loading the same model multiple times (limited memory).
    Thread-safe with lock to avoid race conditions in multi-worker.
    """
    with cls._instances_lock:
      if model_name not in cls._instances:
        instance = super().__new__(cls)
        cls._instances[model_name] = instance
        instance._initialized = False
      return cls._instances[model_name]

  def __init__(
    self,
    model_name: str,
    max_workers: int = 2,
    device: str = "cpu"
  ):
    """
    Init AsyncEmbedder.

    Args:
      model_name: Model name (fastembed compatible)
      max_workers: Threads in the pool (2 for Mac, 4 for servers)
      device: Ignored (fastembed uses ONNX runtime)
    """
    if self._initialized:
      return

    self.model_name = model_name
    self.device = device
    self.max_workers = max_workers
    self.executor = ThreadPoolExecutor(
      max_workers=max_workers,
      thread_name_prefix=f"embedding_{model_name[:20]}"
    )
    self._model: Optional[Any] = None
    self._load_lock = asyncio.Lock()
    self._initialized = True

    logger.info(
      "async_embedder_initialized",
      model=model_name,
      device=device,
      max_workers=max_workers
    )

  async def _ensure_loaded(self):
    """
    Lazy loading of the model (loads only when needed).

    Thread-safe with double-check locking pattern.
    Runs the load in ThreadPoolExecutor to avoid blocking the event loop.
    """
    if self._model is None:
      async with self._load_lock:
        if self._model is None:
          logger.info("loading_model", model=self.model_name, device=self.device)
          start = time.time()

          loop = asyncio.get_running_loop()
          self._model = await loop.run_in_executor(
            self.executor,
            self._load_model
          )

          load_time = (time.time() - start) * 1000
          logger.info(
            "model_loaded",
            model=self.model_name,
            load_time_ms=load_time,
            device=self.device
          )

  def _load_model(self):
    """
    Loads model in a separate thread (blocking).

    IMPORTANT: This method runs in the ThreadPool, NOT in the main thread.

    Returns:
      TextEmbedding instance
    """
    from fastembed import TextEmbedding

    try:
      return TextEmbedding(self.model_name)
    except Exception as e:
      raise RuntimeError(
          f"Embedding model '{self.model_name}' not available locally. "
          f"Run the installer to download it. Error: {e}"
      ) from e

  async def encode_async(
    self,
    text: str,
    normalize: bool = True
  ) -> List[float]:
    """
    Encode a text async (does not block event loop).

    Args:
      text: Text to convert to embedding
      normalize: Whether to normalize embedding (L2 norm)

    Returns:
      Embedding vector (768 dimensions by default)

    Raises:
      ValueError: If text is empty
    """
    if not text.strip():
      raise ValueError("Text no pot estar buit")

    await self._ensure_loaded()

    start = time.time()
    loop = asyncio.get_running_loop()

    embedding = await loop.run_in_executor(
      self.executor,
      self._encode_sync,
      text,
      normalize
    )

    latency = (time.time() - start) * 1000

    logger.debug(
      "encode_completed",
      model=self.model_name,
      text_len=len(text),
      latency_ms=latency,
      dimensions=len(embedding)
    )

    return embedding

  def _encode_sync(self, text: str, normalize: bool) -> List[float]:
    """
    Synchronous encode (runs in the ThreadPool).

    Args:
      text: Text to convert
      normalize: Whether to normalize

    Returns:
      Embedding as a list of floats
    """
    if self._model is None:
      raise RuntimeError("AsyncEmbedder._model not loaded — cal await _ensure_loaded() abans d'invocar _encode_sync")
    embedding = list(self._model.embed([text]))[0]

    if normalize:
      return _normalize(np.array(embedding))

    return np.array(embedding).astype(np.float32).tolist()

  async def encode_batch_async(
    self,
    texts: List[str],
    normalize: bool = True,
    batch_size: int = 32
  ) -> List[List[float]]:
    """
    Encode batch of texts async (optimized).

    Args:
      texts: List of texts
      normalize: Whether to normalize embeddings
      batch_size: Internal batch size

    Returns:
      List of embeddings (same order as texts)

    Raises:
      ValueError: If texts is empty or contains empty strings
    """
    if not texts:
      raise ValueError("texts no pot estar buit")

    if any(not t.strip() for t in texts):
      raise ValueError("Tots els texts han de ser no-buits")

    await self._ensure_loaded()

    start = time.time()
    loop = asyncio.get_running_loop()

    embeddings = await loop.run_in_executor(
      self.executor,
      self._encode_batch_sync,
      texts,
      normalize,
      batch_size
    )

    latency = (time.time() - start) * 1000

    logger.debug(
      "encode_batch_completed",
      model=self.model_name,
      count=len(texts),
      batch_size=batch_size,
      total_latency_ms=latency,
      avg_latency_ms=latency / len(texts)
    )

    return embeddings

  def _encode_batch_sync(
    self,
    texts: List[str],
    normalize: bool,
    batch_size: int
  ) -> List[List[float]]:
    """
    Synchronous batch encode (runs in the ThreadPool).

    Args:
      texts: List of texts
      normalize: Whether to normalize
      batch_size: Batch size

    Returns:
      List of embeddings
    """
    if self._model is None:
      raise RuntimeError("AsyncEmbedder._model not loaded — cal await _ensure_loaded() abans d'invocar _encode_batch_sync")
    embeddings = list(self._model.embed(texts, batch_size=batch_size))

    if normalize:
      return [_normalize(np.array(e)) for e in embeddings]

    return [np.array(e).astype(np.float32).tolist() for e in embeddings]

  async def shutdown(self):
    """
    Graceful shutdown of the ThreadPoolExecutor.

    IMPORTANT: Call this method before closing the application
    to avoid pending tasks.
    """
    logger.info("shutting_down_embedder", model=self.model_name)
    self.executor.shutdown(wait=True)
    self._model = None

    if self.model_name in self._instances:
      del self._instances[self.model_name]

    logger.info("embedder_shutdown_complete", model=self.model_name)

  def get_info(self) -> dict:
    """
    Get encoder information.

    Returns:
      Dict with model_name, device, loaded status
    """
    return {
      "model_name": self.model_name,
      "device": self.device,
      "max_workers": self.max_workers,
      "loaded": self._model is not None
    }
