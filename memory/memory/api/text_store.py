"""
────────────────────────────────────
Server Nexe
Author: Jordi Goy
Location: memory/memory/api/text_store.py
Description: SQLite text store for document payloads. Keeps text out of Qdrant.

www.jgoy.net · https://server-nexe.org
────────────────────────────────────
"""

import contextlib
import json
import logging
import os
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, Optional, Any

logger = logging.getLogger(__name__)

# SQLCipher support (optional). Typed as Any so runtime branches stay valid;
# the SQLCIPHER_AVAILABLE flag guards against None access.
sqlcipher: Any
try:
    from sqlcipher3 import dbapi2 as sqlcipher  # type: ignore[no-redef]  # pyright: ignore[reportMissingImports]
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
        """Open SQLite/SQLCipher connection.

        MC-008: callers must wrap with contextlib.closing() — a bare
        ``with conn:`` only manages the transaction, it never calls close(),
        and every operation leaked one SQLite/SQLCipher connection.
        """
        # B188 #3: branch on self._encrypted, NOT self._crypto — parity with
        # sqlite_store.py:124 / persistence_sqlite.py:246. A legitimately failed
        # migration leaves the live file plaintext with _encrypted=False; opening
        # it as SQLCipher would raise "file is not a database" and crash boot.
        if self._encrypted and SQLCIPHER_AVAILABLE:
            conn = sqlcipher.connect(str(self._db_path))
            dek = self._crypto.derive_key("text_store")
            conn.execute(f"PRAGMA key = \"x'{dek.hex()}'\"")  # nosemgrep: formatted-sql-query,sqlalchemy-execute-raw-query — SQLCipher key directive; dek is internal crypto key, never user input
            conn.execute("PRAGMA cipher_compatibility = 4")
        else:
            conn = sqlite3.connect(str(self._db_path))
        conn.execute("PRAGMA busy_timeout = 5000")
        return conn

    def _init_db(self):
        """Create tables if they don't exist.

        When a crypto provider is present, migrate any plaintext text_store.db to
        SQLCipher and quarantine an encrypted DB that no longer opens with the
        current key BEFORE opening the connection (parity with
        SQLiteStore._init_db / SqliteStorageMixin._init_sqlite). Without this a
        leftover plaintext DB (old install) or one encrypted with an old
        MASTER_KEY raised "file is not a database" → document-RAG dead on boot.
        """
        # mode= is modulated by the umask → explicit chmod to guarantee 0o700
        # (same pattern as sqlite_store.py:85-88 and persistence_sqlite.py:206-207)
        self._db_path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        os.chmod(self._db_path.parent, 0o700)
        if self._crypto and SQLCIPHER_AVAILABLE:
            self._migrate_to_encrypted()
            # A failed migration leaves the file plaintext: only treat the DB as
            # encrypted if it genuinely is now. Marking a still-plaintext file as
            # encrypted would make _quarantine rename the plaintext PII to
            # .unrecoverable-* (data loss + PII left in clear).
            if self._db_path.exists() and self._is_plaintext_sqlite(self._db_path):
                self._encrypted = False
                logger.error(
                    "text_store.db remains plaintext after migration; opening in "
                    "plaintext mode. Text is NOT encrypted — check sqlcipher3 and disk space."
                )
            elif not self._db_path.exists():
                # B188 #2(b): no live file. This is either a brand-new install or
                # an anomalous post-crash state (live DB lost between the two
                # migration renames, with a plaintext .bak as the sole copy). Do
                # NOT blindly mark _encrypted=True and run the destructive sweep
                # against a non-existent live DB — that would delete the .bak. A
                # fresh encrypted DB is created below by _connect/CREATE TABLE.
                self._encrypted = True
            else:
                self._encrypted = True
                self._quarantine_unreadable_encrypted_db()
                self._sweep_plaintext_leftovers()
        elif self._crypto and not SQLCIPHER_AVAILABLE:
            logger.warning(
                "CryptoProvider provided but sqlcipher3 not installed. "
                "text_store.db will NOT be encrypted. Install sqlcipher3 for encryption."
            )
        with contextlib.closing(self._connect()) as conn:
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

    # ── SQLCipher migration / quarantine (parity with sqlite_store.py) ──
    #
    # NAMESPACE: TextStore derives derive_key("text_store") everywhere (the
    # siblings use "sqlite"). Migration and connection MUST use the same purpose
    # or the migrated DB would be illegible (encrypt with one key, open with
    # another). See B188.

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
        """Migrate an existing plaintext text_store.db to SQLCipher, in place.

        Verifies the encrypted copy opens and preserves every table's row count
        before swapping it in, then removes the plaintext backup (Decision B: a
        text_store.db.bak in clear would keep the document PII readable on a
        stolen device). On any failure the plaintext DB is left untouched.
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
        plain_conn = None
        enc_conn = None
        try:
            plain_conn = sqlite3.connect(str(self._db_path))
            plain_conn.execute("PRAGMA busy_timeout = 5000")

            enc_conn = sqlcipher.connect(str(tmp_path))
            dek = self._crypto.derive_key("text_store")
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
            plain_conn = None
            enc_conn.close()
            enc_conn = None
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
            # B188 #1: rollback. If we already renamed the plaintext live DB to
            # .bak and the tmp->live swap then failed, the live path is absent and
            # backup_path holds the ONLY copy. Restore it (plaintext rollback)
            # before propagating so we never end up with no live DB. Only unlink
            # the encrypted tmp once the live DB is safely back (it is no longer
            # the sole copy then).
            backup_path = self._db_path.with_name(self._db_path.name + ".bak")
            if not self._db_path.exists() and backup_path.exists():
                backup_path.rename(self._db_path)
                self._encrypted = False
                logger.error(
                    "Rolled back to plaintext live DB from %s after migration "
                    "failure; text is NOT encrypted.", backup_path.name,
                )
            if tmp_path.exists() and self._db_path.exists():
                tmp_path.unlink()
        finally:
            # MC-010: always close both connections so handles (and the tmp WAL)
            # are released on every path; a leaked handle can block tmp cleanup
            # (notably on Windows). Parity with persistence_sqlite.py (MEM-004).
            if plain_conn is not None:
                try:
                    plain_conn.close()
                except Exception as close_err:
                    logger.debug("plain_conn close failed: %s", close_err)
            if enc_conn is not None:
                try:
                    enc_conn.close()
                except Exception as close_err:
                    logger.debug("enc_conn close failed: %s", close_err)

    def _quarantine_unreadable_encrypted_db(self) -> bool:
        """Archive an encrypted DB that won't open with the current key.

        A DB left by a previous install with a different MASTER_KEY raises
        "file is not a database" on first use and would break document RAG;
        quarantining keeps it recoverable while letting the app boot.
        """
        if not (self._encrypted and SQLCIPHER_AVAILABLE):
            return False
        if not self._db_path.exists() or self._db_path.stat().st_size == 0:
            return False

        db_error_cls = (
            sqlcipher.DatabaseError if SQLCIPHER_AVAILABLE else sqlite3.DatabaseError
        )
        conn = None
        try:
            conn = sqlcipher.connect(str(self._db_path))
            dek = self._crypto.derive_key("text_store")
            conn.execute(f"PRAGMA key = \"x'{dek.hex()}'\"")  # nosemgrep: formatted-sql-query,sqlalchemy-execute-raw-query — SQLCipher key directive; dek is an internal crypto key
            conn.execute("PRAGMA cipher_compatibility = 4")
            conn.execute("SELECT 1 FROM sqlite_master LIMIT 1")
            return False
        except db_error_cls as e:
            if "file is not a database" not in str(e).lower():
                raise
            # MC-012: close the handle BEFORE renaming — Windows refuses to
            # rename a file held open, and the fd must not leak on this path.
            if conn is not None:
                conn.close()
                conn = None
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
        finally:
            if conn is not None:
                conn.close()

    def _sweep_plaintext_leftovers(self) -> None:
        """Remove a stale plaintext .bak left by a crash mid-migration.

        _migrate_to_encrypted renames the plaintext DB to <db>.bak and unlinks it
        only after swapping in the encrypted copy; a SIGKILL/power-cut in that
        window leaves a plaintext .bak with all the text, which nothing else
        would ever clean (the second boot sees an already-encrypted DB and skips
        migration). Once the live DB is encrypted, that .bak is pure leak with no
        recovery value → delete it.
        """
        if not self._encrypted:
            return
        bak = self._db_path.with_name(self._db_path.name + ".bak")
        try:
            if not (bak.exists() and self._is_plaintext_sqlite(bak)):
                return
            # B188 #2: only delete the plaintext .bak once the LIVE encrypted DB
            # is proven readable with the current key. A SIGKILL between the two
            # migration renames can leave {live absent, .bak = sole plaintext
            # copy}; without this check the sweep would destroy the only copy.
            if not self._live_encrypted_db_verified():
                logger.warning(
                    "Plaintext backup %s kept: no verified live encrypted DB "
                    "(possible crash-window leftover — preserving for recovery).",
                    bak.name,
                )
                return
            bak.unlink()
            logger.warning(
                "Removed orphan plaintext backup %s (crash-window leftover).",
                bak.name,
            )
        except OSError as e:  # nosec B110: best-effort cleanup
            logger.debug("Could not sweep plaintext leftover %s: %s", bak, e)

    def _live_encrypted_db_verified(self) -> bool:
        """True only if the live DB exists and opens with the current key.

        Used to gate the destructive .bak sweep: we must never delete the
        plaintext backup unless a usable encrypted live DB is confirmed.
        """
        if not (self._encrypted and SQLCIPHER_AVAILABLE):
            return False
        if not self._db_path.exists() or self._db_path.stat().st_size == 0:
            return False
        conn = None
        try:
            conn = sqlcipher.connect(str(self._db_path))
            dek = self._crypto.derive_key("text_store")
            conn.execute(f"PRAGMA key = \"x'{dek.hex()}'\"")  # nosemgrep: formatted-sql-query,sqlalchemy-execute-raw-query — SQLCipher key directive; dek is an internal crypto key
            conn.execute("PRAGMA cipher_compatibility = 4")
            conn.execute("SELECT 1 FROM sqlite_master LIMIT 1")
            return True
        except Exception:  # nosec B110: verification probe, any failure = unverified
            return False
        finally:
            if conn is not None:
                conn.close()

    def put(self, doc_id: str, collection: str, text: str,
            metadata: Optional[Dict[str, Any]] = None,
            created_at: Optional[str] = None,
            expires_at: Optional[str] = None):
        """Store document text."""
        meta_json = json.dumps(metadata) if metadata else None
        with contextlib.closing(self._connect()) as conn:
            conn.execute(
                """INSERT OR REPLACE INTO document_texts
                   (doc_id, collection, text, metadata_json, created_at, expires_at)
                   VALUES (?, ?, ?, ?, ?, ?)""",
                (doc_id, collection, text, meta_json, created_at, expires_at)
            )
            conn.commit()

    def get(self, doc_id: str, collection: str) -> Optional[Dict[str, Any]]:
        """Retrieve document text and metadata."""
        with contextlib.closing(self._connect()) as conn:
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
        sql = f"SELECT doc_id, text, metadata_json, created_at, expires_at FROM document_texts WHERE doc_id IN ({placeholders}) AND collection = ?"  # nosec B608: dynamic '?' placeholder count for IN clause, all values bound as parameters
        with contextlib.closing(self._connect()) as conn:
            rows = conn.execute(sql, (*doc_ids, collection)).fetchall()  # nosemgrep: sqlalchemy-execute-raw-query — sql uses '?' placeholders, all params bound
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
        with contextlib.closing(self._connect()) as conn:
            cursor = conn.execute(
                "DELETE FROM document_texts WHERE doc_id = ? AND collection = ?",
                (doc_id, collection)
            )
            conn.commit()
            return cursor.rowcount > 0

    def delete_collection(self, collection: str) -> int:
        """Delete all texts in a collection."""
        with contextlib.closing(self._connect()) as conn:
            cursor = conn.execute(
                "DELETE FROM document_texts WHERE collection = ?",
                (collection,)
            )
            conn.commit()
            return cursor.rowcount

    def close(self):
        """No-op (connections are opened/closed per operation)."""
        pass
