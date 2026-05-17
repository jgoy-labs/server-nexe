"""
────────────────────────────────────
Server Nexe
Author: Jordi Goy
Location: memory/memory/engines/persistence.py
Description: PersistenceManager — SQLite (metadata) + QdrantAdapter (vectors).

Dual-store architecture:
  - SQLite (WAL): source of truth for metadata and textual content
  - QdrantAdapter: vector index for semantic search (replaceable)

Replaceability:
  The vector store is accessed via QdrantAdapter which implements the Protocol
  VectorStore. To switch from Qdrant to another backend, replace
  QdrantAdapter with another implementation of the Protocol.
  See: knowledge/*/ARCHITECTURE.md — section "How to change the vector store"

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
    """Error in persistence operations."""


# Configurable timeouts via environment variables
MAX_TIMEOUT = 60.0

def _safe_timeout(env_var: str, default: float) -> float:
    """Timeout from env var with safety cap."""
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
    Dual persistence manager: SQLite + QdrantAdapter.

    Inherits all SQLite logic from SqliteStorageMixin.
    Manages the vector store via QdrantAdapter (replaceable).

    Features:
      - SQLite WAL: metadata + text
      - QdrantAdapter: embedding vectors (interchangeable)
      - Rollback: deletes SQLite if Qdrant fails (strict mode)
      - run_in_executor for blocking operations
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
        # F2.2: resol DEFAULT_QDRANT_PATH via SidecarConfig en sidecar mode
        from memory.memory._paths import resolve_qdrant_path
        self.db_path = db_path
        self.qdrant_path = qdrant_path if qdrant_path is not None else resolve_qdrant_path(self.DEFAULT_QDRANT_PATH)
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
        """Convert hex ID to UUID for Qdrant."""
        padded = hex_id.ljust(32, "0")
        return str(uuid.UUID(padded))

    def _init_qdrant(self) -> None:
        """
        Initialize the QdrantAdapter.

        Priority:
          1. Local path (embedded mode)
          2. URL (server mode)
        """
        from memory.embeddings.adapters import QdrantAdapter
        # qdrant_client re-export via local module — pyright cannot resolve the
        # re-export chain reliably for runtime symbols, so silence false-positive.
        from .qdrant_types import Distance, VectorParams  # pyright: ignore[reportAttributeAccessIssue]

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
        Save entry with dual consistency (SQLite + Qdrant).

        Args:
            entry: MemoryEntry to save
            embedding: Embedding vector (optional)
            strict: If True, rollback SQLite if Qdrant fails

        Returns:
            Entry ID

        Raises:
            StorageError: If persistence fails in strict mode
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
        """Save vector to Qdrant via QdrantAdapter."""
        from .qdrant_types import PointStruct  # pyright: ignore[reportAttributeAccessIssue]

        uuid_id = PersistenceManager._hex_to_uuid(entry_id)

        def _sync_upsert():
            if self.qdrant is None:
                return
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
    ) -> List[tuple]:
        """
        Semantic search via QdrantAdapter.

        Returns:
            List of (entry_id, score)
        """
        loop = asyncio.get_running_loop()

        def _sync_search():
            if self.qdrant is None:
                return []
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
        """Close resources. Does not close QdrantClient — it is shared via pool."""
        self.executor.shutdown(wait=True)
        self.qdrant = None
        logger.info("PersistenceManager closed")


__all__ = ["PersistenceManager", "StorageError", "SQLCIPHER_AVAILABLE"]
