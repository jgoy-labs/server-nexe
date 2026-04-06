"""
────────────────────────────────────
Server Nexe
Author: Jordi Goy 
Location: memory/memory/module.py
Description: Main Memory Module - Flash Memory + RAM Context + Persistence System.

www.jgoy.net · https://server-nexe.org
────────────────────────────────────
"""

from typing import Optional, Dict, Any
import threading
import logging

from personality.i18n import get_i18n
from core.lifespan import get_server_state

from .engines.flash_memory import FlashMemory
from .engines.ram_context import RAMContext
from .constants import DEFAULT_VECTOR_SIZE
from .engines.persistence import PersistenceManager
from .models.memory_entry import MemoryEntry
from .pipeline.ingestion import IngestionPipeline

logger = logging.getLogger(__name__)

def get_memory_service():
    """Get the MemoryService from the active MemoryModule instance. Returns None if not initialized."""
    instance = MemoryModule._instance
    if instance is None or not instance._initialized:
        return None
    return instance._memory_service


class MemoryModule:
  """
  Memory Module - Flash Memory + RAM Context + Persistence + MemoryService.

  Singleton that manages:
  - Flash Memory (temporary cache for results)
  - RAM Context (current session context)
  - Persistence (save/load sessions)
  - MemoryService (v1 facade for pipeline + storage)

  Usage:
    module = MemoryModule.get_instance()
    await module.initialize()
    health = module.get_health()
  """

  _instance: Optional['MemoryModule'] = None
  _initialized: bool = False
  _singleton_lock = threading.Lock()

  def __init__(self):
    """Private constructor. Use get_instance()."""
    if MemoryModule._instance is not None:
      i18n = get_i18n()
      raise RuntimeError(
        i18n.t("memory.singleton_error", "MemoryModule is Singleton. Use get_instance()")
      )

    from .constants import MANIFEST, MODULE_ID

    self.module_id = MODULE_ID
    self.manifest = MANIFEST
    self.name = MANIFEST["name"]
    self.version = MANIFEST["version"]

    # Dependencies obtained via server_state (single source of truth)
    self.i18n = get_i18n()
    self.config = get_server_state().config

    self._flash_memory = None
    self._ram_context = None
    self._persistence = None
    self._pipeline = None
    self._memory_service = None

    logger.debug(f"MemoryModule created: {self.module_id} v{self.version}")

  @classmethod
  def get_instance(cls) -> 'MemoryModule':
    """
    Get Singleton instance of the module (thread-safe).

    Returns:
      MemoryModule: Unique instance of the module
    """
    with cls._singleton_lock:
      if cls._instance is None:
        cls._instance = cls()
    return cls._instance

  async def initialize(self, config: Optional[Dict[str, Any]] = None) -> bool:
    """
    Initializes the Memory Module.

    Eliminates "brute force" path detection (__file__).
    Uses the project_root registered in the Container.

    Args:
      config: Optional configuration (default from manifest)

    Returns:
      bool: True if initialization correct
    """
    if self._initialized:
      logger.debug("MemoryModule already initialized")
      return True

    try:
      final_config = {**self.manifest.get("config", {})}
      if config:
        final_config.update(config)

      logger.debug("MemoryModule initializing...")

      project_root = get_server_state().project_root
      if not project_root:
        from pathlib import Path
        project_root = Path.cwd()
        logger.warning("project_root not found in server_state, using cwd: %s", project_root)

      vectors_path = project_root / "storage" / "vectors"
      db_path = vectors_path / "metadata_memory.db"
      # F8 fix: previously qdrant_path = vectors_path / "qdrant_local" which
      # opened a SECOND QdrantClient on a legacy embedded directory and was
      # the root cause of bug F4 (two clients with diverging collections).
      # Now MemoryModule shares the same singleton client as MemoryAPI and
      # the rest of the server, all rooted at storage/vectors/.
      qdrant_path = vectors_path

      self._flash_memory = FlashMemory(
        default_ttl_seconds=final_config.get("flash_ttl_seconds", 1800)
      )

      self._ram_context = RAMContext(
        flash_memory=self._flash_memory,
        max_entries=final_config.get("ram_max_entries", 100)
      )

      crypto = get_server_state().crypto_provider

      self._persistence = PersistenceManager(
        db_path=db_path,
        qdrant_path=qdrant_path,
        collection_name="nexe_memory",
        vector_size=DEFAULT_VECTOR_SIZE,
        crypto_provider=crypto
      )

      self._pipeline = IngestionPipeline(
        flash_memory=self._flash_memory,
        persistence=self._persistence,
        embedding_model=None
      )

      # Initialize MemoryService (v1 facade)
      try:
        from .memory_service import MemoryService
        self._memory_service = MemoryService(
          db_path=vectors_path / "memory_v1.db",
          qdrant_path=str(qdrant_path),
        )
        await self._memory_service.initialize()
        logger.info("MemoryService initialized")
      except Exception as e:
        logger.warning("MemoryService init failed (non-fatal): %s", e)
        self._memory_service = None

      preload_limit = final_config.get("ram_preload_limit", 50)
      preload_types = final_config.get("ram_preload_entry_types", ["episodic"])

      try:
        recent_entries = await self._persistence.get_recent(
          limit=preload_limit,
          entry_types=preload_types,
          exclude_expired=True
        )

        preload_count = 0
        for entry in recent_entries:
          await self._flash_memory.store(entry)
          preload_count += 1

        logger.debug(f"Memory preload: {preload_count}/{preload_limit} entries loaded")
      except Exception as e:
        logger.warning(f"Memory preload failed: {e}")

      self._initialized = True

      logger.debug(f"MemoryModule initialized v{self.version}")

      return True

    except Exception as e:
      logger.error(f"MemoryModule init failed: {e}", exc_info=True)
      raise

  async def shutdown(self) -> bool:
    """
    Graceful module shutdown.

    Returns:
      bool: True if shutdown correct
    """
    if not self._initialized:
      logger.debug("MemoryModule not initialized, skip shutdown")
      return True

    try:
      logger.debug("MemoryModule shutting down...")

      if self._flash_memory:
        await self._flash_memory.cleanup_expired()

      if self._persistence:
        self._persistence.close()

      if self._pipeline:
        self._pipeline.close()

      if self._memory_service:
        await self._memory_service.shutdown()

      self._initialized = False
      self._flash_memory = None
      self._ram_context = None
      self._persistence = None
      self._pipeline = None
      self._memory_service = None

      logger.debug("MemoryModule shutdown complete")
      return True

    except Exception as e:
      logger.error(f"MemoryModule shutdown failed: {e}", exc_info=True)
      return False

  def get_health(self) -> Dict[str, Any]:
    """
    Gets module health status.

    Returns:
      Dict with status, checks, metadata
    """
    from .health import check_health

    return check_health(self)

  def get_info(self) -> Dict[str, Any]:
    """
    Gets module information.

    Returns:
      Dict with manifest metadata
    """
    return {
      "module_id": self.module_id,
      "name": self.name,
      "version": self.version,
      "description": self.manifest.get("description", ""),
      "capabilities": self.manifest.get("capabilities", []),
      "initialized": self._initialized,
      "config": self.manifest.get("config", {})
    }

  async def ingest(self, entry: MemoryEntry) -> bool:
    """
    Ingests an entry into memory via pipeline.

    Args:
      entry: MemoryEntry to process

    Returns:
      bool: True if successfully ingested
    """
    if not self._initialized or not self._pipeline:
      raise RuntimeError("MemoryModule not initialized. Call initialize() first.")

    return await self._pipeline.ingest(entry)

  async def ingest_batch(self, entries: list) -> dict:
    """
    Ingests multiple entries in batch.

    Args:
      entries: List of MemoryEntry to process

    Returns:
      dict: Batch stats
    """
    if not self._initialized or not self._pipeline:
      raise RuntimeError("MemoryModule not initialized. Call initialize() first.")

    return await self._pipeline.ingest_batch(entries)

  def get_metrics(self) -> Dict[str, Any]:
    """
    Gets Prometheus metrics for the module.

    Returns:
      Dict with counters, gauges, histograms
    """
    from .metrics import get_metrics

    metrics = get_metrics()

    metrics.update_from_module(self)

    return metrics.get_metrics()

__all__ = ["MemoryModule", "get_memory_service"]
