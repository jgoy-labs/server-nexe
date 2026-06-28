"""
SQLCipher encryption tests for TextStore (B188).

TextStore opened the document text DB with a direct PRAGMA key and no fallback,
unlike its siblings (sqlite_store.py, persistence_sqlite.py) which migrate a
plaintext DB to SQLCipher and quarantine a DB that no longer opens with the
current MASTER_KEY. A leftover plaintext text_store.db (or one encrypted with an
old key) raised "file is not a database" on __init__ → persistent document-RAG
death on every boot. These exercise the migration + quarantine path.

Skipped when sqlcipher3 is not installed.
"""
import logging
import os
from pathlib import Path

import pytest

from memory.memory.api.text_store import SQLCIPHER_AVAILABLE, TextStore

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


class TestTextStoreCrypto:
    def test_encrypted_db_has_no_plaintext_header(self, tmp_path):
        """Scenario A — with a crypto provider the file is real SQLCipher."""
        db = tmp_path / "text_store.db"
        store = TextStore(db, crypto_provider=_crypto())
        store.put("d1", "c1", "hello")
        store.close()
        assert db.exists()
        assert _header(db) != PLAINTEXT_HEADER
        assert TextStore._is_plaintext_sqlite(db) is False

    def test_round_trip_with_key(self, tmp_path):
        """Scenario B — reopening with the same provider reads the data back.

        Guards the namespace trap: if migration/connection used a different
        derive_key purpose than the one that encrypted, this would fail.
        """
        db = tmp_path / "text_store.db"
        crypto = _crypto()
        s1 = TextStore(db, crypto_provider=crypto)
        s1.put("d", "c", "Barcelona")
        s1.close()
        s2 = TextStore(db, crypto_provider=crypto)
        doc = s2.get("d", "c")
        s2.close()
        assert doc is not None
        assert doc["text"] == "Barcelona"

    def test_migration_from_plaintext_preserves_data_and_removes_bak(self, tmp_path):
        """Scenario C — the original bug: a plaintext DB auto-migrates, reads
        back, and the plaintext backup is removed (Decision B)."""
        db = tmp_path / "text_store.db"
        plain = TextStore(db)  # no crypto → plaintext
        plain.put("d", "c", "Hola")
        plain.close()
        assert TextStore._is_plaintext_sqlite(db) is True

        enc = TextStore(db, crypto_provider=_crypto())  # auto-migrates
        assert _header(db) != PLAINTEXT_HEADER
        doc = enc.get("d", "c")
        enc.close()
        assert doc is not None
        assert doc["text"] == "Hola"
        assert not (db.parent / (db.name + ".bak")).exists()

    def test_migration_itself_removes_plaintext_bak(self, tmp_path, monkeypatch):
        """Scenario C (isolated) — _migrate_to_encrypted itself drops the plaintext
        .bak (Decision B), independent of the _sweep_plaintext_leftovers safety
        net. The sweep is patched to a no-op so this assertion pins the migration
        path's own unlink (else a leaked .bak would only be caught by the sweep,
        masking a regression in the migration code)."""
        db = tmp_path / "text_store.db"
        plain = TextStore(db)
        plain.put("d", "c", "Hola")
        plain.close()
        assert TextStore._is_plaintext_sqlite(db) is True

        monkeypatch.setattr(
            TextStore, "_sweep_plaintext_leftovers", lambda self: None
        )
        enc = TextStore(db, crypto_provider=_crypto())  # migrates, sweep disabled
        doc = enc.get("d", "c")
        enc.close()
        assert doc is not None and doc["text"] == "Hola"
        assert not (db.parent / (db.name + ".bak")).exists()

    def test_wrong_key_quarantines_and_starts_fresh(self, tmp_path):
        """Scenario D — a different MASTER_KEY cannot open the DB → quarantine
        + fresh DB instead of crashing __init__."""
        db = tmp_path / "text_store.db"
        s1 = TextStore(db, crypto_provider=_crypto())
        s1.put("d", "c", "secret")
        s1.close()
        s2 = TextStore(db, crypto_provider=_crypto())  # different key
        doc = s2.get("d", "c")
        s2.close()
        assert doc is None
        assert list(db.parent.glob(db.name + ".unrecoverable-*"))

    def test_no_crypto_stays_plaintext(self, tmp_path):
        """Scenario E — without a crypto provider behaviour is unchanged."""
        db = tmp_path / "text_store.db"
        store = TextStore(db)
        store.put("d", "c", "plain")
        store.close()
        assert TextStore._is_plaintext_sqlite(db) is True

    def test_post_migration_round_trip_same_key(self, tmp_path):
        """Scenario F — after migrating with key K, reopening with K reads the
        data. Explicit assert that the derive_key used at migration == the one
        used at _connect (closes the 'migrate with wrong namespace → illegible'
        risk the swarm flagged)."""
        db = tmp_path / "text_store.db"
        plain = TextStore(db)
        plain.put("d", "c", "Girona")
        plain.close()
        assert TextStore._is_plaintext_sqlite(db) is True

        crypto = _crypto()
        enc = TextStore(db, crypto_provider=crypto)  # migrates with key K
        assert enc.get("d", "c")["text"] == "Girona"
        enc.close()

        # Reopen with the SAME crypto instance: migration key must equal connect key.
        again = TextStore(db, crypto_provider=crypto)
        doc = again.get("d", "c")
        again.close()
        assert doc is not None
        assert doc["text"] == "Girona"
        assert _header(db) != PLAINTEXT_HEADER


class TestTextStoreCryptoDataLoss:
    """Onada 2 (B188) — three data-loss / crash holes on error paths.

    Each test reproduces the loss/crash with the pre-fix code (RED) and pins the
    post-fix recovery behaviour.
    """

    def test_connect_honours_encrypted_flag_not_just_crypto(self, tmp_path):
        """#3 (regression) — _connect must branch on self._encrypted, not on
        self._crypto. After a legitimately failed migration the live file is
        left in plaintext with _encrypted=False; _connect branching on _crypto
        opens it as SQLCipher → 'file is not a database' crash. The siblings
        branch on _encrypted (sqlite_store.py:124, persistence_sqlite.py:246)."""
        db = tmp_path / "text_store.db"
        # A genuine plaintext SQLite DB with data (no crypto → plaintext).
        plain = TextStore(db)
        plain.put("d", "c", "PlaintextSurvivor")
        plain.close()
        assert TextStore._is_plaintext_sqlite(db) is True

        # Build the post-failed-migration state by hand WITHOUT going through
        # __init__ (which would migrate): crypto present, file plaintext on disk,
        # _encrypted=False (what _init_db sets when migration leaves plaintext).
        store = TextStore.__new__(TextStore)
        store._db_path = db
        store._crypto = _crypto()
        store._encrypted = False

        # Pre-fix: _connect branches on self._crypto → opens plaintext as
        # SQLCipher → DatabaseError 'file is not a database'. Post-fix: honours
        # _encrypted=False → plain sqlite3 connection that reads the data.
        with __import__("contextlib").closing(store._connect()) as conn:
            row = conn.execute(
                "SELECT text FROM document_texts WHERE doc_id='d' AND collection='c'"
            ).fetchone()
        assert row is not None
        assert row[0] == "PlaintextSurvivor"

    def test_no_sqlcipher_with_crypto_warns_at_init_b079(self, tmp_path, monkeypatch, caplog):
        """B079 — a CryptoProvider supplied while sqlcipher3 is unavailable must
        WARN at init that the DB will NOT be encrypted (parity with the sibling
        stores). The warning lives in _init_db (added by B188); this pins it so a
        refactor can't silently drop it. A per-_connect warning is deliberately
        avoided: _connect runs once per operation and would only spam the same
        condition the init warning already reports once."""
        monkeypatch.setattr("memory.memory.api.text_store.SQLCIPHER_AVAILABLE", False)
        db = tmp_path / "text_store.db"
        with caplog.at_level(logging.WARNING, logger="memory.memory.api.text_store"):
            store = TextStore(db, crypto_provider=_crypto())
            store.close()
        assert any(
            "NOT be encrypted" in r.message and r.levelname == "WARNING"
            for r in caplog.records
        ), [(r.levelname, r.message) for r in caplog.records]

    def test_migrate_second_rename_failure_rolls_back_to_plaintext(
        self, tmp_path, monkeypatch
    ):
        """#1 (rollback) — if the tmp->live rename fails after live->.bak
        succeeded, the pre-fix except unlinks the only encrypted copy AND leaves
        the live path absent → total loss. Post-fix the except restores the .bak
        to the live path (plaintext rollback) so the data survives."""
        db = tmp_path / "text_store.db"
        plain = TextStore(db)
        plain.put("d", "c", "RollbackMe")
        plain.close()
        assert TextStore._is_plaintext_sqlite(db) is True

        backup_path = db.with_name(db.name + ".bak")
        real_rename = Path.rename

        def flaky_rename(self, target):
            # Fail only on the second rename: tmp(.encrypted) -> live(text_store.db).
            if Path(self).name.endswith(".encrypted") and Path(target) == db:
                raise OSError("simulated disk failure on tmp->live rename")
            return real_rename(self, target)

        monkeypatch.setattr(Path, "rename", flaky_rename)

        enc = TextStore(db, crypto_provider=_crypto())  # migration hits the failure
        monkeypatch.undo()  # restore rename so the assertions can reopen cleanly

        # Post-fix: live path restored from .bak (plaintext), data readable.
        # The .bak (sole copy) must NOT have been unlinked into oblivion.
        assert db.exists(), "live DB must exist (rolled back from .bak)"
        doc = enc.get("d", "c")
        assert doc is not None, "data lost: rollback did not restore the DB"
        assert doc["text"] == "RollbackMe"

    def test_sweep_keeps_bak_when_live_db_absent(self, tmp_path):
        """#2 (guard) — a SIGKILL between the live->.bak and tmp->live renames
        leaves {live ABSENT, .bak plaintext with data, .encrypted orphan}. The
        pre-fix boot marks _encrypted=True (live file absent falls in the else)
        and the sweep deletes the .bak → the sole surviving copy is destroyed.
        Post-fix: with no verified live encrypted DB the .bak is preserved."""
        db = tmp_path / "text_store.db"
        bak = db.with_name(db.name + ".bak")
        enc_orphan = db.with_name(db.name + ".encrypted")

        # Build a plaintext DB then move it to the .bak slot (live path absent).
        tmp_seed = tmp_path / "seed.db"
        seed = TextStore(tmp_seed)
        seed.put("d", "c", "CrashWindowData")
        seed.close()
        assert TextStore._is_plaintext_sqlite(tmp_seed) is True
        tmp_seed.rename(bak)
        bak.chmod(0o600)
        # An orphan .encrypted left mid-migration (truthy size, not a valid DB).
        enc_orphan.write_bytes(b"\x00" * 64)

        assert not db.exists()
        assert bak.exists() and TextStore._is_plaintext_sqlite(bak)

        # Boot. Pre-fix: _encrypted=True blindly + sweep unlinks the .bak.
        store = TextStore(db, crypto_provider=_crypto())
        store.close()

        # Post-fix: no verified live encrypted DB → .bak preserved for recovery.
        assert bak.exists(), "data lost: crash-window plaintext .bak was swept"
        assert TextStore._is_plaintext_sqlite(bak)
