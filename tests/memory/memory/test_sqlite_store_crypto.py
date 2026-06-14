"""
SQLCipher encryption tests for SQLiteStore (D-002).

These exercise the encryption path added so memory_v1.db (the PII source of
truth) is no longer written in clear with NEXE_ENCRYPTION_ENABLED on. Skipped
when sqlcipher3 is not installed.
"""
import os

import pytest

from memory.memory.storage.sqlite_store import SQLCIPHER_AVAILABLE, SQLiteStore

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


class TestSQLiteStoreCrypto:
    def test_encrypted_db_has_no_plaintext_header(self, tmp_path):
        """With a crypto provider the file is real SQLCipher, not plain SQLite."""
        db = tmp_path / "memory_v1.db"
        store = SQLiteStore(db, crypto_provider=_crypto())
        store.upsert_profile("u1", "name", "Jordi")
        store.close()
        assert db.exists()
        assert _header(db) != PLAINTEXT_HEADER
        assert SQLiteStore._is_plaintext_sqlite(db) is False

    def test_round_trip_with_key(self, tmp_path):
        """Reopening with the same provider reads the data back."""
        db = tmp_path / "memory_v1.db"
        crypto = _crypto()
        s1 = SQLiteStore(db, crypto_provider=crypto)
        s1.upsert_profile("u1", "city", "Barcelona")
        s1.close()
        s2 = SQLiteStore(db, crypto_provider=crypto)
        rows = s2.get_profile("u1", "city")
        s2.close()
        assert any('"Barcelona"' in r["value_json"] for r in rows)

    def test_delete_profile_round_trip_encrypted(self, tmp_path):
        """ADR-002 stage 2: delete a structured fact through the encrypted store."""
        db = tmp_path / "memory_v1.db"
        crypto = _crypto()
        s1 = SQLiteStore(db, crypto_provider=crypto)
        s1.upsert_profile("u1", "city", "Barcelona")
        removed = s1.delete_profile("u1", "city")
        s1.close()
        assert removed == 1
        s2 = SQLiteStore(db, crypto_provider=crypto)
        rows = s2.get_profile("u1", "city")
        s2.close()
        assert rows == []

    def test_wrong_key_quarantines_and_starts_fresh(self, tmp_path):
        """A different MASTER_KEY cannot open the DB → quarantine + fresh DB."""
        db = tmp_path / "memory_v1.db"
        s1 = SQLiteStore(db, crypto_provider=_crypto())
        s1.upsert_profile("u1", "x", "y")
        s1.close()
        s2 = SQLiteStore(db, crypto_provider=_crypto())  # different key
        rows = s2.get_profile("u1", "x")
        s2.close()
        assert rows == []
        assert list(db.parent.glob("memory_v1.db.unrecoverable-*"))

    def test_reopen_after_close_reapplies_key(self, tmp_path):
        """DreamingCycle closes the cached conn; the next op must reapply the key
        (else a SQLCipher handle opened without a key fails 'file is not a database')."""
        db = tmp_path / "memory_v1.db"
        store = SQLiteStore(db, crypto_provider=_crypto())
        store.upsert_profile("u1", "a", "1")
        store._conn.close()  # simulate DreamingCycle closing the shared connection
        store.upsert_profile("u1", "b", "2")  # must reconnect + re-key transparently
        rows = store.get_profile("u1")
        store.close()
        assert len(rows) >= 2

    def test_migration_from_plaintext_preserves_data_and_removes_bak(self, tmp_path):
        """An existing plaintext DB is migrated to SQLCipher, data preserved, and
        the plaintext backup removed (Decision B: no PII left in clear)."""
        db = tmp_path / "memory_v1.db"
        plain = SQLiteStore(db)  # no crypto → plaintext
        plain.upsert_profile("u1", "name", "Jordi")
        plain.insert_episodic("u1", "remembers the sea")
        plain.close()
        assert SQLiteStore._is_plaintext_sqlite(db) is True

        enc = SQLiteStore(db, crypto_provider=_crypto())  # auto-migrates
        assert _header(db) != PLAINTEXT_HEADER
        prof = enc.get_profile("u1", "name")
        epis = enc.get_episodic("u1")
        enc.close()
        assert any('"Jordi"' in r["value_json"] for r in prof)
        assert len(epis) == 1
        assert not (db.parent / "memory_v1.db.bak").exists()

    def test_no_crypto_stays_plaintext(self, tmp_path):
        """Without a crypto provider the behaviour is unchanged (plain SQLite)."""
        db = tmp_path / "memory_v1.db"
        store = SQLiteStore(db)
        store.upsert_profile("u1", "x", "y")
        store.close()
        assert SQLiteStore._is_plaintext_sqlite(db) is True
