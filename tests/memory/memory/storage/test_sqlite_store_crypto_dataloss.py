"""
SQLCipher data-loss tests for SQLiteStore (B248).

SQLiteStore carries the SAME plaintext->SQLCipher migration pattern that
text_store.py had before B188, with the same data-loss holes on error paths:
the migration except destroyed the only copy, and the sweep deleted the
plaintext .bak when the live file was absent (post-crash). This mirrors
tests/memory/memory/api/test_text_store_crypto.py::TestTextStoreCryptoDataLoss
for the production memory store (namespace "sqlite", memory_v1.db / profile).

Skipped when sqlcipher3 is not installed.
"""
import os
from pathlib import Path

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


class TestSQLiteStoreCryptoDataLoss:
    """Onada 2 (B248) — two data-loss holes on error paths + safety nets.

    Each test reproduces the loss/crash with the pre-fix code (RED) and pins
    the post-fix recovery behaviour.
    """

    def test_migrate_second_rename_failure_rolls_back_to_plaintext(
        self, tmp_path, monkeypatch
    ):
        """#1 (rollback) — if the tmp->live rename fails after live->.bak
        succeeded, the pre-fix except unlinks the only encrypted copy AND leaves
        the live path absent → total loss. Post-fix the except restores the .bak
        to the live path (plaintext rollback) so the data survives."""
        db = tmp_path / "memory_v1.db"
        plain = SQLiteStore(db)
        plain.upsert_profile("u1", "name", "RollbackMe")
        plain.close()
        assert SQLiteStore._is_plaintext_sqlite(db) is True

        real_rename = Path.rename

        def flaky_rename(self, target):
            # Fail only on the second rename: tmp(.encrypted) -> live(memory_v1.db).
            if Path(self).name.endswith(".encrypted") and Path(target) == db:
                raise OSError("simulated disk failure on tmp->live rename")
            return real_rename(self, target)

        monkeypatch.setattr(Path, "rename", flaky_rename)

        enc = SQLiteStore(db, crypto_provider=_crypto())  # migration hits failure
        monkeypatch.undo()  # restore rename so the assertions can reopen cleanly

        # Post-fix: live path restored from .bak (plaintext), data readable.
        # The .bak (sole copy) must NOT have been unlinked into oblivion.
        assert db.exists(), "live DB must exist (rolled back from .bak)"
        rows = enc.get_profile("u1", "name")
        enc.close()
        assert rows, "data lost: rollback did not restore the DB"
        assert any('"RollbackMe"' in r["value_json"] for r in rows)

    def test_sweep_keeps_bak_when_live_db_absent(self, tmp_path):
        """#2 (guard) — a SIGKILL between the live->.bak and tmp->live renames
        leaves {live ABSENT, .bak plaintext with data, .encrypted orphan}. The
        pre-fix boot marks _encrypted=True (live file absent falls in the else)
        and the sweep deletes the .bak → the sole surviving copy is destroyed.
        Post-fix: with no verified live encrypted DB the .bak is preserved."""
        db = tmp_path / "memory_v1.db"
        bak = db.with_name(db.name + ".bak")
        enc_orphan = db.with_name(db.name + ".encrypted")

        # Build a plaintext DB then move it to the .bak slot (live path absent).
        tmp_seed = tmp_path / "seed.db"
        seed = SQLiteStore(tmp_seed)
        seed.upsert_profile("u1", "name", "CrashWindowData")
        seed.close()
        assert SQLiteStore._is_plaintext_sqlite(tmp_seed) is True
        tmp_seed.rename(bak)
        bak.chmod(0o600)
        # An orphan .encrypted left mid-migration (truthy size, not a valid DB).
        enc_orphan.write_bytes(b"\x00" * 64)

        assert not db.exists()
        assert bak.exists() and SQLiteStore._is_plaintext_sqlite(bak)

        # Boot. Pre-fix: _encrypted=True blindly + sweep unlinks the .bak.
        store = SQLiteStore(db, crypto_provider=_crypto())
        store.close()

        # Post-fix: no verified live encrypted DB → .bak preserved for recovery.
        assert bak.exists(), "data lost: crash-window plaintext .bak was swept"
        assert SQLiteStore._is_plaintext_sqlite(bak)

    def test_migration_ok_still_removes_bak_no_perpetual_pii(self, tmp_path):
        """No-regression — a normal migration with a verified live encrypted DB
        STILL removes the plaintext .bak (Decision B). The hardened sweep guard
        must not leave the .bak forever = perpetual cleartext PII leak."""
        db = tmp_path / "memory_v1.db"
        plain = SQLiteStore(db)
        plain.upsert_profile("u1", "name", "Jordi")
        plain.insert_episodic("u1", "remembers the sea")
        plain.close()
        assert SQLiteStore._is_plaintext_sqlite(db) is True

        enc = SQLiteStore(db, crypto_provider=_crypto())  # auto-migrates
        assert _header(db) != PLAINTEXT_HEADER
        prof = enc.get_profile("u1", "name")
        enc.close()
        assert any('"Jordi"' in r["value_json"] for r in prof)
        assert not (db.parent / (db.name + ".bak")).exists()

    def test_live_encrypted_db_verified_true_for_real_encrypted_db(self, tmp_path):
        """Helper integration — _live_encrypted_db_verified() returns True with a
        genuine SQLCipher live DB opened by the correct key (real SQLCipher),
        and False once the key no longer matches the file on disk."""
        db = tmp_path / "memory_v1.db"
        crypto = _crypto()
        store = SQLiteStore(db, crypto_provider=crypto)
        store.upsert_profile("u1", "name", "Verified")
        store.close()
        assert _header(db) != PLAINTEXT_HEADER

        # Reopen with the same key: live encrypted DB must verify True.
        again = SQLiteStore(db, crypto_provider=crypto)
        assert again._live_encrypted_db_verified() is True
        again.close()

    def test_live_encrypted_db_verified_false_for_wrong_key(self, tmp_path):
        """Helper integration (False branch) — _live_encrypted_db_verified()
        must return False when the live encrypted DB does NOT open with the
        current key. This is the branch that GATES the destructive sweep: a
        false-positive here would delete the .bak. Exercises the helper's
        ``except: return False`` path with real SQLCipher (a different key)."""
        db = tmp_path / "memory_v1.db"
        store = SQLiteStore(db, crypto_provider=_crypto())  # key A
        store.upsert_profile("u1", "name", "WrongKeyProbe")
        store.close()
        assert _header(db) != PLAINTEXT_HEADER

        # Build a store over the same encrypted file but with a DIFFERENT key,
        # bypassing __init__ (which would quarantine on boot).
        probe = SQLiteStore.__new__(SQLiteStore)
        probe._db_path = db
        probe._crypto = _crypto()  # key B != key A
        probe._encrypted = True
        assert probe._live_encrypted_db_verified() is False

    def test_sweep_preserves_bak_when_live_db_unverified(self, tmp_path):
        """Sweep guard in ISOLATION — calling _sweep_plaintext_leftovers
        directly with {live encrypted under a key we can't read, .bak plaintext
        with data} must KEEP the .bak. Pins the guard's own safety net,
        independent of the _init_db live-absent branch (defence in depth)."""
        db = tmp_path / "memory_v1.db"
        bak = db.with_name(db.name + ".bak")

        # Live DB encrypted with key A.
        live = SQLiteStore(db, crypto_provider=_crypto())
        live.upsert_profile("u1", "name", "LiveData")
        live.close()
        assert _header(db) != PLAINTEXT_HEADER

        # Plaintext .bak with data sitting next to it.
        seed_path = tmp_path / "seed.db"
        seed = SQLiteStore(seed_path)
        seed.upsert_profile("u1", "name", "BakData")
        seed.close()
        seed_path.rename(bak)
        bak.chmod(0o600)
        assert bak.exists() and SQLiteStore._is_plaintext_sqlite(bak)

        # Sweep with a key that CANNOT open the live DB → guard returns False.
        probe = SQLiteStore.__new__(SQLiteStore)
        probe._db_path = db
        probe._crypto = _crypto()  # key B != key A → live DB unverifiable
        probe._encrypted = True
        probe._sweep_plaintext_leftovers()

        assert bak.exists(), "guard failed: .bak swept without a verified live DB"
        assert SQLiteStore._is_plaintext_sqlite(bak)

    def test_live_encrypted_db_verified_false_when_live_absent(self, tmp_path):
        """Helper guard (early return) — returns False when the live DB file does
        not exist. Without this guard the probe would sqlcipher.connect() a fresh
        empty file and report it 'verified', letting the sweep delete a .bak that
        is the only real copy."""
        db = tmp_path / "memory_v1.db"  # never created
        probe = SQLiteStore.__new__(SQLiteStore)
        probe._db_path = db
        probe._crypto = _crypto()
        probe._encrypted = True
        assert probe._live_encrypted_db_verified() is False
        # The probe must NOT have created the live file as a side effect.
        assert not db.exists()

    def test_failed_migration_recovers_on_next_boot(self, tmp_path, monkeypatch):
        """Recovery CYCLE (the real user-facing guarantee) — a migration that
        fails (rollback to plaintext) loses NO data, AND the next boot with no
        failure migrates cleanly to encrypted with the data intact. Without the
        rollback, boot 1 destroys the only copy and boot 2 starts empty."""
        db = tmp_path / "memory_v1.db"
        crypto = _crypto()
        plain = SQLiteStore(db)
        plain.upsert_profile("u1", "name", "Recover")
        plain.close()
        assert SQLiteStore._is_plaintext_sqlite(db) is True

        real_rename = Path.rename
        calls = {"n": 0}

        def flaky_rename(self, target):
            # Fail the tmp->live rename only on the FIRST migration attempt.
            if Path(self).name.endswith(".encrypted") and Path(target) == db:
                calls["n"] += 1
                if calls["n"] == 1:
                    raise OSError("simulated failure on first migration only")
            return real_rename(self, target)

        monkeypatch.setattr(Path, "rename", flaky_rename)

        # Boot 1: migration fails -> rollback to plaintext, data preserved.
        boot1 = SQLiteStore(db, crypto_provider=crypto)
        assert SQLiteStore._is_plaintext_sqlite(db) is True, "boot 1 must roll back to plaintext"
        assert boot1._encrypted is False
        assert boot1.get_profile("u1", "name"), "data lost after failed migration"
        boot1.close()

        # Boot 2: rename works now -> migrates to encrypted, data intact.
        boot2 = SQLiteStore(db, crypto_provider=crypto)
        monkeypatch.undo()
        assert _header(db) != PLAINTEXT_HEADER, "boot 2 must migrate to encrypted"
        rows = boot2.get_profile("u1", "name")
        boot2.close()
        assert any('"Recover"' in r["value_json"] for r in rows), "data lost in recovery cycle"
