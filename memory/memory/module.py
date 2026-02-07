"""
────────────────────────────────────
Server Nexe
Version: 0.8
Author: Jordi Goy 
Location: memory/memory/module.py
Description: Main Memory Module - Flash Memory + RAM Context + Persistence System.

www.jgoy.net
────────────────────────────────────
"""

from typing import Optional, Dict, Any
import threading
import logging
from pathlib import Path

from personality.i18n import get_i18n
from personality.i18n.resolve import t_modular

from .engines.flash_memory import FlashMemory
from .engines.ram_context import RAMContext
from .engines.persistence import PersistenceManager
from .pipeline.ingestion import IngestionPipeline

logger = logging.getLogger(__name__)

def _t(key: str, fallback: str, **kwargs) -> str:
  return t_modular(f"memory.logs.{key}", fallback, **kwargs)

class MemoryModule:
  """
  Memory Module - Flash Memory + RAM Context + Persistence.

  Singleton that manages:
  - Flash Memory (temporary cache for results)
  - RAM Context (current session context)
  - Persistence (save/load sessions)

  Features (PRE-PHASE 1):
  - Base Singleton structure
  - Health checks
  - Flash Memory preparation (PHASE 4)

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

    from core.container import get_service
    from .constants import MANIFEST, MODULE_ID

    self.module_id = MODULE_ID
    self.manifest = MANIFEST
    self.name = MANIFEST["name"]
    self.version = MANIFEST["version"]
    
    # Dependencies obtained via DI Container instead of hacks
    self.i18n = get_service("i18n")
    self.config = get_service("config")

    self._flash_memory = None
    self._ram_context = None
    self._persistence = None
    self._pipeline = None

    logger.debug(_t(
      "created",
      "MemoryModule created: {module_id} v{version} (DI Container active)",
      module_id=self.module_id,
      version=self.version
    ))

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
      logger.debug(_t("already_initialized", "MemoryModule already initialized"))
      return True

    try:
      from core.container import get_service
      
      final_config = {**self.manifest.get("config", {})}
      if config:
        final_config.update(config)

      logger.debug(_t("initializing", "MemoryModule initializing..."))

      project_root = get_service("project_root")
      if not project_root:
        from pathlib import Path
        project_root = Path.cwd()
        logger.warning(_t(
          "project_root_fallback",
          "project_root not found in Container, using cwd: {path}",
          path=project_root
        ))

      # ✅ FIX: Unify paths with installer (storage/vectors/)
      vectors_path = project_root / "storage" / "vectors"
      db_path = vectors_path / "metadata_memory.db"
      qdrant_path = vectors_path / "qdrant_local"

      self._flash_memory = FlashMemory(
        default_ttl_seconds=final_config.get("flash_ttl_seconds", 1800)
      )

      self._ram_context = RAMContext(
        flash_memory=self._flash_memory,
        max_entries=final_config.get("ram_max_entries", 100)
      )

      self._persistence = PersistenceManager(
        db_path=db_path,
        qdrant_path=qdrant_path,
        collection_name="nexe_memory",
        vector_size=768
      )

      self._pipeline = IngestionPipeline(
        flash_memory=self._flash_memory,
        persistence=self._persistence,
        embedding_model=None
      )

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

        logger.debug(_t(
          "preload_loaded",
          "Memory preload: {count}/{limit} entries loaded",
          count=preload_count,
          limit=preload_limit
        ))
      except Exception as e:
        logger.warning(_t(
          "preload_failed",
          "Memory preload failed: {error}",
          error=str(e)
        ))

      self._initialized = True

      logger.debug(_t(
        "initialized",
        "MemoryModule initialized v{version}",
        version=self.version
      ))

      return True

    except Exception as e:
      logger.error(_t(
        "init_failed",
        "MemoryModule init failed: {error}",
        error=str(e)
      ), exc_info=True)
      raise

  async def shutdown(self) -> bool:
    """
    Graceful module shutdown.

    Returns:
      bool: True if shutdown correct
    """
    if not self._initialized:
      logger.debug(_t("shutdown_skip", "MemoryModule not initialized, skip shutdown"))
      return True

    try:
      logger.debug(_t("shutdown_start", "MemoryModule shutting down..."))

      if self._flash_memory:
        await self._flash_memory.cleanup_expired()

      if self._persistence:
        self._persistence.close()

      if self._pipeline:
        self._pipeline.close()

      self._initialized = False
      self._flash_memory = None
      self._ram_context = None
      self._persistence = None
      self._pipeline = None

      logger.debug(_t("shutdown_complete", "MemoryModule shutdown complete"))
      return True

    except Exception as e:
      logger.error(_t(
        "shutdown_failed",
        "MemoryModule shutdown failed: {error}",
        error=str(e)
      ), exc_info=True)
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

  async def ingest(self, entry: "MemoryEntry") -> bool:
    """
    Ingests an entry into memory via pipeline.

    Args:
      entry: MemoryEntry to process

    Returns:
      bool: True if successfully ingested
    """
    if not self._initialized or not self._pipeline:
      i18n = get_i18n()
      raise RuntimeError(
        i18n.t(
          "memory.not_initialized",
          "MemoryModule not initialized. Call initialize() first."
        )
      )

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
      i18n = get_i18n()
      raise RuntimeError(
        i18n.t(
          "memory.not_initialized",
          "MemoryModule not initialized. Call initialize() first."
        )
      )

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

__all__ = ["MemoryModule"]
