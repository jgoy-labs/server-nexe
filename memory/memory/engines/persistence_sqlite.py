"""
────────────────────────────────────
Server Nexe
Author: Jordi Goy
Location: memory/memory/engines/persistence_sqlite.py
Description: SqliteStorageMixin — SQLite management for PersistenceManager.

Contains all SQLite logic: connection, initialization, migration to SQLCipher,
basic CRUD operations and queries. Used as a mixin for PersistenceManager.

www.jgoy.net · https://server-nexe.org
────────────────────────────────────
"""

import asyncio
import json
import logging
import sqlite3
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

from ..models.memory_entry import MemoryEntry

logger = logging.getLogger(__name__)

# SQLCipher: try to import, fall back to plain sqlite3
# Type as Any so calls remain valid in both branches; runtime guards on
# SQLCIPHER_AVAILABLE protect against accessing methods on None.
sqlcipher: Any
try:
    from sqlcipher3 import dbapi2 as sqlcipher  # type: ignore[no-redef]  # pyright: ignore[reportMissingImports]
    SQLCIPHER_AVAILABLE = True
except ImportError:
    sqlcipher = None
    SQLCIPHER_AVAILABLE = False


class SqliteStorageMixin:
    """
    Mixin with all SQLite logic for PersistenceManager.

    Attributes required by the mixin (defined in PersistenceManager.__init__):
        db_path: Path — path to the SQLite file
        _crypto: cryptography provider (optional)
        _encrypted: bool — whether the DB is encrypted
        executor: ThreadPoolExecutor — for sync operations
    """

    # Mixin contract: PersistenceManager.__init__ assigns these; we declare them
    # only to type mixin accesses (no value: the consumer sets them).
    executor: ThreadPoolExecutor
    db_path: Path
    _crypto: Any  # cryptography provider or None
    _encrypted: bool

    # ── Check helpers ────────────────────────────────────────────────────────

    @staticmethod
    def _is_plaintext_sqlite(path: Path) -> bool:
        """Check if a file is an unencrypted SQLite DB."""
        if not path.exists() or path.stat().st_size == 0:
            return False
        with open(path, "rb") as f:
            header = f.read(16)
        return header == b"SQLite format 3\x00"

    # ── SQLCipher migration ───────────────────────────────────────────────────

    def _migrate_to_encrypted(self):
        """Migrate the existing plain DB to SQLCipher."""
        if not self._crypto or not SQLCIPHER_AVAILABLE:
            return
        if not self.db_path.exists():
            return
        if not self._is_plaintext_sqlite(self.db_path):
            return

        logger.info("Migrating plain SQLite to SQLCipher: %s", self.db_path)
        tmp_path = self.db_path.with_suffix(".db.encrypted")
        try:
            plain_conn = sqlite3.connect(str(self.db_path))
            plain_conn.execute("PRAGMA busy_timeout = 5000")

            enc_conn = sqlcipher.connect(str(tmp_path))
            dek = self._crypto.derive_key("sqlite")
            enc_conn.execute(f"PRAGMA key = \"x'{dek.hex()}'\"")
            enc_conn.execute("PRAGMA cipher_compatibility = 4")
            enc_conn.execute("PRAGMA busy_timeout = 5000")

            for line in plain_conn.iterdump():
                if line.strip() in ("BEGIN TRANSACTION;", "COMMIT;"):
                    continue
                enc_conn.execute(line)
            enc_conn.commit()

            plain_conn.close()
            enc_conn.close()

            for suffix in (".db-wal", ".db-shm"):
                wal_file = self.db_path.with_suffix(suffix)
                if wal_file.exists():
                    wal_file.unlink()

            backup_path = self.db_path.with_suffix(".db.bak")
            self.db_path.rename(backup_path)
            tmp_path.rename(self.db_path)
            logger.info("Migration complete. Backup at %s", backup_path)
        except Exception as e:
            logger.error("SQLCipher migration failed: %s. Keeping plain DB.", e)
            if tmp_path.exists():
                tmp_path.unlink()

    # ── Initialization ────────────────────────────────────────────────────────

    def _quarantine_unreadable_encrypted_db(self) -> bool:
        """F5.6 BUG-NEW-2 — Archive an encrypted DB that won't open with the
        current MASTER_KEY-derived key.

        Returns:
            True when the DB was quarantined (caller should treat the path as
            absent and create a fresh one). False when the DB opens correctly
            or doesn't exist.

        When a previous install left a DB encrypted with a different
        MASTER_KEY, the very first cursor.execute against it raises
        `DatabaseError: file is not a database`. That bubbled up through
        MemoryModule.init and broke the whole memory subsystem on the
        second launch of a freshly-installed DMG. Quarantining keeps the
        file recoverable (rename back if the user restores the previous
        key) while letting the app boot cleanly.
        """
        if not (self._encrypted and SQLCIPHER_AVAILABLE):
            return False
        if not self.db_path.exists() or self.db_path.stat().st_size == 0:
            return False

        # sqlcipher3.dbapi2.DatabaseError is NOT a subclass of sqlite3.DatabaseError
        # (separate exception hierarchy in the C extension), so the except clause
        # must reference the runtime exception class directly.
        db_error_cls = sqlcipher.DatabaseError if SQLCIPHER_AVAILABLE else sqlite3.DatabaseError

        try:
            conn = sqlcipher.connect(str(self.db_path))
            dek = self._crypto.derive_key("sqlite")
            conn.execute(f"PRAGMA key = \"x'{dek.hex()}'\"")
            conn.execute("PRAGMA cipher_compatibility = 4")
            try:
                conn.execute("SELECT 1 FROM sqlite_master LIMIT 1")
            finally:
                conn.close()
            return False
        except db_error_cls as e:
            if "file is not a database" not in str(e).lower():
                raise
            ts = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
            quarantine = self.db_path.with_name(
                f"{self.db_path.name}.unrecoverable-{ts}"
            )
            logger.warning(
                "F5.6 BUG-NEW-2: SQLCipher DB %s cannot be opened with the "
                "current MASTER_KEY (likely a previous install with a "
                "different key). Quarantining to %s and starting fresh. "
                "To recover the data, restore the previous MASTER_KEY and "
                "rename the .unrecoverable-* file back.",
                self.db_path,
                quarantine.name,
            )
            self.db_path.rename(quarantine)
            for suffix in ("-wal", "-shm"):
                sidecar = self.db_path.with_name(self.db_path.name + suffix)
                if sidecar.exists():
                    sidecar.unlink()
            return True

    def _init_sqlite(self):
        """Initialize the SQLite DB with WAL mode."""
        self.db_path.parent.mkdir(parents=True, exist_ok=True)

        if self._crypto and SQLCIPHER_AVAILABLE:
            self._migrate_to_encrypted()
            self._encrypted = True
            self._quarantine_unreadable_encrypted_db()
        elif self._crypto and not SQLCIPHER_AVAILABLE:
            logger.warning(
                "CryptoProvider provided but sqlcipher3 not installed. "
                "Database will NOT be encrypted. Install sqlcipher3 for encryption."
            )

        with self._connect_sqlite() as conn:
            cursor = conn.cursor()
            cursor.execute("PRAGMA journal_mode=WAL")
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS memory_entries (
                    id TEXT PRIMARY KEY,
                    entry_type TEXT NOT NULL,
                    content TEXT NOT NULL,
                    source TEXT NOT NULL,
                    timestamp REAL NOT NULL,
                    ttl_seconds INTEGER,
                    metadata_json TEXT,
                    created_at REAL DEFAULT (julianday('now'))
                )
            """)
            cursor.execute(
                "CREATE INDEX IF NOT EXISTS idx_entry_type ON memory_entries(entry_type)"
            )
            cursor.execute(
                "CREATE INDEX IF NOT EXISTS idx_timestamp ON memory_entries(timestamp DESC)"
            )
            conn.commit()

        logger.info("SQLite initialized (encrypted=%s)", self._encrypted)

    def _connect_sqlite(self):
        """Open SQLite/SQLCipher connection with busy timeout."""
        if self._encrypted and SQLCIPHER_AVAILABLE:
            conn = sqlcipher.connect(str(self.db_path))
            dek = self._crypto.derive_key("sqlite")
            conn.execute(f"PRAGMA key = \"x'{dek.hex()}'\"")
            conn.execute("PRAGMA cipher_compatibility = 4")
        else:
            conn = sqlite3.connect(str(self.db_path))
        conn.execute("PRAGMA busy_timeout = 5000")
        return conn

    # ── CRUD operations ───────────────────────────────────────────────────────

    async def _store_sqlite(self, entry: MemoryEntry):
        """Save a MemoryEntry to SQLite (run_in_executor)."""
        loop = asyncio.get_running_loop()

        def _sync_store():
            with self._connect_sqlite() as conn:
                cursor = conn.cursor()
                metadata_json = json.dumps(entry.metadata) if entry.metadata else None
                unix_timestamp = entry.timestamp.timestamp()
                cursor.execute(
                    """
                    INSERT OR REPLACE INTO memory_entries
                    (id, entry_type, content, source, timestamp, ttl_seconds, metadata_json)
                    VALUES (?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        entry.id,
                        entry.entry_type,
                        entry.content,
                        entry.source,
                        unix_timestamp,
                        entry.ttl_seconds,
                        metadata_json,
                    ),
                )
                conn.commit()

        await loop.run_in_executor(self.executor, _sync_store)
        logger.debug("Stored entry %s to SQLite", entry.id)

    async def _delete_sqlite(self, entry_id: str):
        """Delete an entry from SQLite (rollback helper)."""
        loop = asyncio.get_running_loop()

        def _sync_delete():
            with self._connect_sqlite() as conn:
                cursor = conn.cursor()
                cursor.execute("DELETE FROM memory_entries WHERE id = ?", (entry_id,))
                conn.commit()

        await loop.run_in_executor(self.executor, _sync_delete)
        logger.debug("Deleted entry %s from SQLite (rollback)", entry_id)

    async def get(self, entry_id: str) -> Optional[MemoryEntry]:
        """Retrieve an entry by ID."""
        loop = asyncio.get_running_loop()

        def _sync_get():
            with self._connect_sqlite() as conn:
                cursor = conn.cursor()
                cursor.execute(
                    """
                    SELECT id, entry_type, content, source, timestamp, ttl_seconds, metadata_json
                    FROM memory_entries WHERE id = ?
                    """,
                    (entry_id,),
                )
                row = cursor.fetchone()
            if not row:
                return None
            return self._row_to_entry(row)

        return await loop.run_in_executor(self.executor, _sync_get)

    def _row_to_entry(self, row: tuple) -> MemoryEntry:
        """Convert SQLite row to MemoryEntry."""
        entry_id, entry_type, content, source, timestamp, ttl_seconds, metadata_json = row
        metadata = json.loads(metadata_json) if metadata_json else {}
        return MemoryEntry(
            id=entry_id,
            entry_type=entry_type,
            content=content,
            source=source,
            timestamp=datetime.fromtimestamp(timestamp, tz=timezone.utc),
            ttl_seconds=ttl_seconds,
            metadata=metadata,
        )

    async def get_stats(self) -> Dict[str, int]:
        """DB statistics."""
        loop = asyncio.get_running_loop()

        def _sync_stats():
            conn = self._connect_sqlite()
            cursor = conn.cursor()
            cursor.execute("SELECT COUNT(*) FROM memory_entries")
            total = cursor.fetchone()[0]
            cursor.execute(
                "SELECT COUNT(*) FROM memory_entries WHERE entry_type = 'episodic'"
            )
            episodic = cursor.fetchone()[0]
            cursor.execute(
                "SELECT COUNT(*) FROM memory_entries WHERE entry_type = 'semantic'"
            )
            semantic = cursor.fetchone()[0]
            conn.close()
            return {
                "total_entries": total,
                "episodic_count": episodic,
                "semantic_count": semantic,
            }

        return await loop.run_in_executor(self.executor, _sync_stats)

    async def get_recent(
        self,
        limit: int = 50,
        entry_types: Optional[List[str]] = None,
        exclude_expired: bool = True,
    ) -> List[MemoryEntry]:
        """
        Retrieve the N most recent entries from SQLite.

        Used for preload in RAMContext at boot.
        """
        loop = asyncio.get_running_loop()
        types_filter = entry_types or ["episodic"]
        preload_timeout = getattr(self, "_sqlite_preload_timeout", 10.0)

        def _sync_get_recent():
            conn = self._connect_sqlite()
            cursor = conn.cursor()
            placeholders = ",".join(["?" for _ in types_filter])
            query = f"""
                SELECT id, entry_type, content, source, timestamp, ttl_seconds, metadata_json
                FROM memory_entries
                WHERE entry_type IN ({placeholders})
                ORDER BY timestamp DESC
                LIMIT ?
            """  # nosec B608: dynamic '?' placeholder count for IN clause, all values bound as parameters
            cursor.execute(query, (*types_filter, limit * 2))
            rows = cursor.fetchall()
            conn.close()

            entries = []
            now_ts = datetime.now(timezone.utc).timestamp()

            for row in rows:
                if len(entries) >= limit:
                    break
                entry_id, entry_type, content, source, timestamp, ttl_seconds, metadata_json = row
                if exclude_expired and ttl_seconds:
                    if timestamp + ttl_seconds < now_ts:
                        continue
                metadata = json.loads(metadata_json) if metadata_json else {}
                try:
                    entry_datetime = datetime.fromtimestamp(timestamp, tz=timezone.utc)
                except (ValueError, OSError):
                    entry_datetime = datetime.now(timezone.utc)
                entries.append(
                    MemoryEntry(
                        id=entry_id,
                        entry_type=entry_type,
                        content=content,
                        source=source,
                        timestamp=entry_datetime,
                        ttl_seconds=ttl_seconds,
                        metadata=metadata,
                    )
                )
            return entries

        try:
            entries = await asyncio.wait_for(
                loop.run_in_executor(self.executor, _sync_get_recent),
                timeout=preload_timeout,
            )
            logger.info("Loaded %d recent entries from SQLite", len(entries))
            return entries
        except asyncio.TimeoutError:
            logger.warning(
                "SQLite preload timeout (%.1fs), continuing with empty RAM",
                preload_timeout,
            )
            return []
        except Exception as e:
            logger.warning("SQLite preload failed: %s, continuing with empty RAM", e)
            return []


__all__ = ["SqliteStorageMixin", "SQLCIPHER_AVAILABLE"]
