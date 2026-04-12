"""
────────────────────────────────────
Server Nexe
Author: Jordi Goy
Location: memory/embeddings/simple_embedder.py
Description: Simple synchronous embedder based on fastembed (ONNX).

www.jgoy.net · https://server-nexe.org
────────────────────────────────────
"""

from typing import List
import logging
from fastembed import TextEmbedding
import numpy as np

from .constants import DEFAULT_EMBEDDING_MODEL

logger = logging.getLogger(__name__)


def _normalize(v: np.ndarray) -> List[float]:
  """L2-normalize a vector and return as list of floats."""
  norm = np.linalg.norm(v)
  if norm > 0:
    v = v / norm
  return v.astype(np.float32).tolist()


class SimpleEmbedder:
  """
  Simple synchronous embedder based on fastembed (ONNX).

  For cases where cache or async is not needed (e.g., RAG initialization).

  Attributes:
    model_name: Model name
    model: TextEmbedding instance
  """

  _instances = {}

  def __new__(cls, model_name: str, **kwargs):
    """Singleton to avoid loading model multiple times."""
    if model_name not in cls._instances:
      instance = super().__new__(cls)
      cls._instances[model_name] = instance
      instance._initialized = False
    return cls._instances[model_name]

  def __init__(self, model_name: str, device: str = "cpu"):
    """
    Init SimpleEmbedder.

    Args:
      model_name: Model name (fastembed compatible)
      device: Ignored (fastembed uses ONNX runtime, auto-selects)
    """
    if self._initialized:
      return

    self.model_name = model_name
    self.device = device

    logger.info(f"Loading model {model_name} (fastembed/ONNX)")
    try:
      self.model = TextEmbedding(model_name)
    except Exception as e:
      raise RuntimeError(
          f"Embedding model '{model_name}' not available locally. "
          f"Run the installer to download it. Error: {e}"
      ) from e
    self._initialized = True

    logger.info(f"SimpleEmbedder initialized: {model_name}")

  def encode(self, text: str, normalize: bool = True) -> List[float]:
    """
    Encode text to embedding.

    Args:
      text: Text to encode
      normalize: Normalize embedding (default True)

    Returns:
      Embedding as list of floats
    """
    embedding = list(self.model.embed([text]))[0]

    if normalize:
      return _normalize(np.array(embedding))

    return np.array(embedding).astype(np.float32).tolist()

  def encode_batch(
    self,
    texts: List[str],
    normalize: bool = True,
    batch_size: int = 32
  ) -> List[List[float]]:
    """
    Encode batch of texts.

    Args:
      texts: List of texts
      normalize: Normalize embeddings
      batch_size: Batch size for processing

    Returns:
      List of embeddings
    """
    embeddings = list(self.model.embed(texts, batch_size=batch_size))

    if normalize:
      return [_normalize(np.array(e)) for e in embeddings]

    return [np.array(e).astype(np.float32).tolist() for e in embeddings]

  @property
  def dimensions(self) -> int:
    """Get embedding dimensions."""
    return 768

def get_embedder(model_name: str, device: str = "cpu") -> SimpleEmbedder:
  """
  Factory function to get embedder.

  Returns singleton instance of the model.

  Args:
    model_name: Model name (fastembed compatible)
    device: Ignored (fastembed uses ONNX runtime)

  Returns:
    SimpleEmbedder instance

  Examples:
    >>> embedder = get_embedder("paraphrase-multilingual-mpnet-base-v2")
    >>> embedding = embedder.encode("hello world")
    >>> len(embedding)
    768
  """
  return SimpleEmbedder(model_name=model_name, device=device)

__all__ = ["SimpleEmbedder", "get_embedder"]
