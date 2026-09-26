"""
────────────────────────────────────
Server Nexe
Author: Jordi Goy
Location: memory/rag/module.py
Description: RAG module - a thin facade over the retrieval sources in core/rag/.

ADR-008 E2. This module used to own its own sources: a dict built at
initialize() holding one `PersonalityRAG` — an in-memory keyword matcher that
nothing ever wrote to in production, searched by nobody but this module's CLI,
and described as structurally empty by ADR-002:68. The chat never went
through it; it retrieves through `core/rag/` (`source_for`, the registry) from
`core/endpoints/chat_rag.py`. Two retrieval stacks, one of them dead.

So the module no longer keeps sources. It ANSWERS about the ones the turn
uses: the three system collections (`SYSTEM_COLLECTIONS`) plus whatever is
registered (`registered_names()`), and its `search()` asks a source exactly
the way the turn does — `source_for(name).search(memory, RAGQuery(...))` — so
what the CLI shows is what the chat would retrieve from that source.

The imports of `core/` below are deferred on purpose, like the rest of this
package (`health.py`): memory/ must not import core/ at import time, and the
layering gate freezes those edges.

www.jgoy.net · https://server-nexe.org
────────────────────────────────────
"""

from typing import Optional, Dict, Any, List
import threading
import unicodedata
import structlog

from personality.i18n import get_i18n

logger = structlog.get_logger()


class RAGModule:
  """
  RAG Module - introspection and a CLI door onto the chat's retrieval sources.

  Singleton loaded by the module manager by class name
  (`core/modules/module_manager.py::_resolve_memory_class_name`). Owns no
  source and no store: sources live in `core/rag/` (ADR-008 E2).

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

    # ADR-008 E2: only what this module really measures. `documents_added`
    # went with add_document(); `total_chunks` was summed from a `health()`
    # the real sources do not have; `cache_hit_rate` was never written.
    self._stats: Dict[str, Any] = {"searches_performed": 0}

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

    There is nothing to load any more (ADR-008 E2: the sources live in
    `core/rag/` and exist without this module); what is left is the lifecycle
    contract the module manager relies on.

    Args:
      context: Protocol initialize context (D-C). Module overrides under
        context['config'].

    Returns:
      bool: True if initialization correct
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

      self._stats = {"searches_performed": 0}
      self._initialized = True

      logger.info(
        "rag_module_initialized",
        version=self.version,
        sources=self.list_sources(),
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

    Returns:
      bool: True if shutdown correct
    """
    if not self._initialized:
      logger.warning("rag_module_not_initialized_shutdown")
      return True

    logger.info("rag_module_shutting_down")
    self._initialized = False
    logger.info("rag_module_shutdown_complete")
    return True

  def list_sources(self) -> List[str]:
    """
    The sources the chat retrieves from: the three system collections plus
    every registered source — the same union `chat_rag` builds.

    `SYSTEM_COLLECTIONS` is the one place the three names are spelled (#896);
    `core/rag/collections.py` builds its sources from the same constants.

    Does not include collections a plugin created at runtime without
    registering a source: those are discovered live from the store by the
    turn, and this module has no store to ask.

    Returns:
      List of source names, system first, no duplicates
    """
    from core.memory_access import SYSTEM_COLLECTIONS
    from core.rag.registry import registered_names

    return list(dict.fromkeys([*SYSTEM_COLLECTIONS, *registered_names()]))

  def get_source(self, name: str) -> Any:
    """
    Gets a RAG source by name.

    `source_for()` never refuses — for an unknown name it builds #896's
    generic fallback — so the membership guard lives here: this module
    answers for the sources it lists, and a typo must be an error, not a
    search of a collection that does not exist.

    Args:
      name: Source name

    Returns:
      The `RAGSource` that answers for `name`

    Raises:
      ValueError: If source does not exist
    """
    available = self.list_sources()
    if name not in available:
      raise ValueError(
        f"Unknown RAG source: {name}. "
        f"Available: {available}"
      )
    from core.rag.collections import source_for

    return source_for(name)

  async def search(
    self,
    query: str,
    source: str,
    top_k: Optional[int] = None,
    lang: str = "en",
  ) -> List[Any]:
    """
    Search one source the way the chat does.

    The query is NFKC-normalized (the ingest path's normalization, which the
    turn mirrors) and asked of `source_for(source)` with the real MemoryAPI.
    Each source applies its own tuned threshold, top_k and language filter,
    so `top_k` can only cap what the source returns, never widen it.

    Prometheus metrics are NOT recorded here: they measure the SERVER's
    retrieval and are written in `core/endpoints/chat_rag.py`; this is a CLI
    door, run in a process with no /metrics to scrape.

    Args:
      query: Text to search for
      source: Source name (one of `list_sources()`)
      top_k: Optional cap on the number of results
      lang: Language of the query (`user_knowledge` filters by it)

    Returns:
      The source's results (e.g. `SearchResult`), best first

    Raises:
      RuntimeError: If module not initialized
      ValueError: If source unknown
    """
    if not self._initialized:
      raise RuntimeError("RAGModule not initialized. Call initialize() first.")

    rag_source = self.get_source(source)

    from core.rag.source import RAGQuery
    from memory.memory.api.v1 import get_memory_api

    memory = await get_memory_api()
    text = unicodedata.normalize("NFKC", query)
    results = await rag_source.search(memory, RAGQuery(text=text, lang=lang))
    if top_k is not None:
      results = results[:top_k]

    self._stats["searches_performed"] += 1
    logger.info(
      "search_performed",
      source=source,
      results_count=len(results),
      total_searches=self._stats["searches_performed"]
    )
    return results

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
    return {
      "module_id": self.module_id,
      "name": self.name,
      "version": self.version,
      "description": self.manifest.get("description", ""),
      "capabilities": self.manifest.get("capabilities", []),
      "initialized": self._initialized,
      "sources": self.list_sources() if self._initialized else [],
      "stats": self._stats.copy() if self._initialized else {},
      "config": self.manifest.get("default_config", {})
    }

# WS6-01: get_file_rag() and its FileRAGSource singleton were retired — the
# class never existed anywhere in the repo (the import was a permanent
# ImportError and the upload surface a permanent 501). File uploads go
# through POST /ui/upload (web_ui_module), which is the real, working path.

__all__ = ["RAGModule"]
