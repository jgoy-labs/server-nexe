"""
────────────────────────────────────
Server Nexe
Version: 0.8
Author: Jordi Goy 
Location: memory/memory/api/collections.py
Description: Operacions de gestió de collections per Memory API.

www.jgoy.net
────────────────────────────────────
"""

import asyncio
import logging
from concurrent.futures import ThreadPoolExecutor
from typing import List

from qdrant_client import QdrantClient
from qdrant_client.models import Distance, VectorParams

from .models import CollectionInfo, validate_collection_name

logger = logging.getLogger(__name__)

async def create_collection(
  qdrant: QdrantClient,
  executor: ThreadPoolExecutor,
  name: str,
  vector_size: int = 384,
  distance: str = "cosine",
) -> bool:
  """
  Crea una nova collection.

  Args:
    qdrant: Client Qdrant
    executor: ThreadPoolExecutor per operacions sync
    name: Nom de la collection seguint naming convention {modul}_{tipus}
    vector_size: Dimensió dels vectors (default: 384)
    distance: Mètrica de distància ("cosine", "euclid", "dot")

  Returns:
    bool: True si creada, False si ja existeix
  """
  validate_collection_name(name)
  loop = asyncio.get_running_loop()

  def _create():
    collections = qdrant.get_collections().collections
    if name in [c.name for c in collections]:
      logger.info("Collection '%s' already exists", name)
      return False

    distance_map = {
      "cosine": Distance.COSINE,
      "euclid": Distance.EUCLID,
      "dot": Distance.DOT,
    }

    qdrant.create_collection(
      collection_name=name,
      vectors_config=VectorParams(
        size=vector_size, distance=distance_map.get(distance, Distance.COSINE)
      ),
    )
    logger.info("Created collection '%s' (size=%d, distance=%s)", name, vector_size, distance)
    return True

  return await loop.run_in_executor(executor, _create)

async def delete_collection(
  qdrant: QdrantClient,
  executor: ThreadPoolExecutor,
  name: str,
) -> bool:
  """Elimina una collection."""
  loop = asyncio.get_running_loop()

  def _delete():
    collections = qdrant.get_collections().collections
    if name not in [c.name for c in collections]:
      logger.warning("Collection '%s' does not exist", name)
      return False

    qdrant.delete_collection(collection_name=name)
    logger.info("Deleted collection '%s'", name)
    return True

  return await loop.run_in_executor(executor, _delete)

async def list_collections(
  qdrant: QdrantClient,
  executor: ThreadPoolExecutor,
) -> List[CollectionInfo]:
  """Llista totes les collections."""
  loop = asyncio.get_running_loop()

  def _list():
    collections = qdrant.get_collections().collections
    result = []

    for col in collections:
      info = qdrant.get_collection(col.name)
      result.append(
        CollectionInfo(
          name=col.name,
          vector_size=info.config.params.vectors.size,
          points_count=info.points_count,
        )
      )

    return result

  return await loop.run_in_executor(executor, _list)

async def collection_exists(
  qdrant: QdrantClient,
  executor: ThreadPoolExecutor,
  name: str,
) -> bool:
  """Comprova si una collection existeix."""
  loop = asyncio.get_running_loop()

  def _exists():
    collections = qdrant.get_collections().collections
    return name in [c.name for c in collections]

  return await loop.run_in_executor(executor, _exists)

__all__ = [
  "create_collection",
  "delete_collection",
  "list_collections",
  "collection_exists",
]