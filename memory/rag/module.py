"""
────────────────────────────────────
Server Nexe
Author: Jordi Goy 
Location: memory/rag/module.py
Description: Main RAG Module - Multi-source Retrieval-Augmented Generation system.

www.jgoy.net · https://server-nexe.org
────────────────────────────────────
"""

from typing import Optional, Dict, Any, List
import threading
import time
import structlog

from personality.i18n import get_i18n
from memory.rag_sources.base import AddDocumentRequest, SearchRequest, SearchHit

logger = structlog.get_logger()

# #1004: RAG_SEARCHES and RAG_SEARCH_DURATION were declared in
# core/metrics/registry.py, exported in its __all__ and imported by nobody —
# frozen at zero since the day they were written. `search()` below is the
# canonical entry point and already carries `source`, which is exactly the
# label both metrics take.
#
# Module-level and guarded, NOT the lazy `_get_metrics()` helper that
# memory/memory/api/documents.py uses. That helper exists to retry an import
# per call; there is nothing to retry here — prometheus-client is a hard pin
# in requirements.txt, core/metrics/registry.py imports nothing beyond logging
# and prometheus_client (no cycle), and the whole server refuses to start
# without it anyway (core/server/factory_routers.py mounts /metrics
# unconditionally). What the guard buys is the rule that instrumentation must
# never take the RAG search path down with it — and, per #1005, it says so out
# loud instead of passing.
try:
  from core.metrics.registry import RAG_SEARCHES, RAG_SEARCH_DURATION
except ImportError as _metrics_exc:  # pragma: no cover - see test_1004
  RAG_SEARCHES = None  # type: ignore[assignment]
  RAG_SEARCH_DURATION = None  # type: ignore[assignment]
  logger.warning(
    "rag_metrics_unavailable",
    error=str(_metrics_exc),
    impact="RAG search counter and duration histogram will stay at zero; "
           "search itself is unaffected",
  )

# The import succeeding is not the same as the write succeeding. See
# _record_search_metrics: a metric that raises on `.labels()` must not become
# the answer to a search that already ran.
_metrics_write_failed_reported = False

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

  def __init__(self) -> None:
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

  async def initialize(self, context: Optional[Dict[str, Any]] = None) -> bool:
    """
    Initializes the RAG module.

    Loads RAG sources (PersonalityRAG) and prepares the module for operation.

    Args:
      context: Protocol initialize context (D-C). Module overrides under
        context['config'].

    Returns:
      bool: True if initialization correct

    Raises:
      RuntimeError: If already initialized
    """
    if self._initialized:
      logger.warning("rag_module_already_initialized")
      return True

    try:
      from core.modules.protocol import module_config_from_context
      config = module_config_from_context(context, "rag")
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

    # Only the search itself is timed — everything above is argument checking
    # that would drag the histogram down towards zero and hide the real
    # latency of the backend.
    _started = time.perf_counter()
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

    finally:
      self._record_search_metrics(source, time.perf_counter() - _started)

  @staticmethod
  def _record_search_metrics(source: str, elapsed_seconds: float) -> None:
    """Publish one completed search attempt to Prometheus (#1004).

    Counted AND timed on both outcomes on purpose. Both metrics carry a single
    `source` label and no `status`, so there is no way to tell the two apart in
    the series; a counter that dropped failures would under-report load exactly
    when the backend is breaking, and a histogram that dropped them would lose
    the slow timeouts that are the whole reason to keep a latency histogram.
    Keeping both on the same rule also keeps the pair consistent:
    `core_rag_search_duration_seconds_count` always equals
    `core_rag_searches_total`, which is what a Prometheus reader expects of a
    counter and a histogram sharing a label set.

    This deliberately does NOT match `self._stats["searches_performed"]`, which
    counts successes only and is what the module reports in its health block.
    Separating the two in the series would need a `status` label — a change to
    the registry's label set, filed rather than smuggled in here.

    Nothing this method does can reach the caller. It runs from the `finally`
    of `search()`, so an exception raised here does not merely add noise — it
    REPLACES the search's outcome: a search that completed comes back as a
    500, and a search that failed comes back reporting the metric error while
    the real diagnosis (the backend that went down) survives only in
    `__context__`, which no HTTP body ever shows. The `None` guard above is not
    enough for that: it covers "the registry could not be imported", not "the
    registry is there and the write raises". The realistic trigger is the very
    follow-up this finding files — adding a `status` label to the registry
    makes every `labels(source=...)` call raise `ValueError: Incorrect label
    names`, which would turn EVERY RAG search into a 500 from a change that
    touched no search code at all.

    Reported once per process, then silent. What is lost here is a pair of
    counters — a uniform loss that one line describes in full, the same rule
    `memory/memory/api/documents.py` follows — and the failure is
    deterministic: a label-set mismatch fails identically on every search from
    start-up, so repeating the line adds no information while a chat session
    fires several searches a turn.
    """
    global _metrics_write_failed_reported
    if RAG_SEARCHES is None or RAG_SEARCH_DURATION is None:
      return
    try:
      RAG_SEARCHES.labels(source=source).inc()
      RAG_SEARCH_DURATION.labels(source=source).observe(elapsed_seconds)
    except Exception as exc:
      # Deliberately bare: whatever prometheus_client (or a mis-shaped
      # registry) throws, a search that already ran must still be the answer.
      if not _metrics_write_failed_reported:
        _metrics_write_failed_reported = True
        logger.warning(
          "rag_metrics_write_failed",
          error=str(exc),
          source=source,
          impact="core_rag_searches_total and core_rag_search_duration_seconds "
                 "will stay flat until the process restarts; search itself is "
                 "unaffected. Not repeated for later searches.",
        )

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

# WS6-01: get_file_rag() and its FileRAGSource singleton were retired — the
# class never existed anywhere in the repo (the import was a permanent
# ImportError and the upload surface a permanent 501). File uploads go
# through POST /ui/upload (web_ui_module), which is the real, working path.

__all__ = ["RAGModule"]
