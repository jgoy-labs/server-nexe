"""
────────────────────────────────────
Server Nexe
Author: Jordi Goy
Location: memory/memory/storage/vector_index.py
Description: Qdrant embedded vector index wrapper for memory_index collection.

www.jgoy.net · https://server-nexe.org
────────────────────────────────────
"""

import logging
from pathlib import Path
from typing import Any, Dict, List, Optional

from memory.embeddings.constants import DEFAULT_VECTOR_SIZE
from memory.embeddings.adapters import QdrantAdapter

logger = logging.getLogger(__name__)

COLLECTION_NAME = "memory_index"
VECTOR_SIZE = DEFAULT_VECTOR_SIZE


class VectorIndex:
    """
    Wrapper over Qdrant embedded for the memory vector index.

    Collection: memory_index
    Model: paraphrase-multilingual-mpnet-base-v2 (768 dims)

    The vector store is a REBUILDABLE INDEX — SQLite is the source of truth.
    """

    def __init__(self, qdrant_path: str = "storage/vectors"):
        self._qdrant_path = Path(qdrant_path)
        self._client = None
        self._available = False
        self._init_client()

    def _init_client(self):
        """Initialize the QdrantAdapter embedded client."""
        try:
            self._qdrant_path.mkdir(parents=True, exist_ok=True)
            self._client = QdrantAdapter.from_pool(
                collection_name=COLLECTION_NAME,
                path=str(self._qdrant_path),
            )

            # Ensure collection exists via helper (oculta VectorParams/Distance)
            created = self._client.ensure_collection(
                collection_name=COLLECTION_NAME,
                vector_size=VECTOR_SIZE,
                distance="cosine",
            )
            if created:
                logger.info(
                    "Created collection '%s' at %s",
                    COLLECTION_NAME, self._qdrant_path,
                )

            self._available = True
            logger.info("VectorIndex initialized at %s", self._qdrant_path)
        except Exception as e:
            logger.warning("VectorIndex init failed: %s", e)
            self._available = False

    @property
    def available(self) -> bool:
        """Whether the vector index is operational."""
        return self._available

    def index(
        self,
        entries: List[Dict[str, Any]],
        embeddings: List[List[float]],
    ) -> int:
        """
        Index entries with their embeddings.

        Args:
            entries: List of dicts with keys: id, user_id, namespace,
                     memory_type, state, importance, trust_level, created_at
            embeddings: Corresponding embedding vectors

        Returns:
            Number of entries indexed
        """
        if not self._available or not entries:
            return 0

        points_data = [
            {
                "id": entry["id"],
                "vector": embedding,
                "payload": {
                    "rdbms_id": entry.get("rdbms_id", entry["id"]),
                    "user_id": entry["user_id"],
                    "namespace": entry.get("namespace", "default"),
                    "memory_type": entry.get("memory_type", "fact"),
                    "state": entry.get("state", "active"),
                    "importance": entry.get("importance", 0.5),
                    "trust_level": entry.get("trust_level", "untrusted"),
                    "created_at": entry.get("created_at"),
                },
            }
            for entry, embedding in zip(entries, embeddings)
        ]
        # upsert_points oculta PointStruct al caller
        self._client.upsert_points(
            collection_name=COLLECTION_NAME,
            points_data=points_data,
        )
        return len(points_data)

    def search(
        self,
        embedding: List[float],
        user_id: str,
        threshold: float = 0.40,
        limit: int = 20,
        namespace: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        """
        Search the vector index.

        Args:
            embedding: Query embedding vector
            user_id: Filter by user
            threshold: Minimum similarity score
            limit: Maximum results
            namespace: Optional namespace filter

        Returns:
            List of results with id, score, and payload
        """
        if not self._available:
            return []

        # search_with_filter oculta Filter/FieldCondition/MatchValue al caller
        filter_conditions = [
            {"key": "user_id", "value": user_id},
            {"key": "state", "value": "active"},
        ]
        if namespace:
            filter_conditions.append({"key": "namespace", "value": namespace})

        results = self._client.search_with_filter(
            collection_name=COLLECTION_NAME,
            query_vector=embedding,
            filter_conditions=filter_conditions,
            limit=limit,
            score_threshold=threshold,
        )

        return [
            {
                "id": str(r.id),
                "score": r.score,
                "payload": r.payload or {},
            }
            for r in results
        ]

    def delete(self, ids: List[str]) -> int:
        """Delete entries from the index."""
        if not self._available or not ids:
            return 0

        # delete_by_ids oculta PointIdsList al caller
        return self._client.delete_by_ids(
            collection_name=COLLECTION_NAME,
            ids=ids,
        )

    def count(self) -> int:
        """Count total entries in the index."""
        if not self._available:
            return 0
        info = self._client.get_collection(COLLECTION_NAME)
        return info.points_count

    def close(self):
        """Close the QdrantAdapter client."""
        if self._client:
            try:
                self._client.close()
            except Exception as e:
                logger.debug("VectorIndex close failed: %s", e)
            self._client = None
            self._available = False


__all__ = ["VectorIndex", "COLLECTION_NAME", "VECTOR_SIZE"]
