"""
────────────────────────────────────
Server Nexe
Author: Jordi Goy
Location: tests/memory/memory/test_migration_leak_mc010.py
Description: MC-010 — _migrate_to_encrypted de SQLiteStore i TextStore ha de tancar
             LES DUES connexions (plain + encrypted) a TOTS els camins, també quan
             un enc_conn.execute() dins el bucle iterdump peta. Sense un finally les
             connexions inline només es tanquen al camí d'èxit → fuita de handles
             (i a Windows el handle retingut bloqueja la neteja del tmp). Mateix bug
             i mateix fix que persistence_sqlite.py (MEM-004). RED abans del fix
             (les connexions no es tanquen), GREEN després.

www.jgoy.net · https://server-nexe.org
────────────────────────────────────
"""

import sqlite3
from pathlib import Path
from unittest.mock import MagicMock, patch

import memory.memory.storage.sqlite_store as ss
import memory.memory.api.text_store as ts
from memory.memory.storage.sqlite_store import SQLiteStore
from memory.memory.api.text_store import TextStore


def _make_plaintext_db(path: Path) -> None:
    conn = sqlite3.connect(str(path))
    conn.execute("CREATE TABLE t (id INTEGER PRIMARY KEY, v TEXT)")
    conn.execute("INSERT INTO t (v) VALUES ('hello')")
    conn.commit()
    conn.close()


class _ConnSpy:
    """Real plain connection (so iterdump() generates real DDL/DML) with a spied
    close() — sqlite3.Connection.close cannot be patched directly."""

    def __init__(self, conn):
        self._conn = conn
        self.close = MagicMock(wraps=conn.close)

    def __getattr__(self, name):
        return getattr(self._conn, name)


def _enc_conn_that_raises_mid_dump():
    enc_conn = MagicMock()

    def _enc_execute(stmt, *args, **kwargs):
        # Les PRAGMA de setup passen; la primera línia de dump no-PRAGMA peta,
        # simulant una fallada a mig dump.
        if not stmt.strip().upper().startswith("PRAGMA"):
            raise RuntimeError("boom mid-dump")

    enc_conn.execute.side_effect = _enc_execute
    return enc_conn


def _bare(cls, db_path):
    """Instance without __init__ (avoids the startup logic); we set only the
    attributes that _migrate_to_encrypted needs."""
    obj = object.__new__(cls)
    obj._db_path = db_path
    obj._crypto = MagicMock()
    obj._crypto.derive_key.return_value = b"\x00" * 32
    obj._encrypted = False
    return obj


def test_sqlite_store_closes_both_connections_on_mid_dump_raise(tmp_path):
    db_path = tmp_path / "memory_v1.db"
    _make_plaintext_db(db_path)
    assert SQLiteStore._is_plaintext_sqlite(db_path) is True

    store = _bare(SQLiteStore, db_path)
    real_plain = _ConnSpy(sqlite3.connect(str(db_path)))
    enc_conn = _enc_conn_that_raises_mid_dump()
    fake_sqlcipher = MagicMock()
    fake_sqlcipher.connect.return_value = enc_conn

    with patch.object(ss, "SQLCIPHER_AVAILABLE", True), \
            patch.object(ss, "sqlcipher", fake_sqlcipher), \
            patch.object(ss.sqlite3, "connect", return_value=real_plain):
        store._migrate_to_encrypted()  # no ha de propagar; loga i manté el plain

    real_plain.close.assert_called_once()
    enc_conn.close.assert_called_once()
    # Plain DB preservada (la migració va fallar, cap rename a .bak).
    assert db_path.exists()
    assert SQLiteStore._is_plaintext_sqlite(db_path) is True


def test_text_store_closes_both_connections_on_mid_dump_raise(tmp_path):
    db_path = tmp_path / "text_store.db"
    _make_plaintext_db(db_path)
    assert TextStore._is_plaintext_sqlite(db_path) is True

    store = _bare(TextStore, db_path)
    real_plain = _ConnSpy(sqlite3.connect(str(db_path)))
    enc_conn = _enc_conn_that_raises_mid_dump()
    fake_sqlcipher = MagicMock()
    fake_sqlcipher.connect.return_value = enc_conn

    with patch.object(ts, "SQLCIPHER_AVAILABLE", True), \
            patch.object(ts, "sqlcipher", fake_sqlcipher), \
            patch.object(ts.sqlite3, "connect", return_value=real_plain):
        store._migrate_to_encrypted()

    real_plain.close.assert_called_once()
    enc_conn.close.assert_called_once()
    assert db_path.exists()
    assert TextStore._is_plaintext_sqlite(db_path) is True
