"""
────────────────────────────────────
Server Nexe
Version: 0.8
Author: Jordi Goy 
Location: memory/memory/api/documents.py
Description: Operacions CRUD de documents per Memory API.

www.jgoy.net
────────────────────────────────────
"""

import asyncio
import hashlib
import logging
import uuid
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from typing import Any, Callable, Dict, List, Optional

from qdrant_client import QdrantClient
from qdrant_client.models import FieldCondition, Filter, MatchValue, PointStruct, PointIdsList

from .models import Document, SearchResult
from personality.i18n.resolve import t_modular

logger = logging.getLogger(__name__)

def _t(key: str, fallback: str, **kwargs) -> str:
  return t_modular(f"memory.documents.{key}", fallback, **kwargs)

_metrics_imported = False
_MEMORY_OPERATIONS = None
_MEMORY_STORE_SIZE = None

def _get_metrics():
  """Lazy import Prometheus metrics."""
  global _metrics_imported, _MEMORY_OPERATIONS, _MEMORY_STORE_SIZE
  if not _metrics_imported:
    try:
      from core.metrics.registry import MEMORY_OPERATIONS, MEMORY_STORE_SIZE
      _MEMORY_OPERATIONS = MEMORY_OPERATIONS
      _MEMORY_STORE_SIZE = MEMORY_STORE_SIZE
      _metrics_imported = True
    except ImportError:
      _metrics_imported = True
  return _MEMORY_OPERATIONS, _MEMORY_STORE_SIZE

def hex_to_uuid(hex_id: str) -> str:
  """Converteix hex ID a UUID format per Qdrant."""
  padded = hex_id.ljust(32, "0")
  return str(uuid.UUID(padded))

def _delete_points(qdrant: QdrantClient, collection: str, point_ids: List[str]) -> None:
  try:
    qdrant.delete(
      collection_name=collection,
      points_selector=PointIdsList(points=point_ids),
    )
  except Exception:
    qdrant.delete(
      collection_name=collection,
      points_selector=point_ids,
    )

async def store_document(
  qdrant: QdrantClient,
  executor: ThreadPoolExecutor,
  generate_embedding: Callable[[str], List[float]],
  text: str,
  collection: str,
  metadata: Optional[Dict[str, Any]] = None,
  doc_id: Optional[str] = None,
  ttl_seconds: Optional[int] = None,
) -> str:
  """
  Emmagatzema text amb embedding a una collection.

  Args:
    qdrant: Client Qdrant
    executor: ThreadPoolExecutor
    generate_embedding: Funció per generar embeddings
    text: Contingut textual
    collection: Nom de la collection
    metadata: Metadades addicionals
    doc_id: ID personalitzat (auto-generat si None)
    ttl_seconds: Temps de vida en segons (None = permanent)

  Returns:
    str: ID del document creat
  """
  if doc_id is None:
    content_hash = hashlib.sha256(text.encode("utf-8")).hexdigest()
    doc_id = content_hash[:16]

  embedding = await generate_embedding(text)

  now = datetime.now(timezone.utc)
  expires_at = None
  if ttl_seconds is not None:
    expires_at = now + timedelta(seconds=ttl_seconds)

  final_metadata = {
    "text": text,
    "created_at": now.isoformat(),
    "expires_at": expires_at.isoformat() if expires_at else None,
    **(metadata or {}),
  }

  loop = asyncio.get_running_loop()

  def _store():
    uuid_id = hex_to_uuid(doc_id)
    point = PointStruct(
      id=uuid_id,
      vector=embedding,
      payload={"original_id": doc_id, **final_metadata},
    )
    qdrant.upsert(collection_name=collection, points=[point])
    logger.debug(
      _t(
        "stored",
        "Stored document {doc_id} in collection {collection} (ttl={ttl})",
        doc_id=doc_id,
        collection=collection,
        ttl=ttl_seconds,
      )
    )

  await loop.run_in_executor(executor, _store)

  ops, _ = _get_metrics()
  if ops:
    ops.labels(operation="store").inc()

  return doc_id

async def search_documents(
  qdrant: QdrantClient,
  executor: ThreadPoolExecutor,
  generate_embedding: Callable[[str], List[float]],
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
    qdrant: Client Qdrant
    executor: ThreadPoolExecutor
    generate_embedding: Funció per generar embeddings
    query: Text de cerca
    collection: Nom de la collection
    top_k: Màxim nombre de resultats
    threshold: Puntuació mínima (0-1)
    filter_metadata: Filtrar per metadades
    include_expired: Incloure documents expirats

  Returns:
    List[SearchResult]: Resultats ordenats per similitud
  """
  query_embedding = await generate_embedding(query)
  loop = asyncio.get_running_loop()
  now_iso = datetime.now(timezone.utc).isoformat()

  def _search():
    conditions = []
    if filter_metadata:
      for key, value in filter_metadata.items():
        conditions.append(FieldCondition(key=key, match=MatchValue(value=value)))

    qdrant_filter = Filter(must=conditions) if conditions else None

    if hasattr(qdrant, "search"):
      results = qdrant.search(
        collection_name=collection,
        query_vector=query_embedding,
        limit=top_k * 2 if not include_expired else top_k,
        score_threshold=threshold if threshold > 0 else None,
        query_filter=qdrant_filter,
      )
    else:
      # Fallback for modern qdrant-client versions
      res = qdrant.query_points(
        collection_name=collection,
        query=query_embedding,
        limit=top_k * 2 if not include_expired else top_k,
        score_threshold=threshold if threshold > 0 else None,
        query_filter=qdrant_filter,
      )
      results = res.points

    search_results = []
    for r in results:
      expires_at = r.payload.get("expires_at")
      if not include_expired and expires_at:
        if expires_at < now_iso:
          continue

      search_results.append(
        SearchResult(
          id=r.payload.get("original_id", str(r.id)),
          score=r.score,
          collection=collection,
          text=r.payload.get("text"),
          metadata={
            k: v for k, v in r.payload.items() if k not in ("text", "original_id")
          },
        )
      )

      if len(search_results) >= top_k:
        break

    return search_results

  result = await loop.run_in_executor(executor, _search)

  ops, _ = _get_metrics()
  if ops:
    ops.labels(operation="recall").inc()

  return result

async def get_document(
  qdrant: QdrantClient,
  executor: ThreadPoolExecutor,
  doc_id: str,
  collection: str,
) -> Optional[Document]:
  """Obté un document per ID."""
  loop = asyncio.get_running_loop()

  def _get():
    uuid_id = hex_to_uuid(doc_id)
    try:
      results = qdrant.retrieve(
        collection_name=collection, ids=[uuid_id], with_payload=True
      )

      if not results:
        return None

      point = results[0]
      payload = point.payload

      created_at = None
      if payload.get("created_at"):
        created_at = datetime.fromisoformat(payload["created_at"])

      expires_at = None
      if payload.get("expires_at"):
        expires_at = datetime.fromisoformat(payload["expires_at"])

      return Document(
        id=payload.get("original_id", doc_id),
        text=payload.get("text", ""),
        collection=collection,
        metadata={
          k: v
          for k, v in payload.items()
          if k not in ("text", "original_id", "created_at", "expires_at")
        },
        created_at=created_at,
        expires_at=expires_at,
      )

    except Exception as e:
      logger.warning(
        _t(
          "get_failed",
          "Failed to get document {doc_id}: {error}",
          doc_id=doc_id,
          error=str(e),
        )
      )
      return None

  return await loop.run_in_executor(executor, _get)

async def delete_document(
  qdrant: QdrantClient,
  executor: ThreadPoolExecutor,
  doc_id: str,
  collection: str,
) -> bool:
  """Elimina un document."""
  loop = asyncio.get_running_loop()

  def _delete():
    uuid_id = hex_to_uuid(doc_id)
    try:
      _delete_points(qdrant, collection, [uuid_id])
      logger.debug(
        _t(
          "deleted",
          "Deleted document {doc_id} from collection {collection}",
          doc_id=doc_id,
          collection=collection,
        )
      )
      return True

    except Exception as e:
      logger.warning(
        _t(
          "delete_failed",
          "Failed to delete document {doc_id}: {error}",
          doc_id=doc_id,
          error=str(e),
        )
      )
      return False

  result = await loop.run_in_executor(executor, _delete)

  if result:
    ops, _ = _get_metrics()
    if ops:
      ops.labels(operation="delete").inc()

  return result

async def count_documents(
  qdrant: QdrantClient,
  executor: ThreadPoolExecutor,
  collection: str,
) -> int:
  """Compta documents en una collection."""
  loop = asyncio.get_running_loop()

  def _count():
    info = qdrant.get_collection(collection)
    return info.points_count

  return await loop.run_in_executor(executor, _count)

async def cleanup_expired(
  qdrant: QdrantClient,
  executor: ThreadPoolExecutor,
  collection: str,
) -> int:
  """Elimina documents expirats d'una collection."""
  loop = asyncio.get_running_loop()
  now_iso = datetime.now(timezone.utc).isoformat()

  def _cleanup():
    deleted_count = 0
    offset = None

    while True:
      records, offset = qdrant.scroll(
        collection_name=collection,
        limit=100,
        offset=offset,
        with_payload=True,
      )

      if not records:
        break

      expired_ids = []
      for record in records:
        expires_at = record.payload.get("expires_at")
        if expires_at and expires_at < now_iso:
          expired_ids.append(record.id)

      if expired_ids:
        _delete_points(qdrant, collection, expired_ids)
        deleted_count += len(expired_ids)
      logger.debug(
        _t(
          "expired_deleted",
          "Deleted {count} expired documents from {collection}",
          count=len(expired_ids),
          collection=collection,
        )
      )

      if offset is None:
        break

    return deleted_count

  return await loop.run_in_executor(executor, _cleanup)

__all__ = [
  "store_document",
  "search_documents",
  "get_document",
  "delete_document",
  "count_documents",
  "cleanup_expired",
  "hex_to_uuid",
]
