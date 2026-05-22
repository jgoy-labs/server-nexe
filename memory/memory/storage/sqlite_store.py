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
import sqlite3
import threading
import uuid
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Any, Dict, List, Optional

from .sqlite_migrations import init_db

logger = logging.getLogger(__name__)

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

    def __init__(self, db_path: Path):
        self._db_path = Path(db_path)
        self._db_path.parent.mkdir(parents=True, exist_ok=True)
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
                self._conn = sqlite3.connect(
                    str(self._db_path),
                    check_same_thread=False,
                )
                self._conn.execute("PRAGMA busy_timeout = 5000")
                self._conn.execute("PRAGMA journal_mode=WAL")
                self._conn.execute("PRAGMA foreign_keys = ON")
                self._conn.row_factory = sqlite3.Row
            return self._conn

    def _init_db(self):
        """Create all tables if they don't exist."""
        conn = self._connect()
        init_db(conn)
        logger.info("SQLiteStore initialized at %s", self._db_path)

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


__all__ = ["SQLiteStore"]
