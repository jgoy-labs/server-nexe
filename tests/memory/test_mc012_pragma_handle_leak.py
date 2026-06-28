"""MC-012: SQLCipher connection leak when a PRAGMA fails after connect().

The quarantine/verify probes open a connection and run PRAGMA key +
PRAGMA cipher_compatibility BEFORE entering the inner try/finally that guards
the SELECT. If either PRAGMA raises (corrupt header, OOM, I/O error), control
jumps to the except handler without ever closing ``conn`` → file-descriptor
leak (and on Windows an open handle blocks the subsequent rename/cleanup).

The same pattern is replicated across five sibling probes; each is pinned here.
Skipped when sqlcipher3 is not installed (the C extension supplies the real
DatabaseError class the except clause references).
"""
import os
from unittest.mock import MagicMock

import pytest

from core.crypto.provider import CryptoProvider
from memory.memory.api import text_store as ts_mod
from memory.memory.engines import persistence_sqlite as ps_mod
from memory.memory.storage import sqlite_store as ss_mod

pytestmark = pytest.mark.skipif(
    not ss_mod.SQLCIPHER_AVAILABLE, reason="sqlcipher3 not installed"
)


def _crypto():
    return CryptoProvider(master_key=os.urandom(32))


def _make(mod, cls_name, path_attr, db):
    """Build the probe owner with only the attributes the probe touches."""
    obj = object.__new__(getattr(mod, cls_name))
    setattr(obj, path_attr, db)
    obj._encrypted = True
    obj._crypto = _crypto()
    return obj


# (module, class, path attribute, method, returns True when quarantined)
CASES = [
    (ps_mod, "SqliteStorageMixin", "db_path", "_quarantine_unreadable_encrypted_db", True),
    (ss_mod, "SQLiteStore", "_db_path", "_quarantine_unreadable_encrypted_db", True),
    (ts_mod, "TextStore", "_db_path", "_quarantine_unreadable_encrypted_db", True),
    (ss_mod, "SQLiteStore", "_db_path", "_live_encrypted_db_verified", False),
    (ts_mod, "TextStore", "_db_path", "_live_encrypted_db_verified", False),
]


@pytest.mark.parametrize(
    "mod,cls_name,path_attr,method,is_quarantine",
    CASES,
    ids=[f"{c[1]}.{c[3]}" for c in CASES],
)
def test_pragma_failure_closes_connection(
    tmp_path, monkeypatch, mod, cls_name, path_attr, method, is_quarantine
):
    db = tmp_path / "memory_v1.db"
    db.write_bytes(b"this is not a valid sqlcipher database header\x00" * 4)
    assert db.exists() and db.stat().st_size > 0

    fake_conn = MagicMock()
    # A "file is not a database" error keeps _quarantine on its quarantine path
    # (the message gate); _live just needs any failure.
    fake_conn.execute.side_effect = mod.sqlcipher.DatabaseError(
        "file is not a database"
    )
    monkeypatch.setattr(mod.sqlcipher, "connect", lambda *a, **k: fake_conn)

    obj = _make(mod, cls_name, path_attr, db)
    result = getattr(obj, method)()

    if is_quarantine:
        assert result is True
    else:
        assert result is False

    fake_conn.close.assert_called_once()
