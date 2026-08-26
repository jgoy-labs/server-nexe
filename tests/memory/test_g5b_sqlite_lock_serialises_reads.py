"""
────────────────────────────────────
Server Nexe
Author: Jordi Goy
Location: tests/memory/test_g5b_sqlite_lock_serialises_reads.py
Description: G5b (#908) — the RLock on the cached SQLite connection serialises
             reads behind writes, and no read budget covers that path.

www.jgoy.net · https://server-nexe.org
────────────────────────────────────

#890 put a ceiling on the memory READ path, but that ceiling lives in
memory/memory/api/ and only wraps the Qdrant and embedder calls. MemoryService
reaches SQLite synchronously and directly — memory_service.py calls
self._store.get_profile(), get_episodic(), get_stats() with no await and no
executor — so it is outside that budget entirely. #955 already pinned that a
synchronous blocker cannot be cut by the budget; this is the store-side half of
the same shape, and the second hang vector #908 names.

Measured while mutation-testing this gate (26/08/2026): the serialisation does
NOT come only from the @_with_lock decorator. _connect() takes the same lock at
sqlite_store.py:119, and every operation goes through it — so removing the
decorator alone still leaves reads waiting behind writes. The vector is wider
than #908 describes: a method does not even need to be decorated to be caught
by it. Killing this gate takes disabling the lock itself, which is what the
mutation had to do.

The serialisation is deliberate: _with_lock's own docstring says the single
cached connection cannot be shared between threads without Python-level
synchronisation, and that for a mono-usuari local server the cost is
negligible. This gate does not argue with that. It measures it, so the limit is
visible in CI instead of only in a report — and so that a future switch to
per-call connections or a read-write lock has to come here and say so.
"""
from __future__ import annotations

import threading
import time

from memory.memory.storage.sqlite_store import SQLiteStore

HOLD = 0.4      # how long the simulated slow write keeps the lock
TOLERANCE = 0.3  # the read must have waited at least this much of it


def _store(tmp_path) -> SQLiteStore:
    return SQLiteStore(tmp_path / "memory.db")


def test_a_read_with_no_contention_is_fast(tmp_path):
    """Control: without a writer holding the lock, the same read is immediate.

    Without this, the test below would pass even if get_profile() were slow
    for some unrelated reason.
    """
    store = _store(tmp_path)
    try:
        started = time.monotonic()
        store.get_profile("u1")
        elapsed = time.monotonic() - started
    finally:
        store.close()

    assert elapsed < TOLERANCE, (
        f"an uncontended get_profile() took {elapsed:.3f}s — this test's "
        "control is broken, so the contention measurement below means nothing"
    )


def test_a_read_waits_behind_a_slow_write_on_the_same_connection(tmp_path):
    """The second hang vector: a slow write blocks reads, and nothing cuts it.

    If this starts failing because the read NO LONGER waits, someone has fixed
    the vector (per-call connections, or a read-write lock). That is good news:
    update this test and #908, don't delete the assert.
    """
    store = _store(tmp_path)
    writer_holds = threading.Event()

    def _slow_write():
        # Hold exactly what every decorated method holds. Simulating the write
        # by taking the real lock keeps the test honest about WHAT blocks:
        # it is the Python-level lock, not SQLite's own locking.
        with store._lock:
            writer_holds.set()
            time.sleep(HOLD)

    writer = threading.Thread(target=_slow_write, daemon=True)
    writer.start()
    assert writer_holds.wait(timeout=2.0), "the writer thread never started"

    try:
        started = time.monotonic()
        store.get_profile("u1")
        elapsed = time.monotonic() - started
    finally:
        writer.join(timeout=2.0)
        store.close()

    assert elapsed >= TOLERANCE, (
        f"the read returned in {elapsed:.3f}s while a writer held the lock for "
        f"{HOLD}s — either the store no longer serialises reads behind writes "
        "(good: update this test and #908) or the writer released early"
    )
