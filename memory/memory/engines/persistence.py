"""
────────────────────────────────────
Server Nexe
Author: Jordi Goy
Location: memory/memory/engines/persistence.py
Description: PersistenceManager — SQLite (metadades) + QdrantAdapter (vectors).

Arquitectura dual-store:
  - SQLite (WAL): font de veritat per a metadades i contingut textual
  - QdrantAdapter: índex vectorial per a cerca semàntica (substituïble)

Substituibilitat:
  El vector store s'accedeix via QdrantAdapter que implementa el Protocol
  VectorStore. Per canviar de Qdrant a un altre backend, substitueix
  QdrantAdapter per una altra implementació del Protocol.
  Veure: knowledge/*/ARCHITECTURE.md — secció "Com canviar el vector store"

www.jgoy.net · https://server-nexe.org
────────────────────────────────────
"""

import asyncio
import logging
import os
import uuid
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any, Dict, List, Optional

from ..constants import DEFAULT_VECTOR_SIZE
from ..models.memory_entry import MemoryEntry
from .persistence_sqlite import SqliteStorageMixin, SQLCIPHER_AVAILABLE

logger = logging.getLogger(__name__)


class StorageError(Exception):
    """Error en operacions de persistència."""


# Configurable timeouts via variables d'entorn
MAX_TIMEOUT = 60.0

def _safe_timeout(env_var: str, default: float) -> float:
    """Timeout des d'env var amb cap de seguretat."""
    try:
        value = float(os.getenv(env_var, str(default)))
        if value <= 0:
            return default
        return min(value, MAX_TIMEOUT)
    except (ValueError, TypeError):
        return default


QDRANT_TIMEOUT = _safe_timeout("NEXE_QDRANT_TIMEOUT", 5.0)
SQLITE_PRELOAD_TIMEOUT = _safe_timeout("NEXE_SQLITE_PRELOAD_TIMEOUT", 10.0)


class PersistenceManager(SqliteStorageMixin):
    """
    Gestor de persistència dual: SQLite + QdrantAdapter.

    Hereda tota la lògica SQLite de SqliteStorageMixin.
    Gestiona el vector store via QdrantAdapter (substituïble).

    Features:
      - SQLite WAL: metadades + text
      - QdrantAdapter: vectors d'embedding (intercanviable)
      - Rollback: elimina SQLite si Qdrant falla (mode strict)
      - run_in_executor per operacions blocking
    """

    DEFAULT_QDRANT_PATH = Path("storage/vectors")

    def __init__(
        self,
        db_path: Path,
        qdrant_path: Optional[Path] = None,
        collection_name: str = "nexe_memory",
        vector_size: int = DEFAULT_VECTOR_SIZE,
        qdrant_url: Optional[str] = None,
        crypto_provider=None,
    ):
        self.db_path = db_path
        self.qdrant_path = qdrant_path if qdrant_path is not None else self.DEFAULT_QDRANT_PATH
        self.qdrant_url = qdrant_url
        self.collection_name = collection_name
        self.vector_size = vector_size
        self._crypto = crypto_provider
        self._encrypted = False
        self._sqlite_preload_timeout = SQLITE_PRELOAD_TIMEOUT

        self.executor = ThreadPoolExecutor(max_workers=4)

        self._init_sqlite()
        self._init_qdrant()

        logger.info(
            "PersistenceManager initialized (db=%s, encrypted=%s, qdrant=%s)",
            db_path,
            self._encrypted,
            self.qdrant_path or self.qdrant_url or "Embedded",
        )

    @staticmethod
    def _hex_to_uuid(hex_id: str) -> str:
        """Converteix hex ID a UUID per Qdrant."""
        padded = hex_id.ljust(32, "0")
        return str(uuid.UUID(padded))

    def _init_qdrant(self):
        """
        Inicialitza el QdrantAdapter.

        Prioritat:
          1. Path local (mode embedded)
          2. URL (mode servidor)
        """
        from memory.embeddings.adapters import QdrantAdapter
        from memory.memory.engines.qdrant_types import Distance, VectorParams

        self.qdrant: Optional[Any] = None
        self._qdrant_available = False

        try:
            if self.qdrant_path:
                self.qdrant_path.mkdir(parents=True, exist_ok=True)
                self.qdrant = QdrantAdapter.from_pool(
                    collection_name=self.collection_name,
                    path=str(self.qdrant_path),
                )
                logger.info("Qdrant initialized in EMBEDDED mode at %s", self.qdrant_path)
            else:
                self.qdrant = QdrantAdapter.from_pool(
                    collection_name=self.collection_name,
                    url=self.qdrant_url,
                )
                logger.info("Qdrant initialized in SERVER mode at %s", self.qdrant_url)

            collections = self.qdrant.get_collections().collections
            collection_names = [c.name for c in collections]

            if self.collection_name not in collection_names:
                self.qdrant.create_collection(
                    collection_name=self.collection_name,
                    vectors_config=VectorParams(
                        size=self.vector_size,
                        distance=Distance.COSINE,
                    ),
                )
                logger.info("Created Qdrant collection '%s'", self.collection_name)
            else:
                logger.debug("Qdrant collection '%s' already exists", self.collection_name)

            self._qdrant_available = True

        except Exception as e:
            mode = "Embedded" if self.qdrant_path else "Server"
            logger.warning(
                "Qdrant %s mode failed: %s. Memory will use SQLite only (degraded mode).",
                mode,
                e,
            )
            self.qdrant = None
            self._qdrant_available = False

    async def store(
        self,
        entry: MemoryEntry,
        embedding: Optional[List[float]] = None,
        strict: bool = True,
    ) -> str:
        """
        Desa entry amb consistència dual (SQLite + Qdrant).

        Args:
            entry: MemoryEntry a desar
            embedding: Vector d'embedding (opcional)
            strict: Si True, rollback SQLite si Qdrant falla

        Returns:
            ID de l'entry

        Raises:
            StorageError: Si la persistència falla en mode strict
        """
        await self._store_sqlite(entry)

        if embedding and self._qdrant_available:
            try:
                payload = {
                    "entry_type": entry.entry_type,
                    "original_id": entry.id,
                }
                await self._store_qdrant(entry.id, embedding, payload)
            except Exception as e:
                if strict:
                    logger.error(
                        "CRITICAL: Qdrant storage failed for %s: %s. ROLLBACK SQLite.",
                        entry.id, e,
                    )
                    await self._delete_sqlite(entry.id)
                    raise StorageError(f"Storage failed (Strict rollback): {e}")
                else:
                    logger.warning(
                        "DEGRADED: Qdrant failed for %s: %s. Entry kept in SQLite only.",
                        entry.id, e,
                    )
        elif embedding and not self._qdrant_available:
            logger.debug("Entry %s stored only in SQLite (Qdrant unavailable).", entry.id)

        return entry.id

    async def _store_qdrant(
        self,
        entry_id: str,
        embedding: List[float],
        metadata: Dict[str, Any],
    ):
        """Desa vector a Qdrant via QdrantAdapter."""
        from memory.memory.engines.qdrant_types import PointStruct

        uuid_id = PersistenceManager._hex_to_uuid(entry_id)

        def _sync_upsert():
            point = PointStruct(
                id=uuid_id,
                vector=embedding,
                payload={**(metadata or {}), "original_id": entry_id},
            )
            self.qdrant.upsert(
                collection_name=self.collection_name,
                points=[point],
            )

        if self.qdrant_path:
            _sync_upsert()
        else:
            loop = asyncio.get_running_loop()
            await loop.run_in_executor(self.executor, _sync_upsert)

        logger.debug("Stored vector for %s to Qdrant", entry_id)

    async def search(
        self,
        query_vector: List[float],
        limit: int = 10,
        filter_type: Optional[str] = None,
    ) -> List[tuple]:
        """
        Cerca semàntica via QdrantAdapter.

        Returns:
            Llista de (entry_id, score)
        """
        loop = asyncio.get_running_loop()

        def _sync_search():
            return self.qdrant.client_search(
                collection_name=self.collection_name,
                query_vector=query_vector,
                limit=limit,
            )

        if self.qdrant_path:
            results = _sync_search()
        else:
            results = await loop.run_in_executor(self.executor, _sync_search)

        logger.debug("Qdrant search returned %s results", len(results))
        return [(r.id, r.score) for r in results]

    def close(self):
        """Tanca recursos. No tanca QdrantClient — és compartit via pool."""
        self.executor.shutdown(wait=True)
        self.qdrant = None
        logger.info("PersistenceManager closed")


__all__ = ["PersistenceManager", "StorageError", "SQLCIPHER_AVAILABLE"]
