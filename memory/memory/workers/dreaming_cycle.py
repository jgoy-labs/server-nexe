"""
────────────────────────────────────
Server Nexe
Author: Jordi Goy
Location: memory/memory/workers/dreaming_cycle.py
Description: Consolidation worker — processes staging to Profile/Episodic every 15min.

www.jgoy.net · https://server-nexe.org
────────────────────────────────────
"""

import asyncio
import hashlib
import json
import logging
from datetime import datetime, timezone
from typing import Any, Dict, Optional

from memory.memory.config import MemoryConfig

logger = logging.getLogger(__name__)


class DreamingCycle:
    """
    Background consolidation worker.

    Every interval_minutes (default 15):
    1. recover_stuck_leases()
    2. Process staging → Profile or Episodic
    3. Sync RDBMS → Vector Index
    4. Lightweight GC (expired TTL)

    NEVER crash — log and continue. RDBMS transactions protect consistency.
    Independent worker via asyncio.create_task, NOT FastAPI BackgroundTask.
    """

    def __init__(
        self,
        config: Optional[MemoryConfig] = None,
        sqlite_store=None,
        vector_index=None,
        embedder=None,
        *,
        store=None,
    ):
        if config is None:
            from memory.memory.config import get_config
            config = get_config("m1_8gb")
        self._config = config
        self._store = sqlite_store or store
        self._vector = vector_index
        self._embedder = embedder

        self._interval = config.dreaming.interval_minutes * 60
        self._force_threshold = 50
        self._consecutive_skips = 0
        self._is_running = False
        self._should_stop = False
        self._task: Optional[asyncio.Task] = None

    async def run(self):
        """Start the dreaming cycle loop. Alias: start()."""
        return await self.start()

    async def start(self):
        """Start the dreaming cycle loop."""
        logger.info("DreamingCycle started (interval=%ds)", self._interval)
        self._should_stop = False

        # Immediate first cycle if staging has pending entries
        await self.run_cycle()

        while not self._should_stop:
            try:
                await asyncio.sleep(self._interval)
                if not self._should_stop:
                    await self.run_cycle()
            except asyncio.CancelledError:
                logger.info("DreamingCycle cancelled")
                break
            except Exception as e:
                logger.error("DreamingCycle loop error: %s", e)

    def stop(self):
        """Signal the cycle to stop."""
        self._should_stop = True
        if self._task and not self._task.done():
            self._task.cancel()

    async def run_cycle(self):
        """Execute one consolidation cycle."""
        if self._is_running:
            self._consecutive_skips += 1
            if self._consecutive_skips >= 3:
                logger.warning("DreamingCycle: 3 consecutive skips")
            return

        self._is_running = True
        try:
            pending_count = self._count_pending()
            forced = (
                pending_count > self._force_threshold
                or self._consecutive_skips >= 3
            )

            if forced:
                logger.info(
                    "DreamingCycle: forced run (%d pending, %d skips)",
                    pending_count, self._consecutive_skips,
                )

            await self._recover_stuck_leases()
            await self._process_staging()
            await self._sync_vector_index()
            await self._gc_lightweight()

            self._consecutive_skips = 0
            logger.debug("DreamingCycle: cycle complete")

        except Exception as e:
            logger.error("DreamingCycle error: %s", e)
        finally:
            self._is_running = False

    def _count_pending(self) -> int:
        """Count pending staging entries."""
        if not self._store:
            return 0
        try:
            self._store.get_staging(user_id="*", status="pending", limit=1)
            # get_staging filters by user_id, so count all users
            conn = self._store._connect()
            cursor = conn.execute(
                "SELECT COUNT(*) FROM staging WHERE status = ?",
                ("pending",),
            )
            return cursor.fetchone()[0]
        except Exception:
            return 0

    async def _recover_stuck_leases(self):
        """Reset leased entries older than 5 minutes."""
        if not self._store:
            return
        try:
            conn = self._store._connect()
            conn.execute(
                "UPDATE staging SET status = 'pending', leased_at = NULL, "
                "worker_id = NULL "
                "WHERE status = 'leased' "
                "AND leased_at < datetime('now', '-5 minutes')"
            )
            conn.commit()
        except Exception as e:
            logger.error("recover_stuck_leases failed: %s", e)

    async def _process_staging(self):
        """Process pending staging entries in batches."""
        if not self._store:
            return

        try:
            conn = self._store._connect()
            cursor = conn.execute(
                "SELECT * FROM staging WHERE status = ? "
                "ORDER BY created_at ASC LIMIT ?",
                ("pending", 10),
            )
            entries = [dict(row) for row in cursor.fetchall()]

            for entry in entries:
                if self._should_stop:
                    break
                try:
                    await self._process_one(entry)
                except Exception as e:
                    logger.error(
                        "Failed to process staging %s: %s",
                        entry.get("id"), e,
                    )
                    conn.execute(
                        "UPDATE staging SET status = 'failed', "
                        "retry_count = retry_count + 1 WHERE id = ?",
                        (entry["id"],),
                    )
                    conn.commit()

                # Yield control to event loop
                await asyncio.sleep(0)

        except Exception as e:
            logger.error("_process_staging failed: %s", e)

    async def _process_one(self, entry: Dict[str, Any]):
        """Process a single staging entry to Profile or Episodic."""
        if not self._store:
            return

        conn = self._store._connect()
        entry_id = entry["id"]
        user_id = entry["user_id"]
        decision = entry.get("validator_decision", "stage_only")
        target = entry.get("target_store")

        # Lease the entry
        conn.execute(
            "UPDATE staging SET status = 'leased', "
            "leased_at = datetime('now'), worker_id = 'dreaming' "
            "WHERE id = ?",
            (entry_id,),
        )
        conn.commit()

        extractor_json = entry.get("extractor_output_json")
        extractor_output = json.loads(extractor_json) if extractor_json else {}

        if decision == "upsert_profile" or target == "profile":
            attribute = extractor_output.get("attribute")
            value = extractor_output.get("value", entry.get("raw_text"))
            if attribute:
                self._store.upsert_profile(
                    user_id=user_id,
                    attribute=attribute,
                    value=value,
                    entity=extractor_output.get("entity", "user"),
                    source=entry.get("source", "dreaming"),
                    trust_level=entry.get("trust_level", "untrusted"),
                    is_critical=extractor_output.get("is_critical", False),
                )

        elif decision in ("promote_episodic", "stage_only") or target == "episodic":
            content = entry.get("raw_text", "")
            content_hash = hashlib.sha256(
                content.lower().strip().encode()
            ).hexdigest()

            # Tombstone check
            if self._store.is_tombstoned(user_id, content_hash):
                trust = entry.get("trust_level", "untrusted")
                if trust != "trusted":
                    logger.debug("Tombstoned content skipped: %s", entry_id)
                    conn.execute(
                        "UPDATE staging SET status = 'processed' WHERE id = ?",
                        (entry_id,),
                    )
                    conn.commit()
                    return

            # Dedup check (v1: >0.92 refresh, <0.92 new)
            if self._vector and self._vector.available and self._embedder:
                try:
                    embedding = self._embedder.encode(content)
                    emb_list = embedding.tolist() if hasattr(embedding, 'tolist') else list(embedding)
                    similar = self._vector.search(
                        embedding=emb_list,
                        user_id=user_id,
                        threshold=self._config.dedup_refresh_threshold,
                        limit=1,
                    )
                    if similar and similar[0]["score"] > self._config.dedup_refresh_threshold:
                        # Quasi-duplicate: refresh
                        existing_id = similar[0]["id"]
                        conn.execute(
                            "UPDATE episodic SET updated_at = datetime('now'), "
                            "evidence_count = MIN(10, evidence_count + 1) "
                            "WHERE id = ?",
                            (existing_id,),
                        )
                        conn.execute(
                            "UPDATE staging SET status = 'processed' WHERE id = ?",
                            (entry_id,),
                        )
                        conn.commit()
                        return
                except Exception as e:
                    logger.debug("Dedup check failed, inserting as new: %s", e)

            # Insert new episodic
            importance = extractor_output.get("importance", 0.5)
            self._store.insert_episodic(
                user_id=user_id,
                content=content,
                memory_type=extractor_output.get("type", "fact"),
                importance=importance,
                source=entry.get("source", "dreaming"),
                trust_level=entry.get("trust_level", "untrusted"),
                namespace=entry.get("namespace", "default"),
                metadata=extractor_output.get("metadata"),
                related_ids=extractor_output.get("related_ids"),
            )

        # Mark processed
        conn.execute(
            "UPDATE staging SET status = 'processed' WHERE id = ?",
            (entry_id,),
        )
        conn.commit()

    async def _sync_vector_index(self):
        """Sync unsynced RDBMS entries to vector index."""
        if not self._store or not self._vector or not self._embedder:
            return
        if not self._vector.available:
            return

        try:
            conn = self._store._connect()
            cursor = conn.execute(
                "SELECT id, user_id, content, namespace, memory_type, "
                "importance, trust_level, created_at, state "
                "FROM episodic WHERE vector_synced = 0 AND state = 'active' "
                "LIMIT 20"
            )
            rows = [dict(r) for r in cursor.fetchall()]
            if not rows:
                return

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
                logger.debug("Synced %d entries to vector index", indexed)

        except Exception as e:
            logger.error("_sync_vector_index failed: %s", e)

    async def _gc_lightweight(self):
        """Lightweight GC: expire TTL staging + old tombstones."""
        if not self._store:
            return
        try:
            conn = self._store._connect()
            now = datetime.now(timezone.utc).isoformat()

            # Expire old staging
            conn.execute(
                "DELETE FROM staging WHERE expires_at < ? AND status != ?",
                (now, "processed"),
            )

            # Expire old tombstones
            conn.execute(
                "DELETE FROM tombstones WHERE expires_at < ?",
                (now,),
            )

            conn.commit()
        except Exception as e:
            logger.error("_gc_lightweight failed: %s", e)


__all__ = ["DreamingCycle"]
