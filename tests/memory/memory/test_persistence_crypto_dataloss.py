"""
SQLCipher data-loss tests for SqliteStorageMixin / persistence_sqlite (B248).

The persistence engine carries the same plaintext->SQLCipher migration pattern.
It has NO sweep (so no .bak-sweep hole), but two real risks remain on error
paths:

  #1 rollback: if the tmp->live rename fails after live->.bak succeeded, the
     except left the live path absent and the .bak as the only copy without
     restoring it (non-atomic migration).

  #6 _init_sqlite alignment: _init_sqlite forced ``self._encrypted = True``
     UNCONDITIONALLY after migration. A migration that legitimately leaves the
     file plaintext (or a rollback that restored the plaintext .bak) was then
     flagged encrypted, and _quarantine_unreadable_encrypted_db moved the
     plaintext PII to .unrecoverable-* → the rollback was useless. Aligned with
     sqlite_store._init_db: decide _encrypted from the real file state.

These run against REAL SQLCipher (CryptoProvider with a real master key).
Skipped when sqlcipher3 is not installed.
"""
import os
import sqlite3
from pathlib import Path

import pytest

from memory.memory.engines.persistence_sqlite import (
    SQLCIPHER_AVAILABLE,
    SqliteStorageMixin,
)

pytestmark = pytest.mark.skipif(
    not SQLCIPHER_AVAILABLE, reason="sqlcipher3 not installed"
)

PLAINTEXT_HEADER = b"SQLite format 3\x00"


def _crypto():
    from core.crypto.provider import CryptoProvider
    return CryptoProvider(master_key=os.urandom(32))


def _header(path):
    with open(path, "rb") as f:
        return f.read(16)


class _Store(SqliteStorageMixin):
    """Minimal concrete carrier exposing the mixin methods under test, without
    spinning up Qdrant or a ThreadPoolExecutor."""

    def __init__(self, db_path: Path, crypto=None):
        self.db_path = Path(db_path)
        self._crypto = crypto
        self._encrypted = False


def _seed_plaintext(path: Path, value: str) -> None:
    # Schema matches SqliteStorageMixin._init_sqlite so the no-regression test
    # (which runs the full _init_sqlite, including CREATE INDEX idx_entry_type)
    # does not trip over a column mismatch.
    conn = sqlite3.connect(str(path))
    conn.execute(
        """
        CREATE TABLE memory_entries (
            id TEXT PRIMARY KEY,
            entry_type TEXT NOT NULL,
            content TEXT NOT NULL,
            source TEXT NOT NULL,
            timestamp REAL NOT NULL,
            ttl_seconds INTEGER,
            metadata_json TEXT,
            created_at REAL DEFAULT (julianday('now'))
        )
        """
    )
    conn.execute(
        "INSERT INTO memory_entries (id, entry_type, content, source, timestamp) "
        "VALUES (?, ?, ?, ?, ?)",
        ("e1", "episodic", value, "test", 0.0),
    )
    conn.commit()
    conn.close()


class TestPersistenceCryptoDataLoss:
    def test_migrate_second_rename_failure_rolls_back_to_plaintext(
        self, tmp_path, monkeypatch
    ):
        """#1 (rollback) — tmp->live rename fails after live->.bak succeeded.
        Pre-fix: live path absent, .bak unlinked (.db.bak) is NOT touched but the
        live DB is never restored and _init_sqlite would then quarantine it.
        Here we exercise _migrate directly: post-fix the except restores the .bak
        to the live path (plaintext rollback) and sets _encrypted=False."""
        db = tmp_path / "memory.db"
        _seed_plaintext(db, "RollbackMe")
        assert SqliteStorageMixin._is_plaintext_sqlite(db) is True

        store = _Store(db, crypto=_crypto())
        store._encrypted = True  # _init_sqlite would set this; mimic that state

        real_rename = Path.rename

        def flaky_rename(self, target):
            # persistence uses with_suffix(".db.encrypted") for the tmp file.
            if Path(self).name.endswith(".db.encrypted") and Path(target) == db:
                raise OSError("simulated disk failure on tmp->live rename")
            return real_rename(self, target)

        monkeypatch.setattr(Path, "rename", flaky_rename)
        store._migrate_to_encrypted()
        monkeypatch.undo()

        # Post-fix: live restored from .bak, plaintext, data readable.
        assert db.exists(), "live DB must exist (rolled back from .bak)"
        assert store._encrypted is False, "rollback must flag plaintext"
        conn = sqlite3.connect(str(db))
        row = conn.execute(
            "SELECT content FROM memory_entries WHERE id='e1'"
        ).fetchone()
        conn.close()
        assert row is not None, "data lost: rollback did not restore the DB"
        assert row[0] == "RollbackMe"

    def test_init_sqlite_conditional_keeps_plaintext_readable_after_failed_migration(
        self, tmp_path, monkeypatch
    ):
        """#6 (VITAL) — a failed migration that leaves the file in plaintext must
        result in _encrypted=False so _connect_sqlite opens it in PLAIN mode (no
        'file is not a database' crash, no quarantine of the cleartext PII).

        Pre-fix _init_sqlite forced _encrypted=True unconditionally, then
        _quarantine renamed the plaintext live DB to .unrecoverable-* → data gone
        and PII left in clear in an orphan file. Post-fix: _init_sqlite decides
        _encrypted from the real on-disk state, exactly like sqlite_store."""
        db = tmp_path / "memory.db"
        _seed_plaintext(db, "PlaintextSurvivor")
        assert SqliteStorageMixin._is_plaintext_sqlite(db) is True

        store = _Store(db, crypto=_crypto())

        # Force the tmp->live rename to fail so the migration leaves the file
        # plaintext (rollback restores the .bak to the live path in plaintext).
        real_rename = Path.rename

        def flaky_rename(self, target):
            if Path(self).name.endswith(".db.encrypted") and Path(target) == db:
                raise OSError("simulated disk failure on tmp->live rename")
            return real_rename(self, target)

        monkeypatch.setattr(Path, "rename", flaky_rename)
        store._init_sqlite()
        monkeypatch.undo()

        # Post-fix: the file is still plaintext on disk → _encrypted must be False
        # and _connect_sqlite must open it as plain sqlite3 and read the data.
        assert SqliteStorageMixin._is_plaintext_sqlite(db) is True
        assert store._encrypted is False, (
            "_init_sqlite must NOT force _encrypted=True when the live file is "
            "still plaintext (else _connect_sqlite crashes / quarantine eats PII)"
        )
        # No quarantine of the cleartext live DB.
        assert not list(db.parent.glob(db.name + ".unrecoverable-*"))
        conn = store._connect_sqlite()
        try:
            row = conn.execute(
                "SELECT content FROM memory_entries WHERE id='e1'"
            ).fetchone()
        finally:
            conn.close()
        assert row is not None and row[0] == "PlaintextSurvivor"

    def test_init_sqlite_normal_migration_encrypts_and_reads_back(self, tmp_path):
        """No-regression — a normal migration (no induced failure) encrypts the
        DB, sets _encrypted=True, removes the plaintext .bak, and reads back."""
        db = tmp_path / "memory.db"
        _seed_plaintext(db, "Girona")
        crypto = _crypto()
        store = _Store(db, crypto=crypto)
        store._init_sqlite()

        assert store._encrypted is True
        assert _header(db) != PLAINTEXT_HEADER
        assert not db.with_suffix(".db.bak").exists()
        conn = store._connect_sqlite()
        try:
            row = conn.execute(
                "SELECT content FROM memory_entries WHERE id='e1'"
            ).fetchone()
        finally:
            conn.close()
        assert row is not None and row[0] == "Girona"

    def test_failed_migration_recovers_on_next_boot(self, tmp_path, monkeypatch):
        """Recovery CYCLE — the first _init_sqlite fails its migration (rollback
        to plaintext, _encrypted=False, readable), and a second _init_sqlite with
        no failure migrates to encrypted with the data intact. Without the
        rollback + #6 alignment, boot 1 loses the live DB and boot 2 starts empty."""
        db = tmp_path / "memory.db"
        _seed_plaintext(db, "RecoverPersist")
        crypto = _crypto()

        real_rename = Path.rename
        calls = {"n": 0}

        def flaky_rename(self, target):
            if Path(self).name.endswith(".db.encrypted") and Path(target) == db:
                calls["n"] += 1
                if calls["n"] == 1:
                    raise OSError("simulated failure on first migration only")
            return real_rename(self, target)

        monkeypatch.setattr(Path, "rename", flaky_rename)

        # Boot 1: migration fails -> rollback to plaintext, readable.
        boot1 = _Store(db, crypto=crypto)
        boot1._init_sqlite()
        assert SqliteStorageMixin._is_plaintext_sqlite(db) is True, "boot 1 must roll back to plaintext"
        assert boot1._encrypted is False
        conn = boot1._connect_sqlite()
        try:
            row = conn.execute("SELECT content FROM memory_entries WHERE id='e1'").fetchone()
        finally:
            conn.close()
        assert row is not None and row[0] == "RecoverPersist", "data lost after failed migration"

        # Boot 2: rename works -> migrates to encrypted, data intact.
        boot2 = _Store(db, crypto=crypto)
        boot2._init_sqlite()
        monkeypatch.undo()
        assert boot2._encrypted is True, "boot 2 must migrate to encrypted"
        assert _header(db) != PLAINTEXT_HEADER
        conn = boot2._connect_sqlite()
        try:
            row = conn.execute("SELECT content FROM memory_entries WHERE id='e1'").fetchone()
        finally:
            conn.close()
        assert row is not None and row[0] == "RecoverPersist", "data lost in recovery cycle"

    def test_init_sqlite_keeps_bak_when_live_db_absent(self, tmp_path):
        """Regression guard (AI audit B248 review) — post-crash state {live ABSENT,
        .bak plaintext with data}. persistence has NO sweep, so _init_sqlite must
        keep the .bak (sole copy) and create a fresh encrypted live DB. Pins this
        behaviour so a sweep added here in the future can't silently destroy the
        only copy (parity with sqlite_store::test_sweep_keeps_bak_when_live_db_absent)."""
        db = tmp_path / "memory.db"
        bak = db.with_suffix(".db.bak")

        # Plaintext .bak with data; live path absent.
        _seed_plaintext(bak, "CrashWindowPersist")
        bak.chmod(0o600)
        assert not db.exists()
        assert SqliteStorageMixin._is_plaintext_sqlite(bak)

        store = _Store(db, crypto=_crypto())
        store._init_sqlite()

        # .bak (sole copy) preserved for recovery; a fresh live DB is created.
        assert bak.exists(), "data lost: crash-window .bak destroyed by _init_sqlite"
        assert SqliteStorageMixin._is_plaintext_sqlite(bak)
        assert db.exists(), "live DB must be (re)created"
