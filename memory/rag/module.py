"""
────────────────────────────────────
Server Nexe
Version: 0.8
Author: Jordi Goy 
Location: memory/rag/module.py
Description: Main RAG Module - Multi-source Retrieval-Augmented Generation system.

www.jgoy.net · https://server-nexe.org
────────────────────────────────────
"""

import os
from typing import Optional, Dict, Any, List
import threading
import structlog

from personality.i18n import get_i18n
from memory.rag_sources.base import AddDocumentRequest, SearchRequest, SearchHit

logger = structlog.get_logger()

class RAGModule:
  """
  RAG Module - Multi-source RAG system with Qdrant.

  Singleton that manages:
  - Vector stores (Qdrant)
  - Search i retrieval
  - TransactionLedger (multi-store coherence)
  - WriteCoordinator (single-writer policy)

  Features:
  - Base Singleton structure
  - Health checks
  - VectorStore
  - TransactionLedger integration

  Usage:
    module = RAGModule.get_instance()
    await module.initialize()
    health = module.get_health()
  """

  _instance: Optional['RAGModule'] = None
  _initialized: bool = False
  _singleton_lock = threading.Lock()

  def __init__(self):
    """Private constructor. Use get_instance()."""
    if RAGModule._instance is not None:
      i18n = get_i18n()
      raise RuntimeError(
        i18n.t("rag.singleton_error", "RAGModule is Singleton. Use get_instance()")
      )

    from .constants import MANIFEST, MODULE_ID

    self.module_id = MODULE_ID
    self.manifest = MANIFEST
    self.name = MANIFEST["name"]
    self.version = MANIFEST["version"]

    self._sources: Dict[str, Any] = {}

    self._stats = {
      "documents_added": 0,
      "searches_performed": 0,
      "total_chunks": 0,
      "cache_hit_rate": 0.0
    }

    self._vector_store = None
    self._ledger = None
    self._write_coordinator = None

    logger.info(
      "rag_module_created",
      module_id=self.module_id,
      version=self.version
    )

  @classmethod
  def get_instance(cls) -> 'RAGModule':
    """
    Get Singleton instance of the module (thread-safe).

    Returns:
      RAGModule: Unique instance of the module
    """
    with cls._singleton_lock:
      if cls._instance is None:
        cls._instance = cls()
    return cls._instance

  async def initialize(self, config: Optional[Dict[str, Any]] = None) -> bool:
    """
    Initializes the RAG module.

    Loads RAG sources (PersonalityRAG) and prepares the module for operation.

    Args:
      config: Optional configuration (default from manifest)

    Returns:
      bool: True if initialization correct

    Raises:
      RuntimeError: If already initialized
    """
    if self._initialized:
      logger.warning("rag_module_already_initialized")
      return True

    try:
      final_config = {**self.manifest.get("default_config", {})}
      if config:
        final_config.update(config)

      logger.info(
        "rag_module_initializing",
        config=final_config
      )

      from memory.rag_sources.personality import PersonalityRAG

      logger.debug("Loading PersonalityRAG source...")
      personality_rag = PersonalityRAG()

      self._sources = {
        "personality": personality_rag
      }

      logger.info(
        "rag_sources_loaded",
        sources=list(self._sources.keys())
      )

      self._stats = {
        "documents_added": 0,
        "searches_performed": 0,
        "total_chunks": 0,
        "cache_hit_rate": 0.0
      }

      self._initialized = True

      logger.info(
        "rag_module_initialized",
        version=self.version,
        sources_count=len(self._sources),
        initialized=self._initialized
      )

      return True

    except Exception as e:
      logger.error(
        "rag_module_init_failed",
        error=str(e),
        exc_info=True
      )
      raise

  async def shutdown(self) -> bool:
    """
    Graceful module shutdown.

    Cleanup:
    - Flush pending writes
    - Close vector store
    - Shutdown WriteCoordinator

    Returns:
      bool: True if shutdown correct
    """
    if not self._initialized:
      logger.warning("rag_module_not_initialized_shutdown")
      return True

    try:
      logger.info("rag_module_shutting_down")

      self._initialized = False
      self._vector_store = None
      self._ledger = None
      self._write_coordinator = None

      logger.info("rag_module_shutdown_complete")
      return True

    except Exception as e:
      logger.error(
        "rag_module_shutdown_failed",
        error=str(e),
        exc_info=True
      )
      return False

  async def add_document(
    self,
    request: AddDocumentRequest,
    source: str = "personality"
  ) -> str:
    """
    Add document to a RAG source.

    Args:
      request: AddDocumentRequest with text and metadata
      source: RAG source name (default: "personality")

    Returns:
      doc_id: Unique document ID

    Raises:
      RuntimeError: If module not initialized
      ValueError: If source unknown
    """
    if not self._initialized:
      raise RuntimeError("RAGModule not initialized. Call initialize() first.")

    if source not in self._sources:
      raise ValueError(
        f"Unknown RAG source: {source}. "
        f"Available: {list(self._sources.keys())}"
      )

    rag_source = self._sources[source]

    try:
      doc_id = await rag_source.add_document(request)

      self._stats["documents_added"] += 1

      logger.info(
        "document_added",
        doc_id=doc_id,
        source=source,
        text_len=len(request.text),
        total_docs=self._stats["documents_added"]
      )

      return doc_id

    except Exception as e:
      logger.error(
        "add_document_failed",
        error=str(e),
        source=source,
        exc_info=True
      )
      raise

  async def search(
    self,
    request: SearchRequest,
    source: str = "personality"
  ) -> List[SearchHit]:
    """
    Search relevant documents.

    Args:
      request: SearchRequest with query and top_k
      source: RAG source name (default: "personality")

    Returns:
      List[SearchHit]: Results ordered by score

    Raises:
      RuntimeError: If module not initialized
      ValueError: If source unknown
    """
    if not self._initialized:
      raise RuntimeError("RAGModule not initialized. Call initialize() first.")

    if source not in self._sources:
      raise ValueError(
        f"Unknown RAG source: {source}. "
        f"Available: {list(self._sources.keys())}"
      )

    rag_source = self._sources[source]

    try:
      results = await rag_source.search(request)

      self._stats["searches_performed"] += 1

      logger.info(
        "search_performed",
        query=request.query,
        source=source,
        results_count=len(results),
        total_searches=self._stats["searches_performed"]
      )

      return results

    except Exception as e:
      logger.error(
        "search_failed",
        error=str(e),
        source=source,
        query=request.query,
        exc_info=True
      )
      raise

  def get_source(self, name: str) -> Any:
    """
    Gets a RAG source by name.

    Args:
      name: Source name

    Returns:
      RAG source instance

    Raises:
      ValueError: If source does not exist
    """
    if name not in self._sources:
      raise ValueError(
        f"Unknown RAG source: {name}. "
        f"Available: {list(self._sources.keys())}"
      )
    return self._sources[name]

  def list_sources(self) -> List[str]:
    """
    Lists available RAG sources.

    Returns:
      List of source names
    """
    return list(self._sources.keys())

  def get_health(self) -> Dict[str, Any]:
    """
    Gets module health status.

    Delegates to health.py for detailed checks.

    Returns:
      Dict with status, checks, metadata
    """
    from .health import check_health

    return check_health(self)

  def get_info(self) -> Dict[str, Any]:
    """
    Gets module information.

    Returns:
      Dict with manifest metadata, sources, and stats
    """
    total_chunks = 0
    if self._initialized:
      for source in self._sources.values():
        health = source.health()
        total_chunks += health.get("num_chunks", 0)

    current_stats = self._stats.copy() if self._initialized else {}
    if self._initialized:
      current_stats["total_chunks"] = total_chunks

    return {
      "module_id": self.module_id,
      "name": self.name,
      "version": self.version,
      "description": self.manifest.get("description", ""),
      "capabilities": self.manifest.get("capabilities", []),
      "initialized": self._initialized,
      "sources": list(self._sources.keys()) if self._initialized else [],
      "stats": current_stats,
      "config": self.manifest.get("default_config", {})
    }

_file_rag_instance = None
_file_rag_lock = threading.Lock()

def get_file_rag():
  """
  Get or create singleton FileRAGSource instance (thread-safe).

  Returns:
    FileRAGSource: Singleton instance for file uploads
  """
  global _file_rag_instance

  with _file_rag_lock:
    if _file_rag_instance is None:
      from memory.rag_sources.file import FileRAGSource
      _qdrant_url = (
        os.environ.get("NEXE_QDRANT_URL")
        or f"http://{os.environ.get('NEXE_QDRANT_HOST', 'localhost')}:{os.environ.get('NEXE_QDRANT_PORT', '6333')}"
      )
      _file_rag_instance = FileRAGSource(
        qdrant_url=_qdrant_url,
        table_name="uploaded_files"
      )
  return _file_rag_instance

__all__ = ["RAGModule", "get_file_rag"]
