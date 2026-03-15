"""
────────────────────────────────────
Server Nexe
Version: 0.8
Author: Jordi Goy 
Location: memory/embeddings/simple_embedder.py
Description: No description available.

www.jgoy.net · https://server-nexe.org
────────────────────────────────────
"""

from typing import List
import logging
from sentence_transformers import SentenceTransformer
import numpy as np

logger = logging.getLogger(__name__)

class SimpleEmbedder:
  """
  Simple synchronous embedder based on SentenceTransformer.

  For cases where cache or async is not needed (e.g., RAG initialization).

  Attributes:
    model_name: Model name
    model: SentenceTransformer instance
    device: Device (cpu, mps, cuda)
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
      model_name: Model sentence-transformers
      device: cpu, mps, o cuda
    """
    if self._initialized:
      return

    self.model_name = model_name
    self.device = device

    logger.info(f"Loading model {model_name} on {device}")
    try:
      # Primer intent: caché local (sense xarxa — servidor 100% local)
      self.model = SentenceTransformer(model_name, device=device, local_files_only=True)
    except Exception:
      # Fallback: descàrrega (primera instal·lació)
      logger.info(f"Model {model_name} not in local cache, downloading...")
      self.model = SentenceTransformer(model_name, device=device)
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
    embedding = self.model.encode(
      text,
      convert_to_numpy=True,
      normalize_embeddings=normalize
    )

    if isinstance(embedding, np.ndarray):
      embedding = embedding.tolist()

    return embedding

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
    embeddings = self.model.encode(
      texts,
      convert_to_numpy=True,
      normalize_embeddings=normalize,
      batch_size=batch_size
    )

    if isinstance(embeddings, np.ndarray):
      embeddings = embeddings.tolist()

    return embeddings

  @property
  def dimensions(self) -> int:
    """Get embedding dimensions."""
    return self.model.get_sentence_embedding_dimension()

def get_embedder(model_name: str, device: str = "cpu") -> SimpleEmbedder:
  """
  Factory function to get embedder.

  Returns singleton instance of the model.

  Args:
    model_name: Model sentence-transformers
    device: Device (cpu, mps, cuda)

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