"""
────────────────────────────────────
Server Nexe
Version: 0.8
Author: Jordi Goy 
Location: memory/memory/api/__init__.py
Description: Memory API Façade - API genèrica per mòduls externs.

www.jgoy.net
────────────────────────────────────
"""

import asyncio
import logging
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any, Dict, List, Optional

from personality.i18n import get_i18n
from personality.i18n.resolve import t_modular

from qdrant_client import QdrantClient

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

def _t(key: str, fallback: str, **kwargs) -> str:
  return t_modular(f"memory.api.{key}", fallback, **kwargs)

def _t_col(key: str, fallback: str, **kwargs) -> str:
  return t_modular(f"memory.collections.{key}", fallback, **kwargs)

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

  DEFAULT_QDRANT_URL = "http://localhost:6333"
  DEFAULT_VECTOR_SIZE = 768

  def __init__(
    self,
    qdrant_url: Optional[str] = None,
    qdrant_path: Optional[Path] = None,
    embedding_model: str = "all-MiniLM-L6-v2",
  ):
    """
    Inicialitza Memory API.

    Args:
      qdrant_url: URL del servidor Qdrant (default: http://localhost:6333)
      qdrant_path: Path local per mode fitxer/test (prioritat sobre qdrant_url)
      embedding_model: Model d'embeddings (default: all-MiniLM-L6-v2)
    """
    self.qdrant_url = qdrant_url or self.DEFAULT_QDRANT_URL
    self.qdrant_path = qdrant_path
    self.embedding_model = embedding_model
    self.vector_size = self.DEFAULT_VECTOR_SIZE

    self._qdrant: Optional[QdrantClient] = None
    self._embedder = None
    self._executor = ThreadPoolExecutor(max_workers=4)
    self._initialized = False

    if qdrant_path:
      logger.info(
        _t(
          "created_with_path",
          "MemoryAPI created (qdrant_path={path}, model={model})",
          path=self.qdrant_path,
          model=self.embedding_model,
        )
      )
    else:
      logger.info(
        _t(
          "created_with_url",
          "MemoryAPI created (qdrant_url={url}, model={model})",
          url=self.qdrant_url,
          model=self.embedding_model,
        )
      )

  async def initialize(self) -> bool:
    """Inicialitza connexions i models."""
    if self._initialized:
      logger.warning(_t("already_initialized", "MemoryAPI already initialized"))
      return True

    try:
      # Usar mode local si qdrant_path està definit, sinó connectar a URL
      if self.qdrant_path:
        self._qdrant = QdrantClient(path=str(self.qdrant_path))
        logger.info(
          _t(
            "initialized_path",
            "MemoryAPI initialized (path={path})",
            path=self.qdrant_path,
          )
        )
      else:
        self._qdrant = QdrantClient(url=self.qdrant_url, prefer_grpc=False)
        logger.info(
          _t(
            "initialized_url",
            "MemoryAPI initialized (url={url})",
            url=self.qdrant_url,
          )
        )

      await self._init_embedder()
      self._initialized = True
      return True

    except Exception as e:
      logger.error(
        _t(
          "initialization_failed",
          "MemoryAPI initialization failed: {error}",
          error=str(e),
        )
      )
      raise

  async def _init_embedder(self):
    """Inicialitza el model d'embeddings."""
    loop = asyncio.get_running_loop()

    def _load_model():
      from sentence_transformers import SentenceTransformer
      return SentenceTransformer(self.embedding_model)

    self._embedder = await loop.run_in_executor(self._executor, _load_model)
    logger.info(
      _t(
        "embedder_initialized",
        "Embedder initialized: {model}",
        model=self.embedding_model,
      )
    )

  def _ensure_initialized(self):
    """Verificar que l'API està inicialitzada."""
    if not self._initialized:
      i18n = get_i18n()
      raise RuntimeError(
        i18n.t(
          "memory.api.not_initialized",
          "MemoryAPI not initialized. Call initialize() first."
        )
      )

  async def close(self):
    """Tanca connexions i allibera recursos."""
    if self._qdrant:
      try:
        self._qdrant.close()
      except Exception as e:
        logger.debug(
          _t(
            "close_failed",
            "MemoryAPI close failed: {error}",
            error=str(e),
          )
        )
      finally:
        if hasattr(self._qdrant, "_client"):
          delattr(self._qdrant, "_client")

    if self._executor:
      self._executor.shutdown(wait=True)

    self._qdrant = None
    self._embedder = None
    self._initialized = False
    logger.info(_t("closed", "MemoryAPI closed"))

  async def __aenter__(self):
    """Context manager entry."""
    await self.initialize()
    return self

  async def __aexit__(self, exc_type, exc_val, exc_tb):
    """Context manager exit."""
    await self.close()

  async def create_collection(
    self, name: str, vector_size: int = 384, distance: str = "cosine"
  ) -> bool:
    """
    Crea una nova collection.

    Args:
      name: Nom seguint naming convention {modul}_{tipus}
      vector_size: Dimensió dels vectors (default: 384)
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
        _t_col(
          "not_found_create",
          "Collection '{name}' does not exist. Create it first.",
          name=collection
        )
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
      raise CollectionNotFoundError(
        _t_col(
          "not_found",
          "Collection '{name}' does not exist",
          name=collection
        )
      )

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
    )

  async def get(self, doc_id: str, collection: str) -> Optional[Document]:
    """Obté un document per ID."""
    self._ensure_initialized()

    if not await self.collection_exists(collection):
      raise CollectionNotFoundError(
        _t_col(
          "not_found",
          "Collection '{name}' does not exist",
          name=collection
        )
      )

    return await get_document(self._qdrant, self._executor, doc_id, collection)

  async def delete(self, doc_id: str, collection: str) -> bool:
    """Elimina un document."""
    self._ensure_initialized()

    if not await self.collection_exists(collection):
      raise CollectionNotFoundError(
        _t_col(
          "not_found",
          "Collection '{name}' does not exist",
          name=collection
        )
      )

    return await delete_document(self._qdrant, self._executor, doc_id, collection)

  async def count(self, collection: str) -> int:
    """Compta documents en una collection."""
    self._ensure_initialized()

    if not await self.collection_exists(collection):
      raise CollectionNotFoundError(
        _t_col(
          "not_found",
          "Collection '{name}' does not exist",
          name=collection
        )
      )

    return await count_documents(self._qdrant, self._executor, collection)

  async def cleanup_expired(self, collection: str) -> int:
    """Elimina documents expirats d'una collection."""
    self._ensure_initialized()

    if not await self.collection_exists(collection):
      raise CollectionNotFoundError(
        _t_col(
          "not_found",
          "Collection '{name}' does not exist",
          name=collection
        )
      )

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
    logger.info(_t(
      "logs.cleanup_completed",
      "Cleanup completed: {count} documents deleted from {collections} collections",
      count=total,
      collections=len(results)
    ))

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
