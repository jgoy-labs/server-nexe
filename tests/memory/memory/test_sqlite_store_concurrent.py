"""Thread-safety tests for memory.memory.storage.sqlite_store.SQLiteStore.

The cached sqlite3.Connection is shared across asyncio worker threads (the
GCDaemon, RAG ingest workers, and any caller that goes through
``asyncio.to_thread`` / ``run_in_executor``). Without ``check_same_thread=False``
and the RLock guard added on the audit-nit S10 fix, those callers would either
crash with ``sqlite3.ProgrammingError: SQLite objects created in a thread can
only be used in that same thread`` or interleave SELECT/INSERT pairs in
``upsert_profile`` and produce inconsistent state.
"""

from __future__ import annotations

import threading
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

import pytest

from memory.memory.storage.sqlite_store import SQLiteStore


@pytest.fixture
def store(tmp_path: Path) -> SQLiteStore:
    return SQLiteStore(tmp_path / "concurrent.db")


def test_insert_episodic_from_multiple_threads(store: SQLiteStore) -> None:
    """N threads inserting concurrently must not raise and must all land."""
    n_threads = 8
    inserts_per_thread = 25

    def _worker(worker_id: int) -> int:
        for i in range(inserts_per_thread):
            store.insert_episodic(
                user_id=f"u{worker_id}",
                content=f"worker {worker_id} item {i}",
            )
        return inserts_per_thread

    with ThreadPoolExecutor(max_workers=n_threads) as ex:
        results = [f.result() for f in as_completed(
            ex.submit(_worker, w) for w in range(n_threads)
        )]
    assert sum(results) == n_threads * inserts_per_thread

    total = sum(
        len(store.get_episodic(user_id=f"u{w}", limit=1000))
        for w in range(n_threads)
    )
    assert total == n_threads * inserts_per_thread


def test_upsert_profile_under_concurrency_keeps_one_row(store: SQLiteStore) -> None:
    """All threads upserting the SAME (user, entity, attribute) must collapse
    to a single profile row — no UNIQUE constraint failure, no duplicates."""
    n_threads = 16

    def _worker(value: int) -> str:
        return store.upsert_profile(
            user_id="alice",
            attribute="favourite_color",
            value=f"color-{value}",
        )

    with ThreadPoolExecutor(max_workers=n_threads) as ex:
        ids = [f.result() for f in as_completed(
            ex.submit(_worker, v) for v in range(n_threads)
        )]
    assert len(set(ids)) == 1, "All upserts must target the same entry_id"
    rows = store.get_profile("alice", attribute="favourite_color")
    assert len(rows) == 1


def test_mixed_readers_and_writers(store: SQLiteStore) -> None:
    """A mix of writers and readers must not crash."""
    stop = threading.Event()

    def _writer() -> int:
        n = 0
        while not stop.is_set():
            store.insert_episodic(user_id="alice", content=f"item {n}")
            n += 1
        return n

    def _reader() -> int:
        n = 0
        while not stop.is_set():
            store.get_episodic(user_id="alice", limit=10)
            n += 1
        return n

    with ThreadPoolExecutor(max_workers=4) as ex:
        futures = [
            ex.submit(_writer),
            ex.submit(_writer),
            ex.submit(_reader),
            ex.submit(_reader),
        ]
        # Let them run briefly.
        import time
        time.sleep(0.5)
        stop.set()
        results = [f.result() for f in futures]
    # All four threads completed without raising.
    assert all(r >= 0 for r in results)
