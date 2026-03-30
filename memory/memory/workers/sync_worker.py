"""
────────────────────────────────────
Server Nexe
Author: Jordi Goy
Location: memory/memory/workers/sync_worker.py
Description: RDBMS → Vector Index sync worker. Runs within DreamingCycle.

www.jgoy.net · https://server-nexe.org
────────────────────────────────────
"""

import logging
from typing import Dict

logger = logging.getLogger(__name__)


class SyncWorker:
    """
    Synchronizes RDBMS episodic entries to Vector Index.

    Write-ahead: RDBMS is written first, vector_synced flag tracks sync state.
    This worker runs within the DreamingCycle, not independently.
    """

    def __init__(
        self,
        sqlite_store=None,
        vector_index=None,
        embedder=None,
    ):
        self._store = sqlite_store
        self._vector = vector_index
        self._embedder = embedder

    async def sync_pending(self, batch_size: int = 20) -> int:
        """
        Sync entries with vector_synced=false to the vector index.

        Returns number of entries synced.
        """
        if not self._store or not self._vector or not self._embedder:
            return 0
        if not self._vector.available:
            return 0

        try:
            conn = self._store._connect()
            cursor = conn.execute(
                "SELECT id, user_id, content, namespace, memory_type, "
                "importance, trust_level, created_at, state "
                "FROM episodic WHERE vector_synced = 0 AND state = 'active' "
                "LIMIT ?",
                (batch_size,),
            )
            rows = [dict(r) for r in cursor.fetchall()]
            if not rows:
                return 0

            contents = [r["content"] for r in rows]
            embeddings = self._embedder.encode_batch(contents)
            if hasattr(embeddings, 'tolist'):
                embeddings = embeddings.tolist()

            entries = []
            for row in rows:
                entries.append({
                    "id": row["id"],
                    "user_id": row["user_id"],
                    "namespace": row.get("namespace", "default"),
                    "memory_type": row.get("memory_type", "fact"),
                    "state": row.get("state", "active"),
                    "importance": row.get("importance", 0.5),
                    "trust_level": row.get("trust_level", "untrusted"),
                    "created_at": row.get("created_at"),
                })

            indexed = self._vector.index(entries, embeddings)
            if indexed > 0:
                ids = [r["id"] for r in rows]
                placeholders = ",".join("?" for _ in ids)
                conn.execute(
                    f"UPDATE episodic SET vector_synced = 1 "
                    f"WHERE id IN ({placeholders})",
                    ids,
                )
                conn.commit()
                logger.debug("SyncWorker: synced %d entries", indexed)

            return indexed

        except Exception as e:
            logger.error("SyncWorker.sync_pending failed: %s", e)
            return 0

    def get_sync_status(self) -> Dict[str, int]:
        """Get sync status: total vs unsynced counts."""
        if not self._store:
            return {"total": 0, "unsynced": 0}

        try:
            conn = self._store._connect()
            total = conn.execute(
                "SELECT COUNT(*) FROM episodic WHERE state = 'active'"
            ).fetchone()[0]
            unsynced = conn.execute(
                "SELECT COUNT(*) FROM episodic "
                "WHERE state = 'active' AND vector_synced = 0"
            ).fetchone()[0]
            return {"total": total, "unsynced": unsynced}
        except Exception:
            return {"total": 0, "unsynced": 0}


__all__ = ["SyncWorker"]
