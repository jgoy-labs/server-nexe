"""
────────────────────────────────────
Server Nexe
Version: 0.8
Author: Jordi Goy 
Location: memory/embeddings/core/async_encoder.py
Description: AsyncEmbedder: Async wrapper for SentenceTransformer that does NOT block the event loop.

www.jgoy.net
────────────────────────────────────
"""

import asyncio
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from typing import List, Optional
import numpy as np
import structlog
from personality.i18n.resolve import t_modular


def _t(key: str, fallback: str, **kwargs) -> str:
  return t_modular(key, fallback, **kwargs)

logger = structlog.get_logger()

class AsyncEmbedder:
  """
  Async wrapper for SentenceTransformer (does not block the event loop).

  CRITICAL: SentenceTransformer is synchronous and blocking. This wrapper
  runs encode() in a ThreadPoolExecutor to avoid blocking FastAPI.

  Features:
  - Lazy model loading (only loads when needed)
  - Thread-safe with asyncio.Lock
  - Singleton per model (avoids multiple instances)
  - Support for CPU and MPS (Apple Silicon)
  - Graceful ThreadPool shutdown

  Attributes:
    model_name: Sentence-transformers model name
    device: Device (cpu, mps, cuda)
    max_workers: Max threads in the pool (2 on Mac for thermal limits)
    _model: SentenceTransformer instance (lazy loaded)
    _load_lock: Lock for thread-safe lazy loading
    executor: ThreadPoolExecutor for async encoding
  """

  _instances = {}
  _instances_lock = threading.Lock()  # FIX: Thread-safe singleton creation

  def __new__(cls, model_name: str, **kwargs):
    """
    Singleton pattern: Return existing instance if already loaded.

    Avoids loading the same model multiple times (limited memory).
    Thread-safe with a lock to avoid race conditions in multi-worker.
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
      model_name: Sentence-transformers model (e.g. paraphrase-multilingual-MiniLM-L12-v2)
      max_workers: Threads in the pool (2 for Mac, 4 for servers)
      device: cpu, mps, or cuda
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
    self._model: Optional[object] = None
    self._load_lock = asyncio.Lock()
    self._initialized = True

    logger.info(
      "async_embedder_initialized",
      message=_t(
        "embeddings.logs.async_embedder_initialized",
        "AsyncEmbedder initialized (model={model}, device={device}, max_workers={max_workers})",
        model=model_name,
        device=device,
        max_workers=max_workers,
      ),
      model=model_name,
      device=device,
      max_workers=max_workers
    )

  async def _ensure_loaded(self):
    """
    Lazy model loading (load only when needed).

    Thread-safe with double-check locking pattern.
    Loads in a ThreadPoolExecutor to avoid blocking the event loop.
    """
    if self._model is None:
      async with self._load_lock:
        if self._model is None:
          logger.info(
            "loading_model",
            message=_t(
              "embeddings.logs.loading_model",
              "Loading embeddings model (model={model}, device={device})",
              model=self.model_name,
              device=self.device,
            ),
            model=self.model_name,
            device=self.device
          )
          start = time.time()

          loop = asyncio.get_running_loop()
          self._model = await loop.run_in_executor(
            self.executor,
            self._load_model
          )

          load_time = (time.time() - start) * 1000
          logger.info(
            "model_loaded",
            message=_t(
              "embeddings.logs.model_loaded",
              "Embeddings model loaded (model={model}, device={device}, load_time_ms={load_time_ms})",
              model=self.model_name,
              device=self.device,
              load_time_ms=load_time,
            ),
            model=self.model_name,
            load_time_ms=load_time,
            device=self.device
          )

  def _load_model(self):
    """
    Load model in a separate (blocking) thread.

    IMPORTANT: This method runs in the ThreadPool, NOT on the main thread.
    SentenceTransformer.encode() can only run on the thread that created the model.

    Returns:
      SentenceTransformer instance
    """
    from sentence_transformers import SentenceTransformer

    return SentenceTransformer(
      self.model_name,
      device=self.device
    )

  async def encode_async(
    self,
    text: str,
    normalize: bool = True
  ) -> List[float]:
    """
    Encode text asynchronously (does not block the event loop).

    Args:
      text: Text to convert into an embedding
      normalize: Whether to normalize embedding (L2 norm)

    Returns:
      Embedding vector (384 dimensions by default)

    Raises:
      ValueError: If text is empty
    """
    if not text.strip():
      raise ValueError(
        _t(
          "embeddings.validation.text_empty",
          "Text cannot be empty"
        )
      )

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
      message=_t(
        "embeddings.logs.encode_completed",
        "Encode completed (model={model}, text_len={text_len}, latency_ms={latency_ms}, dimensions={dimensions})",
        model=self.model_name,
        text_len=len(text),
        latency_ms=latency,
        dimensions=len(embedding),
      ),
      model=self.model_name,
      text_len=len(text),
      latency_ms=latency,
      dimensions=len(embedding)
    )

    return embedding

  def _encode_sync(self, text: str, normalize: bool) -> List[float]:
    """
    Synchronous encode (runs in the ThreadPool).

    IMPORTANT: This method runs in the ThreadPool, NOT on the main event loop.

    Args:
      text: Text to convert
      normalize: Whether to normalize

    Returns:
      Embedding as a list of floats
    """
    embedding = self._model.encode(
      text,
      convert_to_tensor=False,
      normalize_embeddings=normalize,
      show_progress_bar=False
    )

    return embedding.astype(np.float32).tolist()

  async def encode_batch_async(
    self,
    texts: List[str],
    normalize: bool = True,
    batch_size: int = 32
  ) -> List[List[float]]:
    """
    Encode a batch of texts asynchronously (optimized).

    More efficient than individual encode_async because SentenceTransformer
    can process batches in parallel internally.

    Args:
      texts: List of texts
      normalize: Whether to normalize embeddings
      batch_size: Internal batch size (for SentenceTransformer)

    Returns:
      List of embeddings (same order as texts)

    Raises:
      ValueError: If texts is empty or contains empty strings
    """
    if not texts:
      raise ValueError(
        _t(
          "embeddings.validation.texts_empty",
          "texts cannot be empty"
        )
      )

    if any(not t.strip() for t in texts):
      raise ValueError(
        _t(
          "embeddings.validation.texts_non_empty",
          "All texts must be non-empty"
        )
      )

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
      message=_t(
        "embeddings.logs.encode_batch_completed",
        "Batch encode completed (model={model}, count={count}, batch_size={batch_size}, total_latency_ms={total_latency_ms}, avg_latency_ms={avg_latency_ms})",
        model=self.model_name,
        count=len(texts),
        batch_size=batch_size,
        total_latency_ms=latency,
        avg_latency_ms=latency / len(texts),
      ),
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
    embeddings = self._model.encode(
      texts,
      batch_size=batch_size,
      convert_to_tensor=False,
      normalize_embeddings=normalize,
      show_progress_bar=False
    )

    return embeddings.astype(np.float32).tolist()

  async def shutdown(self):
    """
    Graceful shutdown of the ThreadPoolExecutor.

    IMPORTANT: Call this method before shutting down the application
    to avoid pending tasks.
    """
    logger.info(
      "shutting_down_embedder",
      message=_t(
        "embeddings.logs.shutting_down_embedder",
        "Shutting down embedder (model={model})",
        model=self.model_name,
      ),
      model=self.model_name
    )
    self.executor.shutdown(wait=True)
    self._model = None

    if self.model_name in self._instances:
      del self._instances[self.model_name]

    logger.info(
      "embedder_shutdown_complete",
      message=_t(
        "embeddings.logs.embedder_shutdown_complete",
        "Embedder shutdown complete (model={model})",
        model=self.model_name,
      ),
      model=self.model_name
    )

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
