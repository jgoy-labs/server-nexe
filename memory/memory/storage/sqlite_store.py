"""
------------------------------------
Server Nexe
Author: Jordi Goy
Location: memory/memory/storage/sqlite_store.py
Description: SQLite storage backend — source of truth for all memory data.

www.jgoy.net · https://server-nexe.org
------------------------------------
"""

import functools
import hashlib
import json
import logging
import os
import sqlite3
import threading
import uuid
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Any, Dict, List, Optional

from .sqlite_migrations import init_db

logger = logging.getLogger(__name__)

# SQLCipher: try to import, fall back to plain sqlite3 (mirror of
# engines/persistence_sqlite.py). Typed as Any so calls type-check in both
# branches; runtime guards on SQLCIPHER_AVAILABLE protect against None.
sqlcipher: Any
try:
    from sqlcipher3 import dbapi2 as sqlcipher  # type: ignore[no-redef]  # pyright: ignore[reportMissingImports]
    SQLCIPHER_AVAILABLE = True
except ImportError:
    sqlcipher = None
    SQLCIPHER_AVAILABLE = False

VALID_TABLES = frozenset({
    "profile", "profile_history", "episodic", "staging",
    "tombstones", "memory_events", "gc_log", "attribute_aliases",
    "memory_index", "user_activity",
})


def _validate_table(table: str) -> str:
    """Validate table name against whitelist to prevent SQL injection."""
    if table not in VALID_TABLES:
        raise ValueError(f"Invalid table name: {table}")
    return table


def _with_lock(method):
    """Serialise calls on ``self._lock`` so the cached sqlite3.Connection is
    not used concurrently from multiple threads. The lock is reentrant, so a
    method that already holds it can safely call into another decorated
    method (e.g. ``_init_db`` -> ``_connect``).

    Performance note: this serialises both writes AND reads. SQLite WAL mode
    would normally allow concurrent reads on separate connections, but the
    cached single connection cannot be used from multiple threads without
    Python-level synchronisation regardless of the underlying DB engine. For
    server-nexe (mono-usuari local) the throughput cost is negligible. If a
    future multi-user fork needs concurrent reads it should either switch
    to per-call connections (option B in the audit) or to a read-write
    lock (e.g. ``readerwriterlock.rwlock``)."""
    @functools.wraps(method)
    def wrapper(self, *args, **kwargs):
        with self._lock:
            return method(self, *args, **kwargs)
    return wrapper


class SQLiteStore:
    """
    SQLite storage backend for the memory system.

    All SQL uses parameterized queries (?) — NEVER f-strings.
    WAL mode for concurrent reads.
    user_id is mandatory on all tables from day 1.
    """

    def __init__(self, db_path: Path, crypto_provider: Any = None):
        self._db_path = Path(db_path)
        # mode= is modulated by the umask → explicit chmod to guarantee 0o700 on
        # the dir holding PII (parity with engines/persistence_sqlite.py).
        self._db_path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        os.chmod(self._db_path.parent, 0o700)
        self._crypto = crypto_provider
        self._encrypted = False
        self._conn: Optional[sqlite3.Connection] = None
        # Reentrant so that an operation can call _connect() under the lock
        # and then call into a helper that also takes the lock without
        # deadlocking. The lock serialises writers (which SQLite already
        # forces single-writer anyway) and protects the cached connection
        # so that concurrent threads do not race on the ``self._conn is None``
        # check or interleave SELECT/INSERT pairs in upsert_profile.
        self._lock = threading.RLock()
        self._init_db()

    def _connect(self) -> sqlite3.Connection:
        """Get or create connection.

        Thread-safe: the cached connection is opened with
        ``check_same_thread=False`` and all public methods serialise on
        ``self._lock`` (an RLock), so a single ``sqlite3.Connection`` can
        be shared safely across asyncio worker threads.

        DreamingCycle (and any other caller) closes the connection it obtains
        here after each operation. When that happens ``self._conn`` still
        holds a reference to the now-closed object, so the ``is None`` guard
        would return the stale connection. We detect this by attempting a
        lightweight no-op and discarding on failure.
        """
        with self._lock:
            if self._conn is not None:
                try:
                    self._conn.execute("SELECT 1")
                except Exception:
                    # Connection is closed or broken — discard and reconnect.
                    self._conn = None

            if self._conn is None:
                if self._encrypted and SQLCIPHER_AVAILABLE:
                    # Re-apply the key on EVERY (re)open: DreamingCycle closes the
                    # cached connection after each cycle, and a SQLCipher handle
                    # opened without the key fails with "file is not a database".
                    # PRAGMA key must run first, before any other statement.
                    self._conn = sqlcipher.connect(
                        str(self._db_path),
                        check_same_thread=False,
                    )
                    dek = self._crypto.derive_key("sqlite")
                    self._conn.execute(f"PRAGMA key = \"x'{dek.hex()}'\"")  # nosemgrep: formatted-sql-query,sqlalchemy-execute-raw-query — SQLCipher key directive; dek is an internal crypto key
                    self._conn.execute("PRAGMA cipher_compatibility = 4")
                else:
                    self._conn = sqlite3.connect(
                        str(self._db_path),
                        check_same_thread=False,
                    )
                self._conn.execute("PRAGMA busy_timeout = 5000")
                self._conn.execute("PRAGMA journal_mode=WAL")
                self._conn.execute("PRAGMA foreign_keys = ON")
                self._conn.row_factory = (
                    sqlcipher.Row
                    if (self._encrypted and SQLCIPHER_AVAILABLE)
                    else sqlite3.Row
                )
            return self._conn

    def _init_db(self):
        """Create all tables if they don't exist.

        When a crypto provider is present, migrate any plaintext DB to SQLCipher
        and quarantine an encrypted DB that no longer opens with the current key
        BEFORE opening the connection (parity with SqliteStorageMixin._init_sqlite).
        """
        if self._crypto and SQLCIPHER_AVAILABLE:
            self._migrate_to_encrypted()
            # A failed migration leaves the file plaintext: only treat the DB as
            # encrypted if it genuinely is now. Marking a still-plaintext file as
            # encrypted would make _quarantine rename the plaintext PII to
            # .unrecoverable-* (data loss + PII left in clear).
            if self._db_path.exists() and self._is_plaintext_sqlite(self._db_path):
                self._encrypted = False
                logger.error(
                    "memory_v1.db remains plaintext after migration; opening in "
                    "plaintext mode. PII is NOT encrypted — check sqlcipher3 and disk space."
                )
            else:
                self._encrypted = True
                self._quarantine_unreadable_encrypted_db()
            self._sweep_plaintext_leftovers()
        elif self._crypto and not SQLCIPHER_AVAILABLE:
            logger.warning(
                "CryptoProvider provided but sqlcipher3 not installed. "
                "memory_v1.db will NOT be encrypted. Install sqlcipher3 for encryption."
            )
        conn = self._connect()
        init_db(conn)
        logger.info(
            "SQLiteStore initialized at %s (encrypted=%s)",
            self._db_path, self._encrypted,
        )

    # ── SQLCipher migration / quarantine (parity with SqliteStorageMixin) ──

    @staticmethod
    def _is_plaintext_sqlite(path: Path) -> bool:
        """Check if a file is an unencrypted SQLite DB (plaintext header)."""
        if not path.exists() or path.stat().st_size == 0:
            return False
        with open(path, "rb") as f:
            header = f.read(16)
        return header == b"SQLite format 3\x00"

    @staticmethod
    def _table_row_counts(conn) -> Dict[str, int]:
        """Row count per user table — used to verify a migration lost no data."""
        cur = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' "
            "AND name NOT LIKE 'sqlite_%'"
        )
        counts: Dict[str, int] = {}
        for (name,) in cur.fetchall():
            counts[name] = conn.execute(
                f'SELECT COUNT(*) FROM "{name}"'  # nosec B608: name from sqlite_master, not user input
            ).fetchone()[0]
        return counts

    def _migrate_to_encrypted(self) -> None:
        """Migrate an existing plaintext DB to SQLCipher, in place.

        Verifies the encrypted copy opens and preserves every table's row count
        before swapping it in, then removes the plaintext backup (Decision B:
        leaving memory_v1.db.bak in clear would keep open the stolen-device hole
        this change closes). On any failure the plaintext DB is left untouched.
        """
        if not self._crypto or not SQLCIPHER_AVAILABLE:
            return
        if not self._is_plaintext_sqlite(self._db_path):
            return

        logger.info("Migrating plain SQLite to SQLCipher: %s", self._db_path)
        tmp_path = self._db_path.with_name(self._db_path.name + ".encrypted")
        if tmp_path.exists():
            # Discard a partial .encrypted left by a prior crashed migration so we
            # always start from a clean target (else iterdump's CREATE TABLE would
            # collide with the stale tables).
            tmp_path.unlink()
        try:
            plain_conn = sqlite3.connect(str(self._db_path))
            plain_conn.execute("PRAGMA busy_timeout = 5000")

            enc_conn = sqlcipher.connect(str(tmp_path))
            dek = self._crypto.derive_key("sqlite")
            enc_conn.execute(f"PRAGMA key = \"x'{dek.hex()}'\"")  # nosemgrep: formatted-sql-query,sqlalchemy-execute-raw-query — SQLCipher key directive; dek is an internal crypto key
            enc_conn.execute("PRAGMA cipher_compatibility = 4")
            enc_conn.execute("PRAGMA busy_timeout = 5000")

            for line in plain_conn.iterdump():
                if line.strip() in ("BEGIN TRANSACTION;", "COMMIT;"):
                    continue
                enc_conn.execute(line)
            enc_conn.commit()

            # Verify no data was lost before destroying the plaintext.
            plain_counts = self._table_row_counts(plain_conn)
            enc_counts = self._table_row_counts(enc_conn)
            plain_conn.close()
            enc_conn.close()
            if plain_counts != enc_counts:
                raise RuntimeError(
                    f"row-count mismatch after migration: {plain_counts} != {enc_counts}"
                )

            for suffix in ("-wal", "-shm"):
                sidecar = self._db_path.with_name(self._db_path.name + suffix)
                if sidecar.exists():
                    sidecar.unlink()

            backup_path = self._db_path.with_name(self._db_path.name + ".bak")
            self._db_path.rename(backup_path)
            backup_path.chmod(0o600)
            tmp_path.rename(self._db_path)
            # Decision B: encrypted copy verified in place → drop the plaintext PII.
            backup_path.unlink()
            logger.info("Migration complete and verified; plaintext backup removed.")
        except Exception as e:
            logger.error("SQLCipher migration failed: %s. Keeping plain DB.", e)
            if tmp_path.exists():
                tmp_path.unlink()

    def _quarantine_unreadable_encrypted_db(self) -> bool:
        """Archive an encrypted DB that won't open with the current key.

        A DB left by a previous install with a different MASTER_KEY raises
        "file is not a database" on first use and would break the whole memory
        subsystem; quarantining keeps it recoverable while letting the app boot.
        """
        if not (self._encrypted and SQLCIPHER_AVAILABLE):
            return False
        if not self._db_path.exists() or self._db_path.stat().st_size == 0:
            return False

        db_error_cls = (
            sqlcipher.DatabaseError if SQLCIPHER_AVAILABLE else sqlite3.DatabaseError
        )
        try:
            conn = sqlcipher.connect(str(self._db_path))
            dek = self._crypto.derive_key("sqlite")
            conn.execute(f"PRAGMA key = \"x'{dek.hex()}'\"")  # nosemgrep: formatted-sql-query,sqlalchemy-execute-raw-query — SQLCipher key directive; dek is an internal crypto key
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
            quarantine = self._db_path.with_name(
                f"{self._db_path.name}.unrecoverable-{ts}"
            )
            logger.warning(
                "SQLCipher DB %s cannot be opened with the current MASTER_KEY "
                "(likely a previous install with a different key). Quarantining "
                "to %s and starting fresh.",
                self._db_path, quarantine.name,
            )
            self._db_path.rename(quarantine)
            for suffix in ("-wal", "-shm"):
                sidecar = self._db_path.with_name(self._db_path.name + suffix)
                if sidecar.exists():
                    sidecar.unlink()
            return True

    def _sweep_plaintext_leftovers(self) -> None:
        """Remove a stale plaintext .bak left by a crash mid-migration.

        _migrate_to_encrypted renames the plaintext DB to <db>.bak and unlinks it
        only after swapping in the encrypted copy; a SIGKILL/power-cut in that
        window leaves a plaintext .bak with all the PII, which nothing else would
        ever clean (the second boot sees an already-encrypted DB and skips
        migration). Once the live DB is encrypted, that .bak is pure leak with no
        recovery value → delete it.
        """
        if not self._encrypted:
            return
        bak = self._db_path.with_name(self._db_path.name + ".bak")
        try:
            if bak.exists() and self._is_plaintext_sqlite(bak):
                bak.unlink()
                logger.warning(
                    "Removed orphan plaintext backup %s (crash-window leftover).",
                    bak.name,
                )
        except OSError as e:  # nosec B110: best-effort cleanup
            logger.debug("Could not sweep plaintext leftover %s: %s", bak, e)

    # ── Profile CRUD ──

    @_with_lock
    def upsert_profile(
        self,
        user_id: str,
        attribute: str,
        value: Any,
        entity: str = "user",
        source: str = "heuristic",
        trust_level: str = "untrusted",
        is_critical: bool = False,
    ) -> str:
        """Upsert a profile attribute. Returns the profile entry ID."""
        conn = self._connect()
        now = datetime.now(timezone.utc).isoformat()
        value_json = json.dumps(value)
        entry_id = hashlib.sha256(
            f"{user_id}:{entity}:{attribute}".encode()
        ).hexdigest()[:16]

        # Check existing
        cursor = conn.execute(
            "SELECT id, value_json FROM profile "
            "WHERE user_id = ? AND entity = ? AND attribute = ?",
            (user_id, entity, attribute),
        )
        existing = cursor.fetchone()

        if existing:
            old_value = existing["value_json"]
            # Log history
            conn.execute(
                "INSERT INTO profile_history "
                "(profile_id, old_value_json, new_value_json, source, reason) "
                "VALUES (?, ?, ?, ?, ?)",
                (existing["id"], old_value, value_json, source, "upsert"),
            )
            # Update
            conn.execute(
                "UPDATE profile SET value_json = ?, last_seen_at = ?, "
                "last_confirmed_at = ?, source = ?, trust_level = ?, "
                "is_critical = ?, evidence_count = evidence_count + 1 "
                "WHERE id = ?",
                (value_json, now, now, source, trust_level, is_critical, existing["id"]),
            )
            entry_id = existing["id"]
        else:
            conn.execute(
                "INSERT INTO profile "
                "(id, user_id, entity, attribute, value_json, "
                "first_seen_at, last_seen_at, last_confirmed_at, "
                "source, trust_level, is_critical) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (entry_id, user_id, entity, attribute, value_json,
                 now, now, now, source, trust_level, is_critical),
            )

        conn.commit()
        return entry_id

    @_with_lock
    def get_profile(
        self, user_id: str, attribute: Optional[str] = None
    ) -> List[Dict[str, Any]]:
        """Get profile entries for a user."""
        conn = self._connect()
        if attribute:
            cursor = conn.execute(
                "SELECT * FROM profile "
                "WHERE user_id = ? AND attribute = ? AND state = ?",
                (user_id, attribute, "active"),
            )
        else:
            cursor = conn.execute(
                "SELECT * FROM profile WHERE user_id = ? AND state = ?",
                (user_id, "active"),
            )
        return [dict(row) for row in cursor.fetchall()]

    @_with_lock
    def delete_profile(
        self, user_id: str, attribute: str, entity: str = "user"
    ) -> int:
        """Hard-delete a profile attribute and its history. Returns rows removed.

        ADR-002: single-user local memory uses hard-delete (no tombstones) — when
        the user says "forget X" and confirms, the fact is removed outright, and
        a subsequent recall can never surface it.
        """
        conn = self._connect()
        conn.execute(
            "DELETE FROM profile_history WHERE profile_id IN "
            "(SELECT id FROM profile WHERE user_id = ? AND entity = ? AND attribute = ?)",
            (user_id, entity, attribute),
        )
        cursor = conn.execute(
            "DELETE FROM profile WHERE user_id = ? AND entity = ? AND attribute = ?",
            (user_id, entity, attribute),
        )
        conn.commit()
        return cursor.rowcount

    # ── Episodic CRUD ──

    @_with_lock
    def insert_episodic(
        self,
        user_id: str,
        content: str,
        memory_type: str = "fact",
        importance: float = 0.5,
        source: str = "heuristic",
        trust_level: str = "untrusted",
        namespace: str = "default",
        metadata: Optional[Dict] = None,
        related_ids: Optional[List[str]] = None,
    ) -> str:
        """Insert a new episodic entry. Returns entry ID."""
        conn = self._connect()
        now = datetime.now(timezone.utc).isoformat()
        content_hash = hashlib.sha256(
            content.lower().strip().encode()
        ).hexdigest()
        entry_id = str(uuid.uuid4())[:16]

        conn.execute(
            "INSERT INTO episodic "
            "(id, user_id, content, content_hash, metadata_json, "
            "namespace, memory_type, importance, created_at, updated_at, "
            "source, trust_level, related_ids) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                entry_id, user_id, content, content_hash,
                json.dumps(metadata or {}), namespace, memory_type,
                importance, now, now, source, trust_level,
                json.dumps(related_ids or []),
            ),
        )
        conn.commit()
        return entry_id

    @_with_lock
    def get_episodic(
        self,
        user_id: str,
        limit: int = 50,
        namespace: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        """Get episodic entries for a user."""
        conn = self._connect()
        if namespace:
            cursor = conn.execute(
                "SELECT * FROM episodic "
                "WHERE user_id = ? AND namespace = ? AND state = ? "
                "ORDER BY created_at DESC LIMIT ?",
                (user_id, namespace, "active", limit),
            )
        else:
            cursor = conn.execute(
                "SELECT * FROM episodic "
                "WHERE user_id = ? AND state = ? "
                "ORDER BY created_at DESC LIMIT ?",
                (user_id, "active", limit),
            )
        return [dict(row) for row in cursor.fetchall()]

    # ── Staging CRUD ──

    @_with_lock
    def insert_staging(
        self,
        user_id: str,
        raw_text: str,
        extractor_output: Optional[Dict] = None,
        gate_score: float = 0.0,
        validator_score: float = 0.0,
        validator_decision: str = "stage_only",
        decision_reason: str = "",
        source: str = "user_message",
        trust_level: str = "untrusted",
        namespace: str = "default",
        target_store: Optional[str] = None,
    ) -> str:
        """Insert into staging buffer. Returns entry ID."""
        conn = self._connect()
        now = datetime.now(timezone.utc)
        content_hash = hashlib.sha256(
            raw_text.lower().strip().encode()
        ).hexdigest()
        entry_id = str(uuid.uuid4())[:16]
        expires_at = (now + timedelta(hours=48)).isoformat()

        conn.execute(
            "INSERT INTO staging "
            "(id, user_id, raw_text, extractor_output_json, gate_score, "
            "validator_score, validator_decision, decision_reason, "
            "content_hash, source, namespace, trust_level, "
            "created_at, expires_at, target_store) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                entry_id, user_id, raw_text,
                json.dumps(extractor_output) if extractor_output else None,
                gate_score, validator_score, validator_decision,
                decision_reason, content_hash, source, namespace,
                trust_level, now.isoformat(), expires_at, target_store,
            ),
        )
        conn.commit()
        return entry_id

    @_with_lock
    def get_staging(
        self,
        user_id: str,
        status: str = "pending",
        limit: int = 50,
    ) -> List[Dict[str, Any]]:
        """Get staging entries for a user."""
        conn = self._connect()
        cursor = conn.execute(
            "SELECT * FROM staging "
            "WHERE user_id = ? AND status = ? "
            "ORDER BY created_at ASC LIMIT ?",
            (user_id, status, limit),
        )
        return [dict(row) for row in cursor.fetchall()]

    # ── Tombstones ──

    @_with_lock
    def add_tombstone(
        self,
        user_id: str,
        content_hash: str,
        reason: str = "user_forget",
        entity: Optional[str] = None,
        attribute: Optional[str] = None,
        ttl_days: int = 90,
    ) -> None:
        """Add a tombstone to prevent zombie re-insertion."""
        conn = self._connect()
        now = datetime.now(timezone.utc)
        expires_at = (now + timedelta(days=ttl_days)).isoformat()
        canonical_key = None
        if entity and attribute:
            canonical_key = f"{entity}/{attribute}"

        conn.execute(
            "INSERT INTO tombstones "
            "(user_id, content_hash, canonical_key, entity, attribute, "
            "expires_at, reason) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            (user_id, content_hash, canonical_key, entity, attribute,
             expires_at, reason),
        )
        conn.commit()

    @_with_lock
    def is_tombstoned(self, user_id: str, content_hash: str) -> bool:
        """Check if content is tombstoned."""
        conn = self._connect()
        cursor = conn.execute(
            "SELECT 1 FROM tombstones "
            "WHERE user_id = ? AND content_hash = ? "
            "AND (expires_at IS NULL OR expires_at > ?)",
            (user_id, content_hash, datetime.now(timezone.utc).isoformat()),
        )
        return cursor.fetchone() is not None

    # ── Stats ──

    @_with_lock
    def get_stats(self, user_id: str) -> Dict[str, int]:
        """Get memory statistics for a user."""
        conn = self._connect()

        def _count(table: str) -> int:
            safe_table = _validate_table(table)
            sql = f"SELECT COUNT(*) FROM {safe_table} WHERE user_id = ?"  # nosec B608: safe_table comes from VALID_TABLES frozenset whitelist, not user input
            cursor = conn.execute(sql, (user_id,))
            return cursor.fetchone()[0]

        return {
            "profile_count": _count("profile"),
            "episodic_count": _count("episodic"),
            "staging_count": _count("staging"),
            "tombstone_count": _count("tombstones"),
        }

    # ── Cleanup ──

    @_with_lock
    def close(self):
        """Close the database connection."""
        if self._conn:
            self._conn.close()
            self._conn = None

    @_with_lock
    def get_tables(self) -> List[str]:
        """List all tables in the database."""
        conn = self._connect()
        cursor = conn.execute(
            "SELECT name FROM sqlite_master WHERE type = ? ORDER BY name",
            ("table",),
        )
        return [row["name"] for row in cursor.fetchall()]


__all__ = ["SQLiteStore", "SQLCIPHER_AVAILABLE"]
