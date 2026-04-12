"""
────────────────────────────────────
Server Nexe
Author: Jordi Goy
Location: memory/embeddings/core/async_encoder.py
Description: AsyncEmbedder: Wrapper async per fastembed TextEmbedding que NO bloqueja l'event loop.

www.jgoy.net · https://server-nexe.org
────────────────────────────────────
"""

import asyncio
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from typing import List, Optional
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
  Wrapper async per fastembed TextEmbedding (no bloqueja event loop).

  CRÍTIC: fastembed és síncron i bloquejant. Aquest wrapper
  executa embed() en ThreadPoolExecutor per evitar bloquejar FastAPI.

  Features:
  - Lazy loading del model (només carrega quan es necessita)
  - Thread-safe amb asyncio.Lock
  - Singleton per model (evita múltiples instàncies)
  - Graceful shutdown del ThreadPool

  Attributes:
    model_name: Nom del model
    device: Device (ignored — fastembed uses ONNX runtime)
    max_workers: Màxim threads al pool (2 per Mac per thermal limits)
    _model: Instància de TextEmbedding (lazy loaded)
    _load_lock: Lock per lazy loading thread-safe
    executor: ThreadPoolExecutor per encoding async
  """

  _instances = {}
  _instances_lock = threading.Lock()  # Thread-safe singleton creation across workers

  def __new__(cls, model_name: str, **kwargs):
    """
    Singleton pattern: Retorna instància existent si ja està carregada.

    Evita carregar el mateix model múltiples vegades (memòria limitada).
    Thread-safe amb lock per evitar race conditions en multi-worker.
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
      max_workers: Threads al pool (2 per Mac, 4 per servers)
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
    self._model: Optional[object] = None
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
    Lazy loading del model (carrega només quan es necessita).

    Thread-safe amb double-check locking pattern.
    Executa la càrrega en ThreadPoolExecutor per no bloquejar event loop.
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
    Carrega model en thread separat (bloquejant).

    IMPORTANT: Aquest mètode s'executa al ThreadPool, NO al main thread.

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
    Encode un text async (no bloqueja event loop).

    Args:
      text: Text a convertir en embedding
      normalize: Si normalitzar embedding (L2 norm)

    Returns:
      Vector d'embedding (768 dimensions per defecte)

    Raises:
      ValueError: Si text buit
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
    Encode síncron (executa al ThreadPool).

    Args:
      text: Text a convertir
      normalize: Si normalitzar

    Returns:
      Embedding com a llista de floats
    """
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
    Encode batch de texts async (optimitzat).

    Args:
      texts: Llista de texts
      normalize: Si normalitzar embeddings
      batch_size: Mida del batch intern

    Returns:
      Llista d'embeddings (mateix ordre que texts)

    Raises:
      ValueError: Si texts buit o conté strings buides
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
    Encode batch síncron (executa al ThreadPool).

    Args:
      texts: Llista de texts
      normalize: Si normalitzar
      batch_size: Mida del batch

    Returns:
      Llista d'embeddings
    """
    embeddings = list(self._model.embed(texts, batch_size=batch_size))

    if normalize:
      return [_normalize(np.array(e)) for e in embeddings]

    return [np.array(e).astype(np.float32).tolist() for e in embeddings]

  async def shutdown(self):
    """
    Graceful shutdown del ThreadPoolExecutor.

    IMPORTANT: Cridar aquest mètode abans de tancar l'aplicació
    per evitar tasks pendents.
    """
    logger.info("shutting_down_embedder", model=self.model_name)
    self.executor.shutdown(wait=True)
    self._model = None

    if self.model_name in self._instances:
      del self._instances[self.model_name]

    logger.info("embedder_shutdown_complete", model=self.model_name)

  def get_info(self) -> dict:
    """
    Get informació del encoder.

    Returns:
      Dict amb model_name, device, loaded status
    """
    return {
      "model_name": self.model_name,
      "device": self.device,
      "max_workers": self.max_workers,
      "loaded": self._model is not None
    }
