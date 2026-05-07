"""
Tests for memory/memory/workers/dreaming_cycle.py — Bug 10 fix release v0.9.0.

Verifies that _count_pending() and _sync_vector_index() always close the
SQLite connection (there was no close() before → cumulative connection leak
since the cycle runs every 15 min).

Strategy: fake store that returns a MagicMock as connection and counts
how many times close() was called.
"""

import asyncio
from unittest.mock import MagicMock

import pytest

from memory.memory.workers.dreaming_cycle import DreamingCycle


class _FakeCursor:
    def __init__(self, rows=None, count=0):
        self._rows = rows or []
        self._count = count

    def fetchone(self):
        return (self._count,)

    def fetchall(self):
        return self._rows


class _FakeConn:
    """Fake SQLite connection that records close() and execute() calls."""

    def __init__(self, count=0, rows=None):
        self.closed = False
        self.executed = []
        self._count = count
        self._rows = rows or []

    def execute(self, sql, params=()):
        self.executed.append((sql, params))
        if "COUNT(*)" in sql:
            return _FakeCursor(count=self._count)
        if "SELECT" in sql:
            return _FakeCursor(rows=self._rows)
        return _FakeCursor()

    def commit(self):
        pass

    def close(self):
        self.closed = True


class _FakeStore:
    def __init__(self, conn):
        self._conn = conn
        self.get_staging_calls = 0

    def _connect(self):
        return self._conn

    def get_staging(self, **kwargs):
        self.get_staging_calls += 1
        return []


def _make_cycle(store, vector=None, embedder=None):
    # Bypass full __init__ to avoid dependency on real MemoryConfig
    cycle = DreamingCycle.__new__(DreamingCycle)
    cycle._store = store
    cycle._vector = vector
    cycle._embedder = embedder
    cycle._is_running = False
    cycle._should_stop = False
    cycle._consecutive_skips = 0
    cycle._force_threshold = 50
    cycle._interval = 900
    cycle._task = None
    cycle._config = MagicMock()
    return cycle


def test_count_pending_closes_connection():
    conn = _FakeConn(count=7)
    store = _FakeStore(conn)
    cycle = _make_cycle(store)

    result = cycle._count_pending()
    assert result == 7
    assert conn.closed, "_count_pending didn't close the SQLite connection"


def test_count_pending_closes_connection_on_exception():
    """If execute() raises, the connection must also be closed."""
    class _BadConn(_FakeConn):
        def execute(self, sql, params=()):
            raise RuntimeError("boom")

    conn = _BadConn()
    store = _FakeStore(conn)
    cycle = _make_cycle(store)

    result = cycle._count_pending()
    # _count_pending catches exceptions and returns 0
    assert result == 0
    assert conn.closed, "connection not closed after exception"


def test_count_pending_no_store_returns_zero():
    cycle = _make_cycle(store=None)
    assert cycle._count_pending() == 0


def test_sync_vector_index_closes_connection_when_empty():
    conn = _FakeConn(rows=[])
    store = _FakeStore(conn)
    vector = MagicMock()
    vector.available = True
    embedder = MagicMock()

    cycle = _make_cycle(store, vector=vector, embedder=embedder)
    asyncio.run(cycle._sync_vector_index())
    assert conn.closed, "_sync_vector_index didn't close on empty result"


def test_sync_vector_index_closes_connection_on_exception():
    class _BadConn(_FakeConn):
        def execute(self, sql, params=()):
            raise RuntimeError("db down")

    conn = _BadConn()
    store = _FakeStore(conn)
    vector = MagicMock()
    vector.available = True
    embedder = MagicMock()

    cycle = _make_cycle(store, vector=vector, embedder=embedder)
    asyncio.run(cycle._sync_vector_index())
    assert conn.closed, "connection not closed after sync exception"


def test_sync_vector_index_skips_when_no_dependencies():
    """Without store/vector/embedder, _sync_vector_index must return cleanly."""
    cycle = _make_cycle(store=None)
    asyncio.run(cycle._sync_vector_index())  # no exception


def test_sync_vector_index_skips_when_vector_unavailable():
    conn = _FakeConn()
    store = _FakeStore(conn)
    vector = MagicMock()
    vector.available = False
    embedder = MagicMock()

    cycle = _make_cycle(store, vector=vector, embedder=embedder)
    asyncio.run(cycle._sync_vector_index())
    # No connection was opened because we exited early
    assert not conn.closed
    assert conn.executed == []


# ── Dev #3: Bug 10 fix passada 2 — les 4 funcions restants ──────────────


def test_recover_stuck_leases_closes_connection():
    """_recover_stuck_leases must close the SQLite connection (Bug 10)."""
    conn = _FakeConn()
    store = _FakeStore(conn)
    cycle = _make_cycle(store)
    asyncio.run(cycle._recover_stuck_leases())
    assert conn.closed, "_recover_stuck_leases didn't close the connection"


def test_recover_stuck_leases_closes_connection_on_exception():
    class _BadConn(_FakeConn):
        def execute(self, sql, params=()):
            raise RuntimeError("db down")

    conn = _BadConn()
    store = _FakeStore(conn)
    cycle = _make_cycle(store)
    asyncio.run(cycle._recover_stuck_leases())
    assert conn.closed, "connection not closed after recover exception"


def test_recover_stuck_leases_no_store():
    cycle = _make_cycle(store=None)
    asyncio.run(cycle._recover_stuck_leases())  # no exception


def test_process_staging_closes_connection_empty():
    """_process_staging must close the connection when there are no entries."""
    conn = _FakeConn(rows=[])
    store = _FakeStore(conn)
    cycle = _make_cycle(store)
    asyncio.run(cycle._process_staging())
    assert conn.closed, "_process_staging didn't close on empty"


def test_process_staging_closes_connection_on_exception():
    class _BadConn(_FakeConn):
        def execute(self, sql, params=()):
            raise RuntimeError("boom")

    conn = _BadConn()
    store = _FakeStore(conn)
    cycle = _make_cycle(store)
    asyncio.run(cycle._process_staging())
    assert conn.closed, "connection not closed after exception"


def test_process_staging_no_store():
    cycle = _make_cycle(store=None)
    asyncio.run(cycle._process_staging())  # no exception


def test_process_one_closes_connection_profile_path():
    """_process_one must close the connection on the profile path (Bug 10, quadratic leak)."""
    conn = _FakeConn()
    store = _FakeStore(conn)
    # Add the methods that _process_one calls
    store.upsert_profile = MagicMock()
    cycle = _make_cycle(store)
    entry = {
        "id": 1,
        "user_id": "user-a",
        "validator_decision": "upsert_profile",
        "target_store": "profile",
        "extractor_output_json": '{"attribute":"name","value":"Jordi","entity":"user"}',
        "raw_text": "em dic Jordi",
        "source": "dreaming",
        "trust_level": "untrusted",
    }
    asyncio.run(cycle._process_one(entry))
    assert conn.closed, "_process_one didn't close connection on profile path"
    store.upsert_profile.assert_called_once()


def test_process_one_closes_connection_on_exception():
    """If processing fails midway, the connection must still be closed."""
    class _BadConn(_FakeConn):
        def __init__(self):
            super().__init__()
            self.calls = 0

        def execute(self, sql, params=()):
            self.calls += 1
            if self.calls >= 2:
                raise RuntimeError("boom mid-process")
            return super().execute(sql, params)

    conn = _BadConn()
    store = _FakeStore(conn)
    store.upsert_profile = MagicMock()
    cycle = _make_cycle(store)
    entry = {
        "id": 2,
        "user_id": "user-b",
        "validator_decision": "upsert_profile",
        "target_store": "profile",
        "extractor_output_json": '{"attribute":"lang","value":"ca"}',
    }
    with pytest.raises(RuntimeError):
        asyncio.run(cycle._process_one(entry))
    assert conn.closed, "connection not closed after _process_one exception"


def test_process_one_no_store():
    cycle = _make_cycle(store=None)
    asyncio.run(cycle._process_one({"id": 1, "user_id": "x"}))  # no exception


def test_gc_lightweight_closes_connection():
    conn = _FakeConn()
    store = _FakeStore(conn)
    cycle = _make_cycle(store)
    asyncio.run(cycle._gc_lightweight())
    assert conn.closed, "_gc_lightweight didn't close the connection"


def test_gc_lightweight_closes_connection_on_exception():
    class _BadConn(_FakeConn):
        def execute(self, sql, params=()):
            raise RuntimeError("disk full")

    conn = _BadConn()
    store = _FakeStore(conn)
    cycle = _make_cycle(store)
    asyncio.run(cycle._gc_lightweight())
    assert conn.closed, "connection not closed after gc exception"


def test_gc_lightweight_no_store():
    cycle = _make_cycle(store=None)
    asyncio.run(cycle._gc_lightweight())  # no exception
