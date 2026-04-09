"""
────────────────────────────────────
Server Nexe
Author: Jordi Goy
Location: memory/embeddings/adapters/qdrant_adapter.py
Description: QdrantAdapter — implementació del Protocol VectorStore sobre QdrantClient.

Propòsit:
  Capa d'indireció entre els consumidors del vector store i Qdrant.
  Permet substituir Qdrant per qualsevol altre vector store implementant
  el Protocol VectorStore sense tocar els consumidors.

Protocol implementat:
  memory.embeddings.core.vectorstore.VectorStore

Mètodes addicionals de gestió (passthrough):
  Exposa els mètodes de col·lecció necessaris per consumidors existents.
  Això permet la migració gradual sense trencar l'API existent.

Ús:
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
    Adaptor entre el Protocol VectorStore i QdrantClient.

    Una instància = una col·lecció per defecte (per al Protocol).
    Mètodes passthrough permeten gestió multi-col·lecció (compatible legacy).

    Args:
        collection_name: Col·lecció per defecte per als mètodes del Protocol
        path: Path local (mode embedded)
        url: URL del servidor Qdrant (mode servidor)
        client: QdrantClient ja creat (prioritat sobre path/url)

    Exemple canvi de backend futur (per documentació):
        class WeaviateAdapter:
            def add_vectors(self, ...): # usa weaviate-client
            def search(self, ...): # usa weaviate-client
            def delete(self, ...): # usa weaviate-client
            def health(self, ...): # usa weaviate-client
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

    def _create_client(self) -> Any:
        """Crea el QdrantClient intern via el pool compartit."""
        from core.qdrant_pool import get_qdrant_client
        if self._path:
            return get_qdrant_client(path=self._path)
        if self._url:
            return get_qdrant_client(url=self._url)
        return get_qdrant_client()

    @classmethod
    def from_pool(cls, collection_name: str, path: Optional[str] = None, url: Optional[str] = None) -> "QdrantAdapter":
        """Crea adapter usant el pool compartit (core.qdrant_pool)."""
        from core.qdrant_pool import get_qdrant_client
        if path:
            client = get_qdrant_client(path=path)
        else:
            client = get_qdrant_client(url=url)
        return cls(collection_name=collection_name, client=client)

    # ── Protocol VectorStore ──────────────────────────────────────────────────

    def add_vectors(
        self,
        vectors: List[List[float]],
        texts: List[str],
        metadatas: List[Dict[str, Any]],
    ) -> List[str]:
        """
        Afegir vectors al store.

        Implementa VectorStore.add_vectors().
        Genera IDs UUID v4 per cada vector.

        Returns:
            Llista d'IDs generats
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

        self._client.upsert(
            collection_name=self._collection_name,
            points=points,
        )
        logger.debug("add_vectors: %d vectors afegits a '%s'", len(ids), self._collection_name)
        return ids

    def search(self, request: Any) -> List[Any]:
        """
        Cerca semàntica en la col·lecció per defecte.

        Implementa VectorStore.search() — accepta VectorSearchRequest.

        Returns:
            Llista de VectorSearchHit
        """
        from memory.embeddings.core.vectorstore import VectorSearchHit

        try:
            results = self._client.search(
                collection_name=self._collection_name,
                query_vector=request.query_vector,
                limit=request.top_k,
                score_threshold=None,
            )
        except Exception:
            # Fallback per qdrant-client moderns (1.11+)
            res = self._client.query_points(
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
        Eliminar vectors per IDs de la col·lecció per defecte.

        Implementa VectorStore.delete().

        Returns:
            Nombre de vectors eliminats
        """
        from qdrant_client.models import PointIdsList

        if not ids:
            return 0

        self._client.delete(
            collection_name=self._collection_name,
            points_selector=PointIdsList(points=ids),
        )
        logger.debug("delete: %d vectors eliminats de '%s'", len(ids), self._collection_name)
        return len(ids)

    def health(self) -> Dict[str, Any]:
        """
        Estat de salut del vector store.

        Implementa VectorStore.health().

        Returns:
            Dict amb status, num_vectors, collection
        """
        try:
            info = self._client.get_collection(self._collection_name)
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

    # ── Passthrough de gestió de col·leccions (compat legacy) ─────────────────
    # Permeten que documents.py, collections.py i persistence.py segueixin
    # cridant els mateixos mètodes sense canvis de lògica.
    # Quan es migri a un altre backend, cal implementar aquests mètodes.

    def get_collections(self) -> Any:
        """Llista de totes les col·leccions."""
        return self._client.get_collections()

    def create_collection(self, collection_name: str, vectors_config: Any) -> None:
        """Crea una nova col·lecció."""
        self._client.create_collection(
            collection_name=collection_name,
            vectors_config=vectors_config,
        )

    def delete_collection(self, collection_name: str) -> None:
        """Elimina una col·lecció."""
        self._client.delete_collection(collection_name=collection_name)

    def get_collection(self, collection_name: str) -> Any:
        """Informació d'una col·lecció."""
        return self._client.get_collection(collection_name)

    def upsert(self, collection_name: str, points: List[Any]) -> None:
        """Afegir o actualitzar punts en una col·lecció."""
        self._client.upsert(collection_name=collection_name, points=points)

    def client_search(
        self,
        collection_name: str,
        query_vector: List[float],
        query_filter: Any = None,
        limit: int = 10,
        score_threshold: Optional[float] = None,
    ) -> List[Any]:
        """Cerca en una col·lecció específica (API legacy)."""
        try:
            return self._client.search(
                collection_name=collection_name,
                query_vector=query_vector,
                query_filter=query_filter,
                limit=limit,
                score_threshold=score_threshold,
            )
        except Exception:
            res = self._client.query_points(
                collection_name=collection_name,
                query=query_vector,
                limit=limit,
            )
            return res.points

    def client_delete(self, collection_name: str, points_selector: Any) -> None:
        """Elimina punts d'una col·lecció específica."""
        try:
            self._client.delete(
                collection_name=collection_name,
                points_selector=points_selector,
            )
        except Exception:
            self._client.delete(
                collection_name=collection_name,
                points_selector=points_selector,
            )

    def retrieve(self, collection_name: str, ids: List[str], with_payload: bool = True) -> List[Any]:
        """Recupera punts per ID d'una col·lecció."""
        return self._client.retrieve(
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
        """Navega iterativament pels punts d'una col·lecció."""
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
        return self._client.scroll(**kwargs)

    def query_points(self, collection_name: str, query: List[float], limit: int = 10) -> Any:
        """API moderna de cerca (qdrant-client 1.11+)."""
        return self._client.query_points(
            collection_name=collection_name,
            query=query,
            limit=limit,
        )

    def close(self) -> None:
        """Tanca el client intern. No usar si el client ve del pool compartit."""
        if self._client:
            try:
                self._client.close()
            except Exception:
                pass
            self._client = None

    # ── Helpers d'alt nivell (oculten models Qdrant als callers) ─────────────
    # Permeten que els consumidors (ex: vector_index.py) no necessitin importar
    # qdrant_client.models directament.

    def ensure_collection(
        self,
        collection_name: str,
        vector_size: int,
        distance: str = "cosine",
    ) -> bool:
        """
        Crea la col·lecció si no existeix.

        Oculta VectorParams, Distance i la lògica de check als callers.

        Args:
            collection_name: Nom de la col·lecció
            vector_size: Dimensió dels vectors
            distance: "cosine", "euclid" o "dot"

        Returns:
            True si creada, False si ja existia
        """
        from qdrant_client.models import Distance, VectorParams

        collections = self._client.get_collections().collections
        if collection_name in [c.name for c in collections]:
            return False

        distance_map = {
            "cosine": Distance.COSINE,
            "euclid": Distance.EUCLID,
            "dot": Distance.DOT,
        }
        self._client.create_collection(
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
        Upsert de punts sense exposar PointStruct als callers.

        Args:
            collection_name: Col·lecció destí
            points_data: Llista de dicts amb claus: `id`, `vector`, `payload`
        """
        from qdrant_client.models import PointStruct

        points = [
            PointStruct(id=p["id"], vector=p["vector"], payload=p.get("payload", {}))
            for p in points_data
        ]
        self._client.upsert(collection_name=collection_name, points=points)

    def search_with_filter(
        self,
        collection_name: str,
        query_vector: List[float],
        filter_conditions: Optional[List[Dict[str, Any]]] = None,
        limit: int = 10,
        score_threshold: Optional[float] = None,
    ) -> List[Any]:
        """
        Cerca semàntica amb filtre de metadades, sense exposar Filter/FieldCondition.

        Args:
            collection_name: Col·lecció a cercar
            query_vector: Vector de consulta
            filter_conditions: Llista de dicts `{key, value}` com a condicions must
            limit: Màxim de resultats
            score_threshold: Puntuació mínima (None = sense límit)

        Returns:
            Llista de ScoredPoint (resultats Qdrant)
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
            return self._client.search(
                collection_name=collection_name,
                query_vector=query_vector,
                query_filter=qdrant_filter,
                limit=limit,
                score_threshold=score_threshold,
            )
        except Exception:
            res = self._client.query_points(
                collection_name=collection_name,
                query=query_vector,
                limit=limit,
            )
            return res.points

    def delete_by_ids(self, collection_name: str, ids: List[str]) -> int:
        """
        Elimina punts per IDs sense exposar PointIdsList als callers.

        Args:
            collection_name: Col·lecció destí
            ids: Llista d'IDs a eliminar

        Returns:
            Nombre de punts eliminats
        """
        from qdrant_client.models import PointIdsList

        if not ids:
            return 0
        self._client.delete(
            collection_name=collection_name,
            points_selector=PointIdsList(points=ids),
        )
        return len(ids)


__all__ = ["QdrantAdapter"]
