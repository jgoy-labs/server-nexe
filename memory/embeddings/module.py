"""
────────────────────────────────────
Server Nexe
Author: Jordi Goy 
Location: memory/embeddings/module.py
Description: Main Embeddings Module - Multilingual embedding and vectorization system.

www.jgoy.net · https://server-nexe.org
────────────────────────────────────
"""

from typing import Optional, Dict, Any
import threading
import structlog

from personality.i18n import get_i18n
from .constants import MANIFEST, MODULE_ID
from .core import (
  AsyncEmbedder,
  CachedEmbedder,
  SmartChunker,
  EmbeddingRequest,
  EmbeddingResponse,
  BatchEmbeddingRequest,
  BatchEmbeddingResponse,
  ChunkedDocument,
  EncoderStats,
)

logger = structlog.get_logger()


def _detect_device() -> str:
    """Auto-detect best available device for embeddings.

    fastembed uses ONNX runtime which auto-selects the best provider.
    This returns 'cpu' as fastembed handles device selection internally.
    """
    return "cpu"


class EmbeddingsModule:
  """
  Embeddings Module - Multilingual embeddings system with cache.

  Singleton that manages:
  - Async embedding generation (non-blocking event loop)
  - Multi-level cache (L1 memory + L2 disk)
  - Smart document chunking with section_title detection
  - Batch processing optimitzat

  Features:
  ✅ AsyncEmbedder amb ThreadPool (P90 <120ms)
  ✅ CachedEmbedder amb MultiLevelCache (hit rate >80%)
  ✅ SmartChunker amb section_title detection
  ✅ Workflow nodes integration
  ✅ Stats tracking (latencies, hit rate)

  Usage:
    module = EmbeddingsModule.get_instance()
    await module.initialize()

    request = EmbeddingRequest(text="hello world")
    response = await module.encode(request)

    batch_request = BatchEmbeddingRequest(texts=["hello", "world"])
    batch_response = await module.encode_batch(batch_request)

    chunks = await module.chunk_document(content, document_id)
  """

  _instance: Optional['EmbeddingsModule'] = None
  _initialized: bool = False
  _singleton_lock = threading.Lock()

  def __init__(self):
    """Private constructor. Use get_instance()"""
    if EmbeddingsModule._instance is not None:
      raise RuntimeError(
        get_i18n().t(
          "embeddings.singleton_error",
          "EmbeddingsModule is Singleton. Use get_instance()"
        )
      )

    self.module_id = MODULE_ID
    self.manifest = MANIFEST
    self.name = MANIFEST["name"]
    self.version = MANIFEST["version"]

    self._cached_embedder: Optional[CachedEmbedder] = None
    self._chunker: Optional[SmartChunker] = None
    self._config: Dict[str, Any] = {}

    logger.info(
      "embeddings_module_created",
      module_id=self.module_id,
      version=self.version
    )

  @classmethod
  def get_instance(cls) -> 'EmbeddingsModule':
    """
    Gets Singleton instance of the module (thread-safe).

    Returns:
      EmbeddingsModule: Unique module instance
    """
    with cls._singleton_lock:
      if cls._instance is None:
        cls._instance = cls()
    return cls._instance

  async def initialize(self, config: Optional[Dict[str, Any]] = None) -> bool:
    """
    Initializes the Embeddings module.

    Pipeline:
    1. Merge config with defaults
    2. Create AsyncEmbedder + CachedEmbedder
    3. Create SmartChunker
    4. Validar dependencies

    Args:
      config: Optional configuration
        - model_name: str (default: paraphrase-multilingual-mpnet-base-v2)
        - device: str (default: cpu)
        - max_workers: int (default: 2)
        - cache_enabled: bool (default: True)
        - l1_max_size: int (default: 1000)
        - l2_max_size_gb: float (default: 5.0)
        - l2_ttl_hours: int (default: 72)
        - max_chunk_size: int (default: 1500)

    Returns:
      bool: True if initialization successful

    Raises:
      RuntimeError: If already initialized
      ImportError: If dependencies not available
    """
    if self._initialized:
      logger.warning("embeddings_module_already_initialized")
      return True

    try:
      from .constants import DEFAULT_EMBEDDING_MODEL
      default_config = {
        "model_name": DEFAULT_EMBEDDING_MODEL,
        "device": _detect_device(),
        "max_workers": 2,
        "cache_enabled": True,
        "l1_max_size": 1000,
        "l2_max_size_gb": 5.0,
        "l2_ttl_hours": 72,
        "max_chunk_size": 1500,
        "chunk_overlap": 200,
        "min_chunk_size": 100,
      }

      self._config = {**default_config, **(config or {})}

      logger.info(
        "embeddings_module_initializing",
        config=self._config
      )

      async_embedder = AsyncEmbedder(
        model_name=self._config["model_name"],
        max_workers=self._config["max_workers"],
        device=self._config["device"]
      )

      self._cached_embedder = CachedEmbedder(
        encoder=async_embedder,
        cache_enabled=self._config["cache_enabled"],
        l1_max_size=self._config["l1_max_size"],
        l2_max_size_gb=self._config["l2_max_size_gb"],
        l2_ttl_hours=self._config["l2_ttl_hours"]
      )

      self._chunker = SmartChunker(
        max_chunk_size=self._config["max_chunk_size"],
        chunk_overlap=self._config["chunk_overlap"],
        min_chunk_size=self._config["min_chunk_size"]
      )

      self._initialized = True

      logger.info(
        "embeddings_module_initialized",
        version=self.version,
        model=self._config["model_name"],
        device=self._config["device"],
        cache_enabled=self._config["cache_enabled"]
      )

      return True

    except Exception as e:
      logger.error(
        "embeddings_module_init_failed",
        error=str(e),
        exc_info=True
      )
      raise

  async def encode(self, request: EmbeddingRequest) -> EmbeddingResponse:
    """
    Generates embedding for a text.

    Args:
      request: EmbeddingRequest with text and config

    Returns:
      EmbeddingResponse with embedding and stats

    Raises:
      RuntimeError: If module not initialized
    """
    if not self._initialized or not self._cached_embedder:
      raise RuntimeError(
        get_i18n().t(
          "embeddings.not_initialized",
          "EmbeddingsModule not initialized. Call initialize()"
        )
      )

    return await self._cached_embedder.encode(request)

  async def encode_batch(self, request: BatchEmbeddingRequest) -> BatchEmbeddingResponse:
    """
    Generates batch of embeddings.

    Args:
      request: BatchEmbeddingRequest with texts and config

    Returns:
      BatchEmbeddingResponse with embeddings and stats

    Raises:
      RuntimeError: If module not initialized
    """
    if not self._initialized or not self._cached_embedder:
      raise RuntimeError(
        get_i18n().t(
          "embeddings.not_initialized",
          "EmbeddingsModule not initialized. Call initialize()"
        )
      )

    return await self._cached_embedder.encode_batch(request)

  async def chunk_document(
    self,
    content: str,
    document_id: str
  ) -> ChunkedDocument:
    """
    Chunk document with SmartChunker.

    Args:
      content: Document text
      document_id: Unique document ID

    Returns:
      ChunkedDocument with chunk metadata

    Raises:
      RuntimeError: If module not initialized
    """
    if not self._initialized or not self._chunker:
      raise RuntimeError(
        get_i18n().t(
          "embeddings.not_initialized",
          "EmbeddingsModule not initialized. Call initialize()"
        )
      )

    return self._chunker.chunk_document(content, document_id)

  def get_stats(self) -> EncoderStats:
    """
    Get accumulated encoder statistics.

    Returns:
      EncoderStats with hit rate, latencies, etc.

    Raises:
      RuntimeError: If module not initialized
    """
    if not self._initialized or not self._cached_embedder:
      raise RuntimeError(
        get_i18n().t(
          "embeddings.not_initialized",
          "EmbeddingsModule not initialized. Call initialize()"
        )
      )

    return self._cached_embedder.get_stats()

  async def clear_cache(self):
    """
    Clear all cache (L1 + L2).

    Raises:
      RuntimeError: If module not initialized
    """
    if not self._initialized or not self._cached_embedder:
      raise RuntimeError(
        get_i18n().t(
          "embeddings.not_initialized",
          "EmbeddingsModule not initialized. Call initialize()"
        )
      )

    await self._cached_embedder.clear_cache()

  async def shutdown(self) -> bool:
    """
    Graceful module shutdown.

    Cleanup:
    - AsyncEmbedder shutdown (ThreadPoolExecutor)
    - Cache clear
    - Resources released

    Returns:
      bool: True if shutdown successful
    """
    if not self._initialized:
      logger.warning("embeddings_module_not_initialized_shutdown")
      return True

    try:
      logger.info("embeddings_module_shutting_down")

      if self._cached_embedder:
        await self._cached_embedder.shutdown()

      self._initialized = False
      self._cached_embedder = None
      self._chunker = None
      self._config = {}

      logger.info("embeddings_module_shutdown_complete")
      return True

    except Exception as e:
      logger.error(
        "embeddings_module_shutdown_failed",
        error=str(e),
        exc_info=True
      )
      return False

  def get_health(self) -> Dict[str, Any]:
    """
    Gets module health status.

    Delegates to health.py for detailed checks.

    Returns:
      Dict with:
        - status: "healthy" | "degraded" | "unhealthy"
        - checks: List of individual health checks
        - metadata: Module info
    """
    from .health import check_health

    return check_health(self)

  def get_info(self) -> Dict[str, Any]:
    """
    Gets module information.

    Returns:
      Dict with manifest metadata + current config
    """
    info = {
      "module_id": self.module_id,
      "name": self.name,
      "version": self.version,
      "description": self.manifest.get("description", ""),
      "capabilities": self.manifest.get("capabilities", []),
      "initialized": self._initialized,
    }

    if self._initialized:
      info["config"] = self._config
    info["stats"] = self.get_stats().model_dump() if self._cached_embedder else {}

    return info

__all__ = ["EmbeddingsModule"]
