"""
────────────────────────────────────
Server Nexe
Author: Jordi Goy 
Location: memory/memory/api/__init__.py
Description: Memory API Facade - Generic API for external modules.

www.jgoy.net · https://server-nexe.org
────────────────────────────────────
"""

import asyncio
import logging
import os
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any, Dict, List, Optional

from qdrant_client import QdrantClient

from ..constants import DEFAULT_VECTOR_SIZE

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
    embedding_model: str = "paraphrase-multilingual-mpnet-base-v2",
    crypto_provider=None,
    text_store_path: Optional[Path] = None,
  ):
    """
    Inicialitza Memory API.

    Args:
      qdrant_url: URL del servidor Qdrant (default: http://localhost:6333)
      qdrant_path: Path local per mode fitxer/test (prioritat sobre qdrant_url).
                   Default: storage/vectors (embedded mode)
      embedding_model: Model d'embeddings (default: paraphrase-multilingual-mpnet-base-v2)
    """
    self.qdrant_url = qdrant_url or self.DEFAULT_QDRANT_URL
    self.qdrant_path = qdrant_path if qdrant_path is not None else self.DEFAULT_QDRANT_PATH
    self.embedding_model = embedding_model
    self.vector_size = self.DEFAULT_VECTOR_SIZE

    self._crypto = crypto_provider
    self._text_store_path = text_store_path
    self._text_store = None
    self._qdrant: Optional[QdrantClient] = None
    self._embedder = None
    self._executor = ThreadPoolExecutor(max_workers=4)
    self._initialized = False

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

    def _load_model():
      from sentence_transformers import SentenceTransformer
      try:
        return SentenceTransformer(self.embedding_model, local_files_only=True)
      except Exception:
        return SentenceTransformer(self.embedding_model)

    self._embedder = await loop.run_in_executor(self._executor, _load_model)
    import os as _os
    logger.info("SentenceTransformer initialized (PID=%s, model=%s)", _os.getpid(), self.embedding_model)

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
      return self._embedder.encode(text).tolist()

    return await loop.run_in_executor(self._executor, _encode)

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
