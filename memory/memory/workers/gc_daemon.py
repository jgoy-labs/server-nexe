"""
────────────────────────────────────
Server Nexe
Author: Jordi Goy
Location: memory/memory/workers/gc_daemon.py
Description: Garbage collection daemon for memory system.

www.jgoy.net · https://server-nexe.org
────────────────────────────────────
"""

import logging
import math
from datetime import datetime, timezone
from typing import Any, Dict, Optional

from memory.memory.config import MemoryConfig

logger = logging.getLogger(__name__)


class GCDaemon:
    """
    Garbage collection for the memory system.

    Profile: NEVER auto-delete (v1 decision).
    Episodic: half-life 60 days, score = importance * exp(-age/half_life) * access_boost.
    Access boost: min(3.0, 1.0 + log2(access_count+1) * 0.3).
    Tombstones: 90-day TTL.
    Budget enforcement with absolute limits.
    """

    def __init__(
        self,
        config: MemoryConfig,
        sqlite_store=None,
        vector_index=None,
    ):
        self._config = config
        self._store = sqlite_store
        self._vector = vector_index

    def calculate_entry_score(
        self,
        importance: float,
        created_at: str,
        access_count: int = 0,
        last_accessed: Optional[str] = None,
    ) -> float:
        """
        Calculate GC score for an episodic entry.

        score = importance * exp(-age_days / half_life) * access_boost
        Access boost = min(3.0, 1.0 + log2(access_count+1) * 0.3)
        """
        half_life = self._config.gc.episodic_half_life_days

        # Age in days
        now = datetime.now(timezone.utc)
        try:
            if isinstance(created_at, str):
                created = datetime.fromisoformat(created_at.replace("Z", "+00:00"))
            else:
                created = created_at
            age_days = max(0, (now - created).total_seconds() / 86400)
        except (ValueError, TypeError):
            age_days = 0

        # Decay
        decay = math.exp(-age_days / half_life)

        # Access boost (logarithmic with saturation)
        access_boost = min(
            self._config.gc.access_boost_max,
            1.0 + math.log2(access_count + 1) * 0.3,
        )

        # Cooldown: if last access > 90 days ago, halve the boost
        if last_accessed:
            try:
                if isinstance(last_accessed, str):
                    last_acc = datetime.fromisoformat(
                        last_accessed.replace("Z", "+00:00")
                    )
                else:
                    last_acc = last_accessed
                days_since_access = (now - last_acc).total_seconds() / 86400
                if days_since_access > 90:
                    access_boost = 1.0 + (access_boost - 1.0) / 2
            except (ValueError, TypeError):
                pass

        return importance * decay * access_boost

    def run_gc(self, user_id: str, dry_run: bool = False) -> Dict[str, Any]:
        """
        Run full GC for a user.

        Profile: NEVER auto-delete.
        Episodic: delete entries with score < 0.15.
        Enforce absolute budget limits.

        Args:
            user_id: User to GC.
            dry_run: If True, report without deleting.

        Returns:
            Dict with GC results.
        """
        result = {
            "user_id": user_id,
            "dry_run": dry_run,
            "episodic_scanned": 0,
            "episodic_deleted": 0,
            "tombstones_expired": 0,
            "budget_enforced": False,
        }

        if not self._store:
            return result

        try:
            conn = self._store._connect()

            # 1. Score and purge episodic entries below threshold
            cursor = conn.execute(
                "SELECT id, importance, created_at, access_count, last_accessed "
                "FROM episodic WHERE user_id = ? AND state = 'active'",
                (user_id,),
            )
            entries = [dict(r) for r in cursor.fetchall()]
            result["episodic_scanned"] = len(entries)

            to_delete = []
            for entry in entries:
                score = self.calculate_entry_score(
                    importance=entry.get("importance", 0.5),
                    created_at=entry.get("created_at", ""),
                    access_count=entry.get("access_count", 0),
                    last_accessed=entry.get("last_accessed"),
                )
                if score < 0.15:
                    to_delete.append(entry["id"])

            # 2. Budget enforcement: if over 90%, delete worst 15%
            budget_max = self._config.budgets.episodic_max
            if len(entries) > int(budget_max * 0.9):
                result["budget_enforced"] = True
                # Sort by score ascending — worst first
                scored = []
                for entry in entries:
                    s = self.calculate_entry_score(
                        importance=entry.get("importance", 0.5),
                        created_at=entry.get("created_at", ""),
                        access_count=entry.get("access_count", 0),
                        last_accessed=entry.get("last_accessed"),
                    )
                    scored.append((entry["id"], s))
                scored.sort(key=lambda x: x[1])
                purge_count = max(1, int(len(entries) * 0.15))
                budget_ids = [s[0] for s in scored[:purge_count]]
                to_delete = list(set(to_delete) | set(budget_ids))

            result["episodic_deleted"] = len(to_delete)

            if not dry_run and to_delete:
                # Delete from RDBMS
                placeholders = ",".join("?" for _ in to_delete)
                conn.execute(
                    f"UPDATE episodic SET state = 'archived' "
                    f"WHERE id IN ({placeholders})",
                    to_delete,
                )
                conn.commit()

                # Delete from vector index
                if self._vector:
                    try:
                        self._vector.delete(to_delete)
                    except Exception as e:
                        logger.warning("GC vector delete failed: %s", e)

                # Create tombstones
                for eid in to_delete:
                    try:
                        self._store.add_tombstone(
                            user_id=user_id,
                            content_hash=eid,
                            reason="gc_decay",
                        )
                    except Exception:
                        pass

            # 3. Expire old tombstones
            now = datetime.now(timezone.utc).isoformat()
            if not dry_run:
                cursor = conn.execute(
                    "SELECT COUNT(*) FROM tombstones "
                    "WHERE user_id = ? AND expires_at < ?",
                    (user_id, now),
                )
                result["tombstones_expired"] = cursor.fetchone()[0]
                conn.execute(
                    "DELETE FROM tombstones WHERE user_id = ? AND expires_at < ?",
                    (user_id, now),
                )
                conn.commit()
            else:
                cursor = conn.execute(
                    "SELECT COUNT(*) FROM tombstones "
                    "WHERE user_id = ? AND expires_at < ?",
                    (user_id, now),
                )
                result["tombstones_expired"] = cursor.fetchone()[0]

            # Log
            if not dry_run:
                conn.execute(
                    "INSERT INTO gc_log "
                    "(profile_scanned, profile_deleted, episodic_scanned, "
                    "episodic_deleted, staging_purged, tombstones_expired) "
                    "VALUES (?, ?, ?, ?, ?, ?)",
                    (0, 0, result["episodic_scanned"],
                     result["episodic_deleted"], 0,
                     result["tombstones_expired"]),
                )
                conn.commit()

        except Exception as e:
            logger.error("GC failed for user %s: %s", user_id, e)

        return result


__all__ = ["GCDaemon"]
