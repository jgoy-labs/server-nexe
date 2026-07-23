"""
WS3-03 — SQLiteStore fails CLOSED under NEXE_ENCRYPTION_ENABLED=true.

When the user explicitly demanded encryption, a failed plaintext->SQLCipher
migration must refuse to open the PII in plaintext (parity with the keys.py
wrong-length policy, WS3-02). In 'auto' mode the plaintext fallback with a
loud error log remains the accepted design.

Skipped when sqlcipher3 is not installed.
"""
import os

import pytest

from core.config import encryption_is_mandatory
from memory.memory.storage.sqlite_store import SQLCIPHER_AVAILABLE, SQLiteStore

pytestmark = pytest.mark.skipif(
    not SQLCIPHER_AVAILABLE, reason="sqlcipher3 not installed"
)


def _crypto():
    from core.crypto.provider import CryptoProvider
    return CryptoProvider(master_key=os.urandom(32))


def _make_plaintext_db(tmp_path):
    db = tmp_path / "memory_v1.db"
    plain = SQLiteStore(db)
    plain.upsert_profile("u1", "name", "StayEncrypted")
    plain.close()
    assert SQLiteStore._is_plaintext_sqlite(db) is True
    return db


def _break_migration(monkeypatch):
    """Make the plaintext->SQLCipher migration a no-op that leaves the file
    plaintext — the exact post-failure state WS3-03 is about."""
    monkeypatch.setattr(SQLiteStore, "_migrate_to_encrypted", lambda self: None)


class TestRequireEncryptionFailClosed:
    def test_mandatory_mode_refuses_plaintext_after_failed_migration(
        self, tmp_path, monkeypatch
    ):
        db = _make_plaintext_db(tmp_path)
        _break_migration(monkeypatch)

        with pytest.raises(RuntimeError, match="Refusing to open PII in plaintext"):
            SQLiteStore(db, crypto_provider=_crypto(), require_encryption=True)

        # The plaintext file is the user's only copy: it must remain intact.
        assert db.exists()
        assert SQLiteStore._is_plaintext_sqlite(db) is True

    def test_auto_mode_keeps_the_documented_plaintext_fallback(
        self, tmp_path, monkeypatch
    ):
        db = _make_plaintext_db(tmp_path)
        _break_migration(monkeypatch)

        store = SQLiteStore(db, crypto_provider=_crypto())  # require_encryption=False
        try:
            assert store._encrypted is False
            import json
            entries = store.get_profile("u1", "name")
            assert entries and json.loads(entries[0]["value_json"]) == "StayEncrypted"
        finally:
            store.close()

    def test_mandatory_mode_with_successful_migration_opens_encrypted(self, tmp_path):
        db = _make_plaintext_db(tmp_path)

        store = SQLiteStore(db, crypto_provider=_crypto(), require_encryption=True)
        try:
            assert store._encrypted is True
            assert SQLiteStore._is_plaintext_sqlite(db) is False
        finally:
            store.close()


class TestEncryptionIsMandatory:
    @pytest.mark.parametrize("value,expected", [
        ("true", True),
        ("TRUE", True),
        (" true ", True),
        ("auto", False),
        ("", False),
        ("false", False),
        ("garbage", False),
        ("1", False),  # same closed vocabulary as _resolve_encryption_enabled
    ])
    def test_normalization(self, value, expected):
        assert encryption_is_mandatory(value) is expected
