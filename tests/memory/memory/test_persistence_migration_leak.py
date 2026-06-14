"""
MEM-004: _migrate_to_encrypted must close BOTH the plain and the encrypted
connection on every path, including when an enc_conn.execute() inside the
iterdump loop raises. Otherwise the sqlite/sqlcipher handles (and the tmp WAL)
leak and can block the tmp cleanup.

These tests mock sqlcipher so they run without sqlcipher3 installed.
"""

import sqlite3
from pathlib import Path
from unittest.mock import MagicMock, patch

import memory.memory.engines.persistence_sqlite as ps
from memory.memory.engines.persistence_sqlite import SqliteStorageMixin


class _Store(SqliteStorageMixin):
    """Minimal concrete carrier exposing the mixin method under test."""

    def __init__(self, db_path: Path):
        self.db_path = db_path
        self._crypto = MagicMock()
        self._crypto.derive_key.return_value = b"\x00" * 32
        self._encrypted = False


def _make_plaintext_db(path: Path) -> None:
    conn = sqlite3.connect(str(path))
    conn.execute("CREATE TABLE t (id INTEGER PRIMARY KEY, v TEXT)")
    conn.execute("INSERT INTO t (v) VALUES ('hello')")
    conn.commit()
    conn.close()


def test_migration_closes_both_connections_when_iterdump_execute_raises(tmp_path):
    db_path = tmp_path / "memory.db"
    _make_plaintext_db(db_path)
    assert SqliteStorageMixin._is_plaintext_sqlite(db_path) is True

    store = _Store(db_path)

    # Real plain connection so iterdump() yields real DDL/DML; wrap it so we
    # can spy on close() (sqlite3.Connection.close is read-only, can't patch).
    class _ConnSpy:
        def __init__(self, conn):
            self._conn = conn
            self.close = MagicMock(wraps=conn.close)

        def __getattr__(self, name):
            return getattr(self._conn, name)

    real_plain = _ConnSpy(sqlite3.connect(str(db_path)))

    # Encrypted connection: a mock that raises when replaying a dumped line.
    enc_conn = MagicMock()

    def _enc_execute(stmt, *args, **kwargs):
        # PRAGMA setup lines pass; the first non-PRAGMA dump line blows up,
        # simulating a mid-dump failure.
        if not stmt.strip().upper().startswith("PRAGMA"):
            raise RuntimeError("boom mid-dump")

    enc_conn.execute.side_effect = _enc_execute

    fake_sqlcipher = MagicMock()
    fake_sqlcipher.connect.return_value = enc_conn

    with patch.object(ps, "SQLCIPHER_AVAILABLE", True), \
         patch.object(ps, "sqlcipher", fake_sqlcipher), \
         patch.object(ps.sqlite3, "connect", return_value=real_plain):
        # Must not raise; failure is logged and the plain DB is kept.
        store._migrate_to_encrypted()

    # The core assertion of MEM-004: both handles are closed on the error path.
    real_plain.close.assert_called_once()
    enc_conn.close.assert_called_once()

    # Plain DB preserved (migration failed, no .bak rename happened).
    assert db_path.exists()
    assert SqliteStorageMixin._is_plaintext_sqlite(db_path) is True


def test_migration_removes_plaintext_backup_on_success(tmp_path):
    # B089 / D-002: after a SUCCESSFUL migration the plaintext .db.bak must be
    # REMOVED (Decision B), not merely chmod'd — otherwise the cleartext PII
    # survives on disk and is recoverable on a stolen device.
    db_path = tmp_path / "memory.db"
    _make_plaintext_db(db_path)
    store = _Store(db_path)

    enc_conn = MagicMock()  # accepts every PRAGMA/dump line → success path

    def _connect(path):
        # the real sqlcipher creates the encrypted tmp file; emulate it so the
        # subsequent tmp_path.rename(db_path) succeeds without sqlcipher3.
        Path(path).write_bytes(b"not-a-plaintext-sqlite-header")
        return enc_conn

    fake_sqlcipher = MagicMock()
    fake_sqlcipher.connect.side_effect = _connect

    with patch.object(ps, "SQLCIPHER_AVAILABLE", True), \
         patch.object(ps, "sqlcipher", fake_sqlcipher):
        store._migrate_to_encrypted()

    bak_path = db_path.with_suffix(".db.bak")
    assert not bak_path.exists()  # fail-before: D-002 left the .bak (only chmod'd)
    assert db_path.exists()
    assert SqliteStorageMixin._is_plaintext_sqlite(db_path) is False
