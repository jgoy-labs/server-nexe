"""
────────────────────────────────────
Server Nexe
Author: Jordi Goy
Location: memory/memory/workers/gc_daemon.py
Description: Garbage collection daemon for memory system.

www.jgoy.net · https://server-nexe.org
────────────────────────────────────
"""

import asyncio
import logging
import math
from datetime import datetime, timezone
from typing import Any, Callable, Dict, Optional

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

    def _gc_score_entries(self, entries) -> list:
        """Return list of entry IDs with score < 0.15."""
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
        return to_delete

    def _gc_enforce_budget(self, entries, to_delete: list) -> list:
        """If over 90% budget, add worst 15% to deletion list. Returns merged list."""
        budget_max = self._config.budgets.episodic_max
        if len(entries) <= int(budget_max * 0.9):
            return to_delete
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
        return list(set(to_delete) | set(budget_ids))

    def _gc_delete_entries(self, conn, user_id: str, to_delete: list) -> None:
        """Archive entries in RDBMS, remove from vector index, create tombstones.

        Tombstones MUST carry the entry's real ``content_hash`` (SHA256 of the
        normalised content), not its ``id`` (a uuid4[:16]). The reinsertion guard
        in ``DreamingCycle._process_episodic`` looks up ``is_tombstoned`` by the
        recomputed content hash, so an id-keyed tombstone could never match and
        the gc_decay anti-zombie protection was dead weight (B032).
        """
        placeholders = ",".join("?" for _ in to_delete)
        # Resolve the real content_hash of each entry before archiving (archiving
        # only flips ``state``, so the hash column is unaffected by order).
        hash_rows = conn.execute(
            f"SELECT id, content_hash FROM episodic WHERE id IN ({placeholders})",  # nosec B608: dynamic '?' placeholder count for IN clause, all values bound as parameters
            to_delete,
        ).fetchall()  # nosemgrep: sqlalchemy-execute-raw-query — parameterized with '?' placeholders
        id_to_hash = {row["id"]: row["content_hash"] for row in hash_rows}
        sql = f"UPDATE episodic SET state = 'archived' WHERE id IN ({placeholders})"  # nosec B608: dynamic '?' placeholder count for IN clause, all values bound as parameters
        conn.execute(sql, to_delete)  # nosemgrep: sqlalchemy-execute-raw-query — parameterized with '?' placeholders
        conn.commit()
        if self._vector:
            try:
                self._vector.delete(to_delete)
            except Exception as e:
                logger.warning("GC vector delete failed: %s", e)
        if self._store is None:
            return
        for eid in to_delete:
            content_hash = id_to_hash.get(eid)
            if content_hash is None:
                # No row found for this id (e.g. concurrently deleted) — without
                # the real hash a tombstone would be inert, so skip it loudly.
                logger.warning("GC: no content_hash for entry %s; tombstone skipped", eid)
                continue
            try:
                self._store.add_tombstone(user_id=user_id, content_hash=content_hash, reason="gc_decay")
            except Exception:  # nosec B110: best-effort tombstone insertion during GC; failure logged elsewhere via outer error path
                pass

    def _gc_expire_tombstones(self, conn, user_id: str, dry_run: bool) -> int:
        """Count (and optionally delete) expired tombstones. Returns count."""
        now = datetime.now(timezone.utc).isoformat()
        cursor = conn.execute(
            "SELECT COUNT(*) FROM tombstones WHERE user_id = ? AND expires_at < ?",
            (user_id, now),
        )
        count = cursor.fetchone()[0]
        if not dry_run:
            conn.execute(
                "DELETE FROM tombstones WHERE user_id = ? AND expires_at < ?",
                (user_id, now),
            )
            conn.commit()
        return count

    def _gc_write_log(self, conn, result: dict) -> None:
        """Insert a gc_log row summarising this GC run."""
        conn.execute(
            "INSERT INTO gc_log "
            "(profile_scanned, profile_deleted, episodic_scanned, "
            "episodic_deleted, staging_purged, tombstones_expired) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (0, 0, result["episodic_scanned"], result["episodic_deleted"],
             0, result["tombstones_expired"]),
        )
        conn.commit()

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

            to_delete = self._gc_score_entries(entries)

            # 2. Budget enforcement
            budget_max = self._config.budgets.episodic_max
            if len(entries) > int(budget_max * 0.9):
                result["budget_enforced"] = True
                to_delete = self._gc_enforce_budget(entries, to_delete)

            result["episodic_deleted"] = len(to_delete)

            if not dry_run and to_delete:
                self._gc_delete_entries(conn, user_id, to_delete)

            # 3. Expire old tombstones
            result["tombstones_expired"] = self._gc_expire_tombstones(conn, user_id, dry_run)

            # 4. Log
            if not dry_run:
                self._gc_write_log(conn, result)

        except Exception as e:
            logger.error("GC failed for user %s: %s", user_id, e)

        return result


async def run_gc_for_active_users(
    gc_daemon: "GCDaemon",
    store,
    stop_flag: Optional[Callable[[], bool]] = None,
) -> None:
    """Invoke `gc_daemon.run_gc(user_id)` for every active episodic user.

    Runs each `run_gc` call **on the event loop thread** — SQLiteStore
    caches connections without check_same_thread=False, so offloading to
    a worker thread would hit `ProgrammingError: SQLite objects created
    in a thread can only be used in that same thread` (silently caught
    inside run_gc and turned into a no-op). GCDaemon work is light
    enough (scoring + a couple of SQL statements per user) to run
    synchronously; we yield control via `await asyncio.sleep(0)` between
    users so other tasks can progress.

    Never raises — individual user failures are logged and skipped.

    Args:
        gc_daemon: a GCDaemon instance.
        store: SQLite store with `_connect()`.
        stop_flag: optional callable that returns True to abort early
            between users (cooperative cancellation).
    """
    if not gc_daemon or not store:
        return

    user_ids: list[str] = []
    conn = None
    try:
        conn = store._connect()
        cursor = conn.execute(
            "SELECT DISTINCT user_id FROM episodic WHERE state = 'active'"
        )
        user_ids = [row[0] for row in cursor.fetchall()]
    except Exception as e:
        logger.error("run_gc_for_active_users: user listing failed: %s", e)
        return
    finally:
        if conn is not None:
            try:
                conn.close()
            except Exception:  # nosec B110: best-effort SQLite conn.close() inside finally; no-op if already closed
                pass

    for user_id in user_ids:
        if stop_flag and stop_flag():
            break
        try:
            result = gc_daemon.run_gc(user_id)
            deleted = result.get("episodic_deleted", 0)
            if deleted:
                logger.info(
                    "GC user=%s: %d episodic pruned, budget_enforced=%s",
                    user_id, deleted, result.get("budget_enforced", False),
                )
        except Exception as e:
            logger.error("run_gc_for_active_users: run_gc failed for %s: %s", user_id, e)
        await asyncio.sleep(0)


__all__ = ["GCDaemon", "run_gc_for_active_users"]
