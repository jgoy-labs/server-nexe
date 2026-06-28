"""MC-013: BootstrapTokenManager.initialize_on_startup leaks the connection.

initialize_on_startup opens a sqlite3 connection and runs PRAGMA + three
CREATE TABLE + commit WITHOUT a try/finally. If any statement raises (corrupt
DB on PRAGMA, disk full on CREATE/commit, I/O error), ``conn.close()`` (the
last line) is skipped and the handle leaks until GC — unlike every other
method in the class, which wraps the connection in try/finally. On Windows a
retained handle can block temp-dir cleanup.
"""
import sqlite3
from unittest.mock import MagicMock

import pytest

import core.bootstrap_tokens as bt_mod
from core.bootstrap_tokens import BootstrapTokenManager


def test_initialize_on_startup_closes_conn_on_failure(tmp_path, monkeypatch):
    fake_conn = MagicMock()
    fake_conn.cursor.return_value = MagicMock()
    fake_conn.commit.side_effect = sqlite3.OperationalError("disk I/O error")
    monkeypatch.setattr(bt_mod.sqlite3, "connect", lambda *a, **k: fake_conn)

    mgr = object.__new__(BootstrapTokenManager)
    mgr._db_path = None
    mgr._initialized = False

    with pytest.raises(sqlite3.OperationalError):
        mgr.initialize_on_startup(tmp_path)

    fake_conn.close.assert_called_once()
    assert mgr._initialized is False
