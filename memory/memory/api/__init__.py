"""
────────────────────────────────────
Server Nexe
Author: Jordi Goy 
Location: memory/memory/api/__init__.py
Description: Memory API Facade - Generic API for external modules.

www.jgoy.net · https://server-nexe.org
────────────────────────────────────
"""

from __future__ import annotations

import asyncio
import logging
import os
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import TYPE_CHECKING, Any, Dict, List, Optional

if TYPE_CHECKING:
    from qdrant_client import QdrantClient

from ..constants import DEFAULT_EMBEDDING_MODEL, DEFAULT_VECTOR_SIZE
from ..config import IngestConfig

from .models import (
  CollectionInfo,
  CollectionNotFoundError,
  Document,
  DocumentNotFoundError,
  InvalidCollectionNameError,
  MemoryAPIError,
  SearchResult,
  validate_collection_name,
  COLLECTION_NAME_PATTERN,
)
from .operations import (
  cleanup_expired,
  collection_exists,
  count_documents,
  create_collection,
  delete_collection,
  delete_document,
  get_document,
  hex_to_uuid,
  list_collections,
  search_documents,
  store_document,
  store_documents_batch,
)

logger = logging.getLogger(__name__)

class MemoryAPI:
  """
  API genèrica per accés a Qdrant des de mòduls externs.

  Aquesta classe ofereix una interfície simplificada per:
  - Crear collections per mòduls específics
  - Emmagatzemar text amb embeddings
  - Cercar per similitud semàntica
  - Gestionar documents (get, delete)

  IMPORTANT: Aquesta API és agnòstica respecte a les collections.
  No defineix collections específiques com "personality" o "conversations".
  Cada mòdul consumidor (Anàlisi Contextual, Memory, Auditor) crea les seves pròpies
  collections segons les seves necessitats.

  Example:
    async with MemoryAPI() as memory:
      await memory.create_collection("nexe_knowledge")
      await memory.store("text", "nexe_knowledge", {"type": "road"})
  """

  DEFAULT_QDRANT_URL = os.getenv(
    "NEXE_QDRANT_URL",
    f"http://{os.getenv('NEXE_QDRANT_HOST', 'localhost')}:{os.getenv('NEXE_QDRANT_PORT', '6333')}"
  )
  DEFAULT_VECTOR_SIZE = DEFAULT_VECTOR_SIZE

  DEFAULT_QDRANT_PATH = Path("storage/vectors")

  def __init__(
    self,
    qdrant_url: Optional[str] = None,
    qdrant_path: Optional[Path] = None,
    embedding_model: str = DEFAULT_EMBEDDING_MODEL,
    crypto_provider=None,
    text_store_path: Optional[Path] = None,
    ingest_config: Optional[IngestConfig] = None,
  ):
    """
    Inicialitza Memory API.

    Args:
      qdrant_url: URL del servidor Qdrant (default: http://localhost:6333)
      qdrant_path: Path local per mode fitxer/test (prioritat sobre qdrant_url).
                   Default: storage/vectors (embedded mode)
      embedding_model: Model d'embeddings (default: paraphrase-multilingual-mpnet-base-v2)
      ingest_config: SSOT for ingest pipeline tunables (batch sizes, pre-warm,
                     mega-batch). Default IngestConfig() preserves the exact
                     historical behaviour (store_batch_size=50, no embed
                     batch_size override, no pre-warm, no mega-batch).
                     Introduced by bug #16 to remove hardcodes.
    """
    self.qdrant_url = qdrant_url or self.DEFAULT_QDRANT_URL
    self.qdrant_path = qdrant_path if qdrant_path is not None else self.DEFAULT_QDRANT_PATH
    self.embedding_model = embedding_model
    self.vector_size = self.DEFAULT_VECTOR_SIZE
    self.ingest_config = ingest_config if ingest_config is not None else IngestConfig()

    self._crypto = crypto_provider
    self._text_store_path = text_store_path
    self._text_store = None
    self._qdrant: Optional[QdrantClient] = None
    self._embedder = None
    self._executor = ThreadPoolExecutor(max_workers=4)
    self._initialized = False

    # Bug #16 perf counters (opt-in via ingest_config.perf_logging).
    # Zero overhead when disabled: the counters are only mutated if the
    # flag is True at call sites. All durations are monotonic nanoseconds
    # from time.perf_counter_ns(). See reset_perf_counters() and
    # get_perf_snapshot() for the public API consumed by the benchmark.
    self._perf: Dict[str, int] = {
      "embed_ns": 0,
      "embed_calls": 0,
      "chunks_embedded": 0,
      "store_total_ns": 0,
      "store_calls": 0,
      "chunks_stored": 0,
      "warmup_ns": 0,
    }

    if qdrant_path:
      logger.info(
        "MemoryAPI created (qdrant_path=%s, model=%s)",
        self.qdrant_path,
        self.embedding_model,
      )
    else:
      logger.info(
        "MemoryAPI created (qdrant_url=%s, model=%s)",
        self.qdrant_url,
        self.embedding_model,
      )

  async def initialize(self) -> bool:
    """Inicialitza connexions i models."""
    if self._initialized:
      logger.warning("MemoryAPI already initialized")
      return True

    try:
      # Use local mode if qdrant_path is set, otherwise connect to URL
      from core.qdrant_pool import get_qdrant_client

      if self.qdrant_path:
        self._qdrant = get_qdrant_client(path=str(self.qdrant_path))
        logger.info("MemoryAPI initialized (path=%s)", self.qdrant_path)
      else:
        self._qdrant = get_qdrant_client(url=self.qdrant_url)
        logger.info("MemoryAPI initialized (url=%s)", self.qdrant_url)

      # Initialize text store if path provided
      if self._text_store_path:
        from .text_store import TextStore
        self._text_store = TextStore(
          db_path=self._text_store_path,
          crypto_provider=self._crypto,
        )
        logger.info("TextStore initialized at %s", self._text_store_path)

      await self._init_embedder()
      self._initialized = True
      return True

    except Exception as e:
      logger.error("MemoryAPI initialization failed: %s", e)
      raise

  async def _init_embedder(self):
    """Inicialitza el model d'embeddings."""
    loop = asyncio.get_running_loop()
    # Bug #16: forward `threads` to fastembed so ORT caps its intra-op
    # thread pool. Default (None) lets fastembed decide; ingest_config
    # currently sets 6 to avoid Apple Silicon E-core contention.
    embed_threads = self.ingest_config.embed_threads

    def _load_model():
      from fastembed import TextEmbedding
      kwargs = {}
      if embed_threads is not None:
        kwargs["threads"] = embed_threads
      try:
        return TextEmbedding(self.embedding_model, **kwargs)
      except Exception as e:
        raise RuntimeError(
            f"Embedding model '{self.embedding_model}' not available locally. "
            f"Run the installer to download it. Error: {e}"
        ) from e

    self._embedder = await loop.run_in_executor(self._executor, _load_model)
    import os as _os
    logger.info("TextEmbedding initialized (PID=%s, model=%s)", _os.getpid(), self.embedding_model)

  def _ensure_initialized(self):
    """Verify that the API is initialized."""
    if not self._initialized:
      raise RuntimeError("MemoryAPI not initialized. Call initialize() first.")

  async def close(self):
    """Tanca connexions i allibera recursos.

    NOTE: Do NOT close the Qdrant client here — it comes from the shared pool
    (core.qdrant_pool) and other consumers depend on it. The pool handles
    lifecycle via close_qdrant_client() at shutdown.
    """

    if self._executor:
      self._executor.shutdown(wait=True)

    if self._text_store:
      self._text_store.close()
      self._text_store = None

    self._qdrant = None
    self._embedder = None
    self._initialized = False
    logger.info("MemoryAPI closed")

  async def __aenter__(self):
    """Context manager entry."""
    await self.initialize()
    return self

  async def __aexit__(self, exc_type, exc_val, exc_tb):
    """Context manager exit."""
    await self.close()

  async def create_collection(
    self, name: str, vector_size: int = DEFAULT_VECTOR_SIZE, distance: str = "cosine"
  ) -> bool:
    """
    Crea una nova collection.

    Args:
      name: Nom seguint naming convention {modul}_{tipus}
      vector_size: Dimensió dels vectors (default: 768)
      distance: Mètrica ("cosine", "euclid", "dot")

    Returns:
      bool: True si creada, False si ja existeix
    """
    self._ensure_initialized()
    return await create_collection(
      self._qdrant, self._executor, name, vector_size, distance
    )

  async def delete_collection(self, name: str) -> bool:
    """Elimina una collection."""
    self._ensure_initialized()
    return await delete_collection(self._qdrant, self._executor, name)

  async def list_collections(self) -> List[CollectionInfo]:
    """Llista totes les collections."""
    self._ensure_initialized()
    return await list_collections(self._qdrant, self._executor)

  async def collection_exists(self, name: str) -> bool:
    """Comprova si una collection existeix."""
    self._ensure_initialized()
    return await collection_exists(self._qdrant, self._executor, name)

  async def store(
    self,
    text: str,
    collection: str,
    metadata: Optional[Dict[str, Any]] = None,
    doc_id: Optional[str] = None,
    ttl_seconds: Optional[int] = None,
  ) -> str:
    """
    Emmagatzema text amb embedding.

    Args:
      text: Contingut textual
      collection: Nom de la collection
      metadata: Metadades addicionals
      doc_id: ID personalitzat (auto-generat si None)
      ttl_seconds: Temps de vida (None = permanent)

    Returns:
      str: ID del document creat
    """
    self._ensure_initialized()

    if not await self.collection_exists(collection):
      raise CollectionNotFoundError(
        f"Collection '{collection}' does not exist. Create it first."
      )

    return await store_document(
      self._qdrant,
      self._executor,
      self._generate_embedding,
      text,
      collection,
      metadata,
      doc_id,
      ttl_seconds,
      text_store=self._text_store,
    )

  async def store_batch(
    self,
    items: List[Dict[str, Any]],
    collection: str,
  ) -> List[str]:
    """
    Batch store multiple documents with single embedding call.

    Each item: {"text": str, "metadata": dict|None, "doc_id": str|None, "ttl_seconds": int|None}

    Bug #16: when `ingest_config.perf_logging` is True, the wall-clock of
    the whole store_batch operation (embed + upsert + prep) is accumulated
    in `self._perf["store_total_ns"]`. Subtracting `embed_ns` from it
    yields an approximation of the Qdrant upsert cost.
    """
    self._ensure_initialized()

    if not await self.collection_exists(collection):
      raise CollectionNotFoundError(
        f"Collection '{collection}' does not exist. Create it first."
      )

    perf_on = self.ingest_config.perf_logging
    n_items = len(items)
    if perf_on:
      t0 = time.perf_counter_ns()
      try:
        return await store_documents_batch(
          self._qdrant,
          self._executor,
          self._generate_embeddings_batch,
          items,
          collection,
          text_store=self._text_store,
        )
      finally:
        self._perf["store_total_ns"] += time.perf_counter_ns() - t0
        self._perf["store_calls"] += 1
        self._perf["chunks_stored"] += n_items
    return await store_documents_batch(
      self._qdrant,
      self._executor,
      self._generate_embeddings_batch,
      items,
      collection,
      text_store=self._text_store,
    )

  async def store_batch_precomputed(
    self,
    items: List[Dict[str, Any]],
    embeddings: List[List[float]],
    collection: str,
  ) -> List[str]:
    """Batch store with pre-computed embeddings (bug #16 precompute path).

    The embedding callback is never invoked — caller supplies vectors
    aligned 1:1 with `items`. Skips fastembed entirely, so the cold
    ingest cost collapses to Qdrant upsert time.
    """
    self._ensure_initialized()
    if not await self.collection_exists(collection):
      raise CollectionNotFoundError(
        f"Collection '{collection}' does not exist. Create it first."
      )
    perf_on = self.ingest_config.perf_logging
    n_items = len(items)
    # Pass a no-op callback so store_documents_batch signature stays
    # unchanged; the precomputed_embeddings kwarg short-circuits it.
    async def _noop(_texts):  # pragma: no cover - should never execute
      raise AssertionError("embedding callback invoked despite precomputed path")
    if perf_on:
      t0 = time.perf_counter_ns()
      try:
        return await store_documents_batch(
          self._qdrant,
          self._executor,
          _noop,
          items,
          collection,
          text_store=self._text_store,
          precomputed_embeddings=embeddings,
        )
      finally:
        self._perf["store_total_ns"] += time.perf_counter_ns() - t0
        self._perf["store_calls"] += 1
        self._perf["chunks_stored"] += n_items
    return await store_documents_batch(
      self._qdrant,
      self._executor,
      _noop,
      items,
      collection,
      text_store=self._text_store,
      precomputed_embeddings=embeddings,
    )

  async def search(
    self,
    query: str,
    collection: str,
    top_k: int = 5,
    threshold: float = 0.0,
    filter_metadata: Optional[Dict[str, Any]] = None,
    include_expired: bool = False,
  ) -> List[SearchResult]:
    """
    Cerca per similitud semàntica.

    Args:
      query: Text de cerca
      collection: Nom de la collection
      top_k: Màxim nombre de resultats
      threshold: Puntuació mínima (0-1)
      filter_metadata: Filtrar per metadades
      include_expired: Incloure documents expirats

    Returns:
      List[SearchResult]: Resultats ordenats per similitud
    """
    self._ensure_initialized()

    if not await self.collection_exists(collection):
      raise CollectionNotFoundError(f"Collection '{collection}' does not exist.")

    return await search_documents(
      self._qdrant,
      self._executor,
      self._generate_embedding,
      query,
      collection,
      top_k,
      threshold,
      filter_metadata,
      include_expired,
      text_store=self._text_store,
    )

  async def get(self, doc_id: str, collection: str) -> Optional[Document]:
    """Get a document by ID."""
    self._ensure_initialized()

    if not await self.collection_exists(collection):
      raise CollectionNotFoundError(f"Collection '{collection}' does not exist.")

    return await get_document(self._qdrant, self._executor, doc_id, collection, text_store=self._text_store)

  async def delete(self, doc_id: str, collection: str) -> bool:
    """Elimina un document."""
    self._ensure_initialized()

    if not await self.collection_exists(collection):
      raise CollectionNotFoundError(f"Collection '{collection}' does not exist.")

    return await delete_document(self._qdrant, self._executor, doc_id, collection, text_store=self._text_store)

  async def scroll(
    self,
    collection: str,
    limit: int = 50,
    offset: Optional[Any] = None,
  ):
    """
    Scroll all points in a collection without semantic ranking.

    Returns (points, next_offset). Direct passthrough to qdrant_client.scroll().
    Used for unbiased listing (no semantic query, no language bias).
    """
    self._ensure_initialized()

    if not await self.collection_exists(collection):
      raise CollectionNotFoundError(f"Collection '{collection}' does not exist.")

    loop = asyncio.get_running_loop()

    def _scroll():
      return self._qdrant.scroll(
        collection_name=collection,
        limit=limit,
        offset=offset,
        with_payload=True,
        with_vectors=False,
      )

    return await loop.run_in_executor(self._executor, _scroll)

  async def count(self, collection: str) -> int:
    """Compta documents en una collection."""
    self._ensure_initialized()

    if not await self.collection_exists(collection):
      raise CollectionNotFoundError(f"Collection '{collection}' does not exist.")

    return await count_documents(self._qdrant, self._executor, collection)

  async def cleanup_expired(self, collection: str) -> int:
    """Elimina documents expirats d'una collection."""
    self._ensure_initialized()

    if not await self.collection_exists(collection):
      raise CollectionNotFoundError(f"Collection '{collection}' does not exist.")

    return await cleanup_expired(self._qdrant, self._executor, collection)

  async def cleanup_all_expired(self) -> Dict[str, int]:
    """Elimina documents expirats de totes les collections."""
    self._ensure_initialized()

    collections = await self.list_collections()
    results = {}

    for col in collections:
      deleted = await self.cleanup_expired(col.name)
      if deleted > 0:
        results[col.name] = deleted

    total = sum(results.values())
    logger.info(
      "Cleanup completed: %d documents deleted from %d collections",
      total,
      len(results),
    )

    return results

  async def _generate_embedding(self, text: str) -> List[float]:
    """Genera embedding per un text."""
    loop = asyncio.get_running_loop()

    def _encode():
      import numpy as _np
      v = list(self._embedder.embed([text]))[0]
      arr = _np.array(v)
      norm = _np.linalg.norm(arr)
      if norm > 0:
        arr = arr / norm
      return arr.astype(_np.float32).tolist()

    return await loop.run_in_executor(self._executor, _encode)

  async def _generate_embeddings_batch(self, texts: List[str]) -> List[List[float]]:
    """Genera embeddings per un batch de textos en una sola crida fastembed.

    Bug #16: respecta `ingest_config.embed_batch_size` si està configurat.
    Default None preserva el comportament històric (no passar batch_size
    kwarg, FastEmbed aplica el seu default intern).

    Quan `ingest_config.perf_logging` és True, acumula durada i recomptes
    a `self._perf` — zero cost quan és False.
    """
    loop = asyncio.get_running_loop()
    embed_batch_size = self.ingest_config.embed_batch_size
    perf_on = self.ingest_config.perf_logging

    def _encode_batch():
      import numpy as _np
      results = []
      if embed_batch_size is not None:
        iterator = self._embedder.embed(texts, batch_size=embed_batch_size)
      else:
        iterator = self._embedder.embed(texts)
      for v in iterator:
        arr = _np.array(v)
        norm = _np.linalg.norm(arr)
        if norm > 0:
          arr = arr / norm
        results.append(arr.astype(_np.float32).tolist())
      return results

    if perf_on:
      t0 = time.perf_counter_ns()
      out = await loop.run_in_executor(self._executor, _encode_batch)
      self._perf["embed_ns"] += time.perf_counter_ns() - t0
      self._perf["embed_calls"] += 1
      self._perf["chunks_embedded"] += len(texts)
      return out
    return await loop.run_in_executor(self._executor, _encode_batch)

  async def warmup(self) -> None:
    """Pre-carrega pesos ONNX/tokenizer amb una crida curta (~1 token).

    Bug #16 pre-warm: la primera crida a `self._embedder.embed(...)` és cara
    perquè fastembed fa lazy-init d'ONNX Runtime sessions. Fer-ho fora del
    camí crític dona timings de workload nets.

    No-op si `ingest_config.pre_warm` és False (default). L'invocant hauria
    de respectar la flag per deixar la decisió a la config central.

    Quan perf_logging està actiu, la durada queda isolada a `warmup_ns` i
    els comptadors `embed_ns` / `chunks_embedded` NO reflecteixen aquesta
    crida (es decrementen al final) — així el benchmark veu la durada del
    workload real sense contaminació del pre-warm.
    """
    self._ensure_initialized()
    if not self.ingest_config.pre_warm:
      return
    perf_on = self.ingest_config.perf_logging
    if not perf_on:
      await self._generate_embeddings_batch(["warmup"])
      return
    # Mesurem el warmup per separat. Prenem snapshot previ, cridem, i
    # restem l'aportació del warmup als comptadors d'embed.
    embed_ns_before = self._perf["embed_ns"]
    embed_calls_before = self._perf["embed_calls"]
    chunks_before = self._perf["chunks_embedded"]
    t0 = time.perf_counter_ns()
    await self._generate_embeddings_batch(["warmup"])
    self._perf["warmup_ns"] += time.perf_counter_ns() - t0
    # Revertim l'efecte del warmup sobre els comptadors de workload.
    self._perf["embed_ns"] = embed_ns_before
    self._perf["embed_calls"] = embed_calls_before
    self._perf["chunks_embedded"] = chunks_before

  def reset_perf_counters(self) -> None:
    """Reset all perf counters to zero (bug #16 benchmark helper)."""
    for k in self._perf:
      self._perf[k] = 0

  def get_perf_snapshot(self) -> Dict[str, int]:
    """Return a snapshot of the current perf counters.

    Keys returned:
    - embed_ns: cumulative ns in _generate_embeddings_batch (workload only).
    - embed_calls: number of embed batch calls (workload only).
    - chunks_embedded: total items passed through embed (workload only).
    - store_total_ns: cumulative ns in store_batch (embed + upsert + prep).
    - store_calls: number of store_batch invocations.
    - chunks_stored: total items stored.
    - warmup_ns: cumulative ns spent in warmup() calls (isolated).
    - upsert_ns_derived: store_total_ns - embed_ns (derived, may underflow
      to 0 if rounding is unfavourable; treat as approximation).
    """
    snap = dict(self._perf)
    derived = snap["store_total_ns"] - snap["embed_ns"]
    snap["upsert_ns_derived"] = max(0, derived)
    return snap

  @staticmethod
  def _hex_to_uuid(hex_id: str) -> str:
    """Converteix hex ID a UUID format."""
    return hex_to_uuid(hex_id)

__all__ = [
  "MemoryAPI",
  "Document",
  "SearchResult",
  "CollectionInfo",
  "MemoryAPIError",
  "CollectionNotFoundError",
  "InvalidCollectionNameError",
  "DocumentNotFoundError",
  "validate_collection_name",
  "COLLECTION_NAME_PATTERN",
]
