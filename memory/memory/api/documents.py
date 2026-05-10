"""
────────────────────────────────────
Server Nexe
Author: Jordi Goy 
Location: memory/memory/api/documents.py
Description: Document CRUD operations for Memory API.

www.jgoy.net · https://server-nexe.org
────────────────────────────────────
"""

import asyncio
import hashlib
import logging
import uuid
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from typing import Any, Awaitable, Callable, Dict, List, Optional

from .models import Document, SearchResult

logger = logging.getLogger(__name__)

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
  """Convert hex ID to UUID format for Qdrant."""
  padded = hex_id.ljust(32, "0")
  return str(uuid.UUID(padded))

def _delete_points(qdrant: Any, collection: str, point_ids: List[str]) -> None:
  """Delete points from a Qdrant collection, falling back to raw ID list on error."""
  from memory.memory.engines.qdrant_types import PointIdsList
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
  qdrant: Any,
  executor: ThreadPoolExecutor,
  generate_embedding: Callable[[str], Awaitable[List[float]]],
  text: str,
  collection: str,
  metadata: Optional[Dict[str, Any]] = None,
  doc_id: Optional[str] = None,
  ttl_seconds: Optional[int] = None,
  text_store=None,
) -> str:
  """
  Store text with embedding in a collection.

  Args:
    qdrant: Qdrant client
    executor: ThreadPoolExecutor
    generate_embedding: Function to generate embeddings
    text: Textual content
    collection: Collection name
    metadata: Additional metadata
    doc_id: Custom ID (auto-generated if None)
    ttl_seconds: Time to live in seconds (None = permanent)

  Returns:
    str: ID of the created document
  """
  if doc_id is None:
    content_hash = hashlib.sha256(text.encode("utf-8")).hexdigest()
    doc_id = content_hash[:16]

  try:
    embedding = await asyncio.wait_for(generate_embedding(text), timeout=30.0)
  except asyncio.TimeoutError:
    raise RuntimeError(f"Embedding generation timed out for text (length={len(text)})")

  now = datetime.now(timezone.utc)
  expires_at = None
  if ttl_seconds is not None:
    expires_at = now + timedelta(seconds=ttl_seconds)

  created_at_iso = now.isoformat()
  expires_at_iso = expires_at.isoformat() if expires_at else None

  loop = asyncio.get_running_loop()

  if text_store:
    # Text goes to SQLite, Qdrant only gets vectors + IDs
    text_store.put(
      doc_id=doc_id, collection=collection, text=text,
      metadata=metadata,
      created_at=created_at_iso, expires_at=expires_at_iso,
    )
    qdrant_payload = {
      "original_id": doc_id,
      "created_at": created_at_iso,
      "expires_at": expires_at_iso,
      # No text in Qdrant payload
    }
  else:
    # Legacy mode: text in Qdrant payload (backwards compatible)
    qdrant_payload = {
      "original_id": doc_id,
      "text": text,
      "created_at": created_at_iso,
      "expires_at": expires_at_iso,
      **(metadata or {}),
    }

  def _store():
    """Upsert a single document point into the Qdrant collection."""
    from memory.memory.engines.qdrant_types import PointStruct
    uuid_id = hex_to_uuid(doc_id)
    point = PointStruct(
      id=uuid_id,
      vector=embedding,
      payload=qdrant_payload,
    )
    qdrant.upsert(collection_name=collection, points=[point])
    logger.debug("Stored document %s in collection %s (ttl=%s)", doc_id, collection, ttl_seconds)

  await loop.run_in_executor(executor, _store)

  ops, _ = _get_metrics()
  if ops:
    ops.labels(operation="store").inc()

  return doc_id


async def store_documents_batch(
  qdrant: Any,
  executor: ThreadPoolExecutor,
  generate_embeddings_batch: Callable[[List[str]], Awaitable[List[List[float]]]],
  items: List[Dict[str, Any]],
  collection: str,
  text_store=None,
  *,
  precomputed_embeddings: Optional[List[List[float]]] = None,
) -> List[str]:
  """
  Batch store: generate all embeddings at once, then upsert in one call.

  Each item in items: {"text": str, "metadata": dict|None, "doc_id": str|None, "ttl_seconds": int|None}

  Bug #16: if `precomputed_embeddings` is provided (one vector per item,
  same order), the `generate_embeddings_batch` callback is NOT invoked.
  This is what the pre-computed KB path uses to bypass fastembed at
  install time.
  """
  if not items:
    return []

  texts = [item["text"] for item in items]
  if precomputed_embeddings is not None:
    if len(precomputed_embeddings) != len(items):
      raise ValueError(
        f"precomputed_embeddings length {len(precomputed_embeddings)} "
        f"does not match items length {len(items)}"
      )
    embeddings = precomputed_embeddings
  else:
    embeddings = await generate_embeddings_batch(texts)

  now = datetime.now(timezone.utc)
  created_at_iso = now.isoformat()
  doc_ids = []
  points_data = []

  for item, embedding in zip(items, embeddings):
    text = item["text"]
    metadata = item.get("metadata")
    doc_id = item.get("doc_id")
    ttl_seconds = item.get("ttl_seconds")

    if doc_id is None:
      content_hash = hashlib.sha256(text.encode("utf-8")).hexdigest()
      doc_id = content_hash[:16]
    doc_ids.append(doc_id)

    expires_at_iso = None
    if ttl_seconds is not None:
      expires_at_iso = (now + timedelta(seconds=ttl_seconds)).isoformat()

    if text_store:
      text_store.put(
        doc_id=doc_id, collection=collection, text=text,
        metadata=metadata,
        created_at=created_at_iso, expires_at=expires_at_iso,
      )
      payload = {"original_id": doc_id, "created_at": created_at_iso, "expires_at": expires_at_iso}
    else:
      payload = {
        "original_id": doc_id, "text": text,
        "created_at": created_at_iso, "expires_at": expires_at_iso,
        **(metadata or {}),
      }

    points_data.append((doc_id, embedding, payload))

  loop = asyncio.get_running_loop()

  def _batch_upsert():
    """Upsert all document points into Qdrant in a single call."""
    from memory.memory.engines.qdrant_types import PointStruct
    points = [
      PointStruct(id=hex_to_uuid(did), vector=emb, payload=pl)
      for did, emb, pl in points_data
    ]
    qdrant.upsert(collection_name=collection, points=points)

  await loop.run_in_executor(executor, _batch_upsert)

  ops, _ = _get_metrics()
  if ops:
    ops.labels(operation="store_batch").inc(len(doc_ids))

  logger.debug("Batch stored %d documents in collection %s", len(doc_ids), collection)
  return doc_ids


def _qdrant_query(qdrant, collection, query_embedding, top_k, threshold, include_expired, filter_metadata):
  """Execute the qdrant search (legacy .search or modern .query_points) and return raw points."""
  from memory.memory.engines.qdrant_types import FieldCondition, Filter, MatchValue
  conditions = []
  if filter_metadata:
    for key, value in filter_metadata.items():
      conditions.append(FieldCondition(key=key, match=MatchValue(value=value)))
  qdrant_filter = Filter(must=conditions) if conditions else None
  limit = top_k * 2 if not include_expired else top_k
  score_threshold = threshold if threshold > 0 else None
  if hasattr(qdrant, "search"):
    return qdrant.search(
      collection_name=collection,
      query_vector=query_embedding,
      limit=limit,
      score_threshold=score_threshold,
      query_filter=qdrant_filter,
    )
  res = qdrant.query_points(
    collection_name=collection,
    query=query_embedding,
    limit=limit,
    score_threshold=score_threshold,
    query_filter=qdrant_filter,
  )
  return res.points


def _filter_search_results(results, collection, top_k, include_expired, now_iso):
  """Convert raw qdrant points to SearchResult list, filtering expired entries."""
  search_results = []
  for r in results:
    expires_at = r.payload.get("expires_at")
    if not include_expired and expires_at and expires_at < now_iso:
      continue
    doc_id = r.payload.get("original_id", str(r.id))
    search_results.append(
      SearchResult(
        id=doc_id,
        score=r.score,
        collection=collection,
        text=r.payload.get("text"),  # May be None if text_store is used
        metadata={
          k: v for k, v in r.payload.items() if k not in ("text", "original_id")
        },
      )
    )
    if len(search_results) >= top_k:
      break
  return search_results


async def search_documents(
  qdrant: Any,
  executor: ThreadPoolExecutor,
  generate_embedding: Callable[[str], Awaitable[List[float]]],
  query: str,
  collection: str,
  top_k: int = 5,
  threshold: float = 0.0,
  filter_metadata: Optional[Dict[str, Any]] = None,
  include_expired: bool = False,
  text_store=None,
) -> List[SearchResult]:
  """
  Search by semantic similarity.

  Args:
    qdrant: Qdrant client
    executor: ThreadPoolExecutor
    generate_embedding: Function to generate embeddings
    query: Search text
    collection: Collection name
    top_k: Maximum number of results
    threshold: Minimum score (0-1)
    filter_metadata: Filter by metadata
    include_expired: Include expired documents

  Returns:
    List[SearchResult]: Results sorted by similarity
  """
  query_embedding = await generate_embedding(query)
  loop = asyncio.get_running_loop()
  now_iso = datetime.now(timezone.utc).isoformat()

  def _search():
    """Execute Qdrant similarity search and filter expired results."""
    raw = _qdrant_query(qdrant, collection, query_embedding, top_k, threshold, include_expired, filter_metadata)
    return _filter_search_results(raw, collection, top_k, include_expired, now_iso)

  result = await loop.run_in_executor(executor, _search)

  # Fill text from TextStore if available and text is missing from payload
  if text_store and result:
    ids_needing_text = [r.id for r in result if not r.text]
    if ids_needing_text:
      texts = text_store.get_many(ids_needing_text, collection)
      for sr in result:
        if not sr.text and sr.id in texts:
          sr.text = texts[sr.id]["text"]

  ops, _ = _get_metrics()
  if ops:
    ops.labels(operation="recall").inc()

  return result

async def get_document(
  qdrant: Any,
  executor: ThreadPoolExecutor,
  doc_id: str,
  collection: str,
  text_store=None,
) -> Optional[Document]:
  """Get a document by ID."""
  loop = asyncio.get_running_loop()

  def _get():
    """Retrieve a single document from Qdrant by its hex ID."""
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

      # Get text from TextStore if available, fallback to payload
      text = payload.get("text", "")
      doc_metadata = {
        k: v
        for k, v in payload.items()
        if k not in ("text", "original_id", "created_at", "expires_at")
      }

      if text_store and not text:
        stored = text_store.get(doc_id, collection)
        if stored:
          text = stored["text"]
          doc_metadata = stored.get("metadata", doc_metadata)

      return Document(
        id=payload.get("original_id", doc_id),
        text=text,
        collection=collection,
        metadata=doc_metadata,
        created_at=created_at,
        expires_at=expires_at,
      )

    except Exception as e:
      logger.warning("Failed to get document %s: %s", doc_id, e)
      return None

  return await loop.run_in_executor(executor, _get)

async def delete_document(
  qdrant: Any,
  executor: ThreadPoolExecutor,
  doc_id: str,
  collection: str,
  text_store=None,
) -> bool:
  """Delete a document."""
  loop = asyncio.get_running_loop()

  def _delete():
    """Delete a single document from Qdrant by its hex ID."""
    uuid_id = hex_to_uuid(doc_id)
    try:
      _delete_points(qdrant, collection, [uuid_id])
      logger.debug("Deleted document %s from collection %s", doc_id, collection)
      return True

    except Exception as e:
      logger.warning("Failed to delete document %s: %s", doc_id, e)
      return False

  result = await loop.run_in_executor(executor, _delete)

  if result:
    if text_store:
      text_store.delete(doc_id, collection)
    ops, _ = _get_metrics()
    if ops:
      ops.labels(operation="delete").inc()

  return result

async def count_documents(
  qdrant: Any,
  executor: ThreadPoolExecutor,
  collection: str,
) -> int:
  """Count documents in a collection."""
  loop = asyncio.get_running_loop()

  def _count():
    """Return the point count for a Qdrant collection."""
    info = qdrant.get_collection(collection)
    return info.points_count

  return await loop.run_in_executor(executor, _count)

async def cleanup_expired(
  qdrant: Any,
  executor: ThreadPoolExecutor,
  collection: str,
) -> int:
  """Delete expired documents from a collection."""
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
        logger.debug("Deleted %d expired documents from %s", len(expired_ids), collection)

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
