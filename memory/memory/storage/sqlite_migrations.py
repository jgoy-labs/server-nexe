"""
------------------------------------
Server Nexe
Author: Jordi Goy
Location: memory/memory/storage/sqlite_migrations.py
Description: SQLite schema creation and migrations.

www.jgoy.net · https://server-nexe.org
------------------------------------
"""

import logging
import sqlite3

logger = logging.getLogger(__name__)


def init_db(conn: sqlite3.Connection) -> None:
    """Create all tables and indexes if they don't exist."""
    cursor = conn.cursor()

    # Profile Store (EAV with closed schema)
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS profile (
            id TEXT PRIMARY KEY,
            user_id TEXT NOT NULL,
            entity TEXT NOT NULL DEFAULT 'user',
            attribute TEXT NOT NULL,
            value_json TEXT NOT NULL,
            evidence_count INTEGER DEFAULT 1,
            first_seen_at TIMESTAMP,
            last_seen_at TIMESTAMP,
            last_confirmed_at TIMESTAMP,
            source TEXT,
            trust_level TEXT NOT NULL DEFAULT 'untrusted',
            is_critical BOOLEAN DEFAULT FALSE,
            state TEXT DEFAULT 'active',
            schema_version TEXT DEFAULT '1.0',
            UNIQUE(user_id, entity, attribute)
        )
    """)

    # Profile history
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS profile_history (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            profile_id TEXT NOT NULL REFERENCES profile(id),
            old_value_json TEXT,
            new_value_json TEXT,
            changed_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            source TEXT,
            reason TEXT
        )
    """)

    # Episodic Store
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS episodic (
            id TEXT PRIMARY KEY,
            user_id TEXT NOT NULL,
            content TEXT NOT NULL,
            content_hash TEXT,
            metadata_json TEXT DEFAULT '{}',
            namespace TEXT DEFAULT 'default',
            memory_type TEXT,
            importance REAL DEFAULT 0.5,
            current_relevance REAL,
            evidence_count INTEGER DEFAULT 1,
            access_count INTEGER DEFAULT 0,
            last_accessed TIMESTAMP,
            created_at TIMESTAMP,
            updated_at TIMESTAMP,
            expires_at TIMESTAMP,
            source TEXT,
            source_ref TEXT,
            trust_level TEXT NOT NULL DEFAULT 'untrusted',
            state TEXT DEFAULT 'active',
            vector_synced BOOLEAN DEFAULT FALSE,
            embedding_model TEXT,
            schema_version TEXT DEFAULT '1.0',
            related_ids TEXT DEFAULT '[]'
        )
    """)

    # Staging buffer
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS staging (
            id TEXT PRIMARY KEY,
            user_id TEXT NOT NULL,
            raw_text TEXT NOT NULL,
            extractor_output_json TEXT,
            gate_score REAL,
            validator_score REAL,
            validator_decision TEXT,
            decision_reason TEXT,
            content_hash TEXT,
            source TEXT,
            source_ref TEXT,
            namespace TEXT DEFAULT 'default',
            trust_level TEXT NOT NULL DEFAULT 'untrusted',
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            expires_at TIMESTAMP,
            status TEXT DEFAULT 'pending',
            leased_at TIMESTAMP,
            worker_id TEXT,
            retry_count INTEGER DEFAULT 0,
            target_store TEXT
        )
    """)

    # Tombstones
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS tombstones (
            user_id TEXT NOT NULL,
            content_hash TEXT NOT NULL,
            canonical_key TEXT,
            entity TEXT,
            attribute TEXT,
            deleted_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            expires_at TIMESTAMP,
            reason TEXT
        )
    """)

    # Audit log
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS memory_events (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id TEXT NOT NULL,
            entry_id TEXT,
            entry_store TEXT,
            action TEXT NOT NULL,
            actor TEXT,
            before_json TEXT,
            after_json TEXT,
            reason TEXT,
            timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            expires_at TIMESTAMP
        )
    """)

    # Alias mappings
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS attribute_aliases (
            raw_key TEXT PRIMARY KEY,
            canonical_key TEXT NOT NULL,
            hit_count INTEGER DEFAULT 1
        )
    """)

    # GC log
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS gc_log (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            run_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            profile_scanned INTEGER,
            profile_deleted INTEGER,
            episodic_scanned INTEGER,
            episodic_deleted INTEGER,
            staging_purged INTEGER,
            tombstones_expired INTEGER,
            reconciliation_fixes INTEGER,
            duration_ms INTEGER
        )
    """)

    # User activity
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS user_activity (
            user_id TEXT NOT NULL,
            activity_date DATE NOT NULL,
            session_count INTEGER DEFAULT 1,
            PRIMARY KEY (user_id, activity_date)
        )
    """)

    # Indexes
    cursor.execute("""
        CREATE INDEX IF NOT EXISTS idx_profile_user
        ON profile(user_id, state)
    """)
    cursor.execute("""
        CREATE INDEX IF NOT EXISTS idx_episodic_namespace
        ON episodic(namespace, state)
    """)
    cursor.execute("""
        CREATE INDEX IF NOT EXISTS idx_episodic_user_ns
        ON episodic(user_id, namespace, state)
    """)
    cursor.execute("""
        CREATE INDEX IF NOT EXISTS idx_staging_pending
        ON staging(user_id, namespace, status, created_at)
    """)
    cursor.execute("""
        CREATE INDEX IF NOT EXISTS idx_tombstones_hash
        ON tombstones(user_id, content_hash)
    """)
    cursor.execute("""
        CREATE INDEX IF NOT EXISTS idx_events_entry
        ON memory_events(user_id, entry_id, timestamp)
    """)

    conn.commit()
    logger.info("SQLite schema initialized")


__all__ = ["init_db"]
