"""
────────────────────────────────────
Server Nexe
Author: Jordi Goy
Location: memory/memory/api/text_store.py
Description: SQLite text store for document payloads. Keeps text out of Qdrant.

www.jgoy.net · https://server-nexe.org
────────────────────────────────────
"""

import json
import logging
import sqlite3
from pathlib import Path
from typing import Dict, Optional, Any

logger = logging.getLogger(__name__)

# SQLCipher support (optional)
try:
    from sqlcipher3 import dbapi2 as sqlcipher
    SQLCIPHER_AVAILABLE = True
except ImportError:
    sqlcipher = None
    SQLCIPHER_AVAILABLE = False


class TextStore:
    """
    SQLite store for document text and metadata.

    Qdrant stores only vectors + IDs. All text lives here.
    Supports optional encryption via CryptoProvider + SQLCipher.
    """

    def __init__(self, db_path: Path, crypto_provider=None):
        self._db_path = db_path
        self._crypto = crypto_provider
        self._encrypted = False
        self._init_db()

    def _connect(self):
        """Open SQLite/SQLCipher connection."""
        if self._crypto and SQLCIPHER_AVAILABLE:
            conn = sqlcipher.connect(str(self._db_path))
            dek = self._crypto.derive_key("text_store")
            conn.execute(f"PRAGMA key = \"x'{dek.hex()}'\"")
            conn.execute("PRAGMA cipher_compatibility = 4")
            self._encrypted = True
        else:
            conn = sqlite3.connect(str(self._db_path))
        conn.execute("PRAGMA busy_timeout = 5000")
        return conn

    def _init_db(self):
        """Create tables if they don't exist."""
        self._db_path.parent.mkdir(parents=True, exist_ok=True)
        with self._connect() as conn:
            conn.execute("PRAGMA journal_mode=WAL")
            conn.execute("""
                CREATE TABLE IF NOT EXISTS document_texts (
                    doc_id TEXT NOT NULL,
                    collection TEXT NOT NULL,
                    text TEXT NOT NULL,
                    metadata_json TEXT,
                    created_at TEXT,
                    expires_at TEXT,
                    PRIMARY KEY (doc_id, collection)
                )
            """)
            conn.execute("""
                CREATE INDEX IF NOT EXISTS idx_doc_collection
                ON document_texts(collection)
            """)
            conn.commit()

    def put(self, doc_id: str, collection: str, text: str,
            metadata: Optional[Dict[str, Any]] = None,
            created_at: Optional[str] = None,
            expires_at: Optional[str] = None):
        """Store document text."""
        meta_json = json.dumps(metadata) if metadata else None
        with self._connect() as conn:
            conn.execute(
                """INSERT OR REPLACE INTO document_texts
                   (doc_id, collection, text, metadata_json, created_at, expires_at)
                   VALUES (?, ?, ?, ?, ?, ?)""",
                (doc_id, collection, text, meta_json, created_at, expires_at)
            )
            conn.commit()

    def get(self, doc_id: str, collection: str) -> Optional[Dict[str, Any]]:
        """Retrieve document text and metadata."""
        with self._connect() as conn:
            row = conn.execute(
                """SELECT text, metadata_json, created_at, expires_at
                   FROM document_texts WHERE doc_id = ? AND collection = ?""",
                (doc_id, collection)
            ).fetchone()
        if not row:
            return None
        text, meta_json, created_at, expires_at = row
        return {
            "text": text,
            "metadata": json.loads(meta_json) if meta_json else {},
            "created_at": created_at,
            "expires_at": expires_at,
        }

    def get_many(self, doc_ids: list, collection: str) -> Dict[str, Dict[str, Any]]:
        """Retrieve multiple documents by ID."""
        if not doc_ids:
            return {}
        placeholders = ",".join(["?" for _ in doc_ids])
        with self._connect() as conn:
            rows = conn.execute(
                f"""SELECT doc_id, text, metadata_json, created_at, expires_at
                    FROM document_texts
                    WHERE doc_id IN ({placeholders}) AND collection = ?""",
                (*doc_ids, collection)
            ).fetchall()
        result = {}
        for doc_id, text, meta_json, created_at, expires_at in rows:
            result[doc_id] = {
                "text": text,
                "metadata": json.loads(meta_json) if meta_json else {},
                "created_at": created_at,
                "expires_at": expires_at,
            }
        return result

    def delete(self, doc_id: str, collection: str) -> bool:
        """Delete document text."""
        with self._connect() as conn:
            cursor = conn.execute(
                "DELETE FROM document_texts WHERE doc_id = ? AND collection = ?",
                (doc_id, collection)
            )
            conn.commit()
            return cursor.rowcount > 0

    def delete_collection(self, collection: str) -> int:
        """Delete all texts in a collection."""
        with self._connect() as conn:
            cursor = conn.execute(
                "DELETE FROM document_texts WHERE collection = ?",
                (collection,)
            )
            conn.commit()
            return cursor.rowcount

    def close(self):
        """No-op (connections are opened/closed per operation)."""
        pass
