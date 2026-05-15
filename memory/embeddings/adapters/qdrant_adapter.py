"""
────────────────────────────────────
Server Nexe
Author: Jordi Goy
Location: memory/embeddings/adapters/qdrant_adapter.py
Description: QdrantAdapter — implementation of the VectorStore Protocol on top of QdrantClient.

Purpose:
  Indirection layer between vector store consumers and Qdrant.
  Allows replacing Qdrant with any other vector store by implementing
  the VectorStore Protocol without touching consumers.

Implemented protocol:
  memory.embeddings.core.vectorstore.VectorStore

Additional management methods (passthrough):
  Exposes the collection methods needed by existing consumers.
  This allows gradual migration without breaking the existing API.

Usage:
  >>> adapter = QdrantAdapter(collection_name="nexe_docs", path="storage/vectors")
  >>> ids = adapter.add_vectors([[0.1, 0.2]], ["text"], [{"source": "pdf"}])
  >>> hits = adapter.search(VectorSearchRequest(query_vector=[0.1, 0.2], top_k=5))

www.jgoy.net · https://server-nexe.org
────────────────────────────────────
"""

import logging
import uuid
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)


class QdrantAdapter:
    """
    Adapter between the VectorStore Protocol and QdrantClient.

    One instance = one default collection (for the Protocol).
    Passthrough methods allow multi-collection management (legacy compatible).

    Args:
        collection_name: Default collection for Protocol methods
        path: Local path (embedded mode)
        url: Qdrant server URL (server mode)
        client: Already created QdrantClient (takes priority over path/url)

    Example future backend swap (for documentation):
        class WeaviateAdapter:
            def add_vectors(self, ...): # uses weaviate-client
            def search(self, ...): # uses weaviate-client
            def delete(self, ...): # uses weaviate-client
            def health(self, ...): # uses weaviate-client
    """

    def __init__(
        self,
        collection_name: str = "default",
        path: Optional[str] = None,
        url: Optional[str] = None,
        client: Optional[Any] = None,
    ):
        self._collection_name = collection_name
        self._path = path
        self._url = url
        self._client = client

        if self._client is None:
            self._client = self._create_client()

    def _require_client(self) -> Any:
        """Returns self._client or raises RuntimeError if the adapter is closed.

        Used at the 23 callsites to give a semantically correct error
        (RuntimeError "closed") when someone reuses the adapter after `close()`
        instead of propagating AttributeError.
        """
        if self._client is None:
            raise RuntimeError("QdrantAdapter is closed")
        return self._client

    def _create_client(self) -> Any:
        """Creates the internal QdrantClient via the shared pool."""
        from core.qdrant_pool import get_qdrant_client
        if self._path:
            return get_qdrant_client(path=self._path)
        if self._url:
            return get_qdrant_client(url=self._url)
        return get_qdrant_client()

    @classmethod
    def from_pool(cls, collection_name: str, path: Optional[str] = None, url: Optional[str] = None) -> "QdrantAdapter":
        """Creates adapter using the shared pool (core.qdrant_pool)."""
        from core.qdrant_pool import get_qdrant_client
        if path:
            client = get_qdrant_client(path=path)
        else:
            client = get_qdrant_client(url=url)
        return cls(collection_name=collection_name, client=client)

    # ── VectorStore Protocol ──────────────────────────────────────────────────

    def add_vectors(
        self,
        vectors: List[List[float]],
        texts: List[str],
        metadatas: List[Dict[str, Any]],
    ) -> List[str]:
        """
        Add vectors to the store.

        Implements VectorStore.add_vectors().
        Generates UUID v4 IDs for each vector.

        Returns:
            List of generated IDs
        """
        from qdrant_client.models import PointStruct

        if len(vectors) != len(texts) or len(vectors) != len(metadatas):
            raise ValueError("vectors, texts i metadatas han de tenir la mateixa longitud")

        ids = [str(uuid.uuid4()) for _ in vectors]
        points = [
            PointStruct(
                id=ids[i],
                vector=vectors[i],
                payload={**metadatas[i], "text": texts[i]},
            )
            for i in range(len(vectors))
        ]

        self._require_client().upsert(
            collection_name=self._collection_name,
            points=points,
        )
        logger.debug("add_vectors: %d vectors afegits a '%s'", len(ids), self._collection_name)
        return ids

    def search(self, request: Any) -> List[Any]:
        """
        Semantic search in the default collection.

        Implements VectorStore.search() — accepts VectorSearchRequest.

        Returns:
            List of VectorSearchHit
        """
        from memory.embeddings.core.vectorstore import VectorSearchHit

        try:
            results = self._require_client().search(
                collection_name=self._collection_name,
                query_vector=request.query_vector,
                limit=request.top_k,
                score_threshold=None,
            )
        except Exception:
            # Fallback for modern qdrant-client (1.11+)
            res = self._require_client().query_points(
                collection_name=self._collection_name,
                query=request.query_vector,
                limit=request.top_k,
            )
            results = res.points

        return [
            VectorSearchHit(
                id=str(r.id),
                score=min(1.0, max(0.0, r.score)),
                text=(r.payload or {}).get("text", ""),
                metadata={k: v for k, v in (r.payload or {}).items() if k != "text"},
            )
            for r in results
        ]

    def delete(self, ids: List[str]) -> int:
        """
        Delete vectors by IDs from the default collection.

        Implements VectorStore.delete().

        Returns:
            Number of deleted vectors
        """
        from qdrant_client.models import PointIdsList

        if not ids:
            return 0

        self._require_client().delete(
            collection_name=self._collection_name,
            points_selector=PointIdsList(points=ids),
        )
        logger.debug("delete: %d vectors eliminats de '%s'", len(ids), self._collection_name)
        return len(ids)

    def health(self) -> Dict[str, Any]:
        """
        Health status of the vector store.

        Implements VectorStore.health().

        Returns:
            Dict with status, num_vectors, collection
        """
        try:
            info = self._require_client().get_collection(self._collection_name)
            return {
                "status": "healthy",
                "num_vectors": info.points_count or 0,
                "collection": self._collection_name,
                "backend": "qdrant_embedded",
            }
        except Exception as e:
            return {
                "status": "unhealthy",
                "error": str(e),
                "collection": self._collection_name,
                "backend": "qdrant_embedded",
            }

    # ── Collection management passthrough (legacy compat) ─────────────────────
    # Allow documents.py, collections.py and persistence.py to keep
    # calling the same methods without logic changes.
    # When migrating to another backend, these methods must be implemented.

    def get_collections(self) -> Any:
        """List of all collections."""
        return self._require_client().get_collections()

    def create_collection(self, collection_name: str, vectors_config: Any) -> None:
        """Creates a new collection."""
        self._require_client().create_collection(
            collection_name=collection_name,
            vectors_config=vectors_config,
        )

    def delete_collection(self, collection_name: str) -> None:
        """Deletes a collection."""
        self._require_client().delete_collection(collection_name=collection_name)

    def get_collection(self, collection_name: str) -> Any:
        """Information about a collection."""
        return self._require_client().get_collection(collection_name)

    def upsert(self, collection_name: str, points: List[Any]) -> None:
        """Add or update points in a collection."""
        self._require_client().upsert(collection_name=collection_name, points=points)

    def client_search(
        self,
        collection_name: str,
        query_vector: List[float],
        query_filter: Any = None,
        limit: int = 10,
        score_threshold: Optional[float] = None,
    ) -> List[Any]:
        """Search in a specific collection (legacy API)."""
        try:
            return self._require_client().search(
                collection_name=collection_name,
                query_vector=query_vector,
                query_filter=query_filter,
                limit=limit,
                score_threshold=score_threshold,
            )
        except Exception:
            res = self._require_client().query_points(
                collection_name=collection_name,
                query=query_vector,
                limit=limit,
            )
            return res.points

    def client_delete(self, collection_name: str, points_selector: Any) -> None:
        """Deletes points from a specific collection."""
        try:
            self._require_client().delete(
                collection_name=collection_name,
                points_selector=points_selector,
            )
        except Exception:
            self._require_client().delete(
                collection_name=collection_name,
                points_selector=points_selector,
            )

    def retrieve(self, collection_name: str, ids: List[str], with_payload: bool = True) -> List[Any]:
        """Retrieves points by ID from a collection."""
        return self._require_client().retrieve(
            collection_name=collection_name,
            ids=ids,
            with_payload=with_payload,
        )

    def scroll(
        self,
        collection_name: str,
        limit: int = 10,
        offset: Optional[str] = None,
        with_payload: bool = True,
        with_vectors: bool = False,
        scroll_filter: Any = None,
    ) -> Any:
        """Iteratively navigates through the points of a collection."""
        kwargs: Dict[str, Any] = {
            "collection_name": collection_name,
            "limit": limit,
            "with_payload": with_payload,
            "with_vectors": with_vectors,
        }
        if offset is not None:
            kwargs["offset"] = offset
        if scroll_filter is not None:
            kwargs["scroll_filter"] = scroll_filter
        return self._require_client().scroll(**kwargs)

    def query_points(self, collection_name: str, query: List[float], limit: int = 10) -> Any:
        """Modern search API (qdrant-client 1.11+)."""
        return self._require_client().query_points(
            collection_name=collection_name,
            query=query,
            limit=limit,
        )

    def close(self) -> None:
        """Closes the internal client. Do not use if the client comes from the shared pool."""
        if self._client is not None:
            try:
                self._client.close()
            except Exception:  # nosec B110: best-effort QdrantClient close; cleanup is the caller's responsibility either way
                pass
            self._client = None

    # ── High-level helpers (hide Qdrant models from callers) ──────────────────
    # Allow consumers (e.g. vector_index.py) to avoid importing
    # qdrant_client.models directly.

    def ensure_collection(
        self,
        collection_name: str,
        vector_size: int,
        distance: str = "cosine",
    ) -> bool:
        """
        Creates the collection if it does not exist.

        Hides VectorParams, Distance and the check logic from callers.

        Args:
            collection_name: Collection name
            vector_size: Vector dimension
            distance: "cosine", "euclid" or "dot"

        Returns:
            True if created, False if it already existed
        """
        from qdrant_client.models import Distance, VectorParams

        collections = self._require_client().get_collections().collections
        if collection_name in [c.name for c in collections]:
            return False

        distance_map = {
            "cosine": Distance.COSINE,
            "euclid": Distance.EUCLID,
            "dot": Distance.DOT,
        }
        self._require_client().create_collection(
            collection_name=collection_name,
            vectors_config=VectorParams(
                size=vector_size,
                distance=distance_map.get(distance, Distance.COSINE),
            ),
        )
        return True

    def upsert_points(
        self,
        collection_name: str,
        points_data: List[Dict[str, Any]],
    ) -> None:
        """
        Upsert of points without exposing PointStruct to callers.

        Args:
            collection_name: Target collection
            points_data: List of dicts with keys: `id`, `vector`, `payload`
        """
        from qdrant_client.models import PointStruct

        points = [
            PointStruct(id=p["id"], vector=p["vector"], payload=p.get("payload", {}))
            for p in points_data
        ]
        self._require_client().upsert(collection_name=collection_name, points=points)

    def search_with_filter(
        self,
        collection_name: str,
        query_vector: List[float],
        filter_conditions: Optional[List[Dict[str, Any]]] = None,
        limit: int = 10,
        score_threshold: Optional[float] = None,
    ) -> List[Any]:
        """
        Semantic search with metadata filter, without exposing Filter/FieldCondition.

        Args:
            collection_name: Collection to search
            query_vector: Query vector
            filter_conditions: List of dicts `{key, value}` as must conditions
            limit: Maximum number of results
            score_threshold: Minimum score (None = no limit)

        Returns:
            List of ScoredPoint (Qdrant results)
        """
        from qdrant_client.models import FieldCondition, Filter, MatchValue

        qdrant_filter = None
        if filter_conditions:
            must = [
                FieldCondition(key=c["key"], match=MatchValue(value=c["value"]))
                for c in filter_conditions
            ]
            qdrant_filter = Filter(must=must)

        try:
            return self._require_client().search(
                collection_name=collection_name,
                query_vector=query_vector,
                query_filter=qdrant_filter,
                limit=limit,
                score_threshold=score_threshold,
            )
        except Exception:
            res = self._require_client().query_points(
                collection_name=collection_name,
                query=query_vector,
                query_filter=qdrant_filter,
                limit=limit,
            )
            return res.points

    def delete_by_ids(self, collection_name: str, ids: List[str]) -> int:
        """
        Deletes points by IDs without exposing PointIdsList to callers.

        Args:
            collection_name: Target collection
            ids: List of IDs to delete

        Returns:
            Number of deleted points
        """
        from qdrant_client.models import PointIdsList

        if not ids:
            return 0
        self._require_client().delete(
            collection_name=collection_name,
            points_selector=PointIdsList(points=ids),
        )
        return len(ids)


__all__ = ["QdrantAdapter"]
