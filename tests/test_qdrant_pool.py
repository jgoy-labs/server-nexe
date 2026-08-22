"""
────────────────────────────────────
Server Nexe
Author: Jordi Goy
Location: tests/test_qdrant_pool.py
Description: Tests for Bug 13 — flush before close in qdrant_pool and explicit
             error handling (replaces the `except: pass` that was hiding
             silent corruptions).

www.jgoy.net · https://server-nexe.org
────────────────────────────────────
"""
import logging
from unittest.mock import MagicMock

import pytest

import core.qdrant_pool as pool


@pytest.fixture(autouse=True)
def _reset_pool():
    pool._instances.clear()
    yield
    pool._instances.clear()


def test_close_calls_flush_then_close():
    """flush must be called BEFORE close, and both without errors."""
    client = MagicMock()
    call_order = []
    client.flush.side_effect = lambda: call_order.append("flush")
    client.close.side_effect = lambda: call_order.append("close")
    pool._instances["test:fake"] = client

    pool.close_qdrant_client()

    assert call_order == ["flush", "close"], (
        f"Expected order ['flush','close'], got {call_order}"
    )
    assert pool._instances == {}


def test_close_logs_warning_on_close_failure(caplog):
    """If close() raises, it is not swallowed: an explicit warning is logged.

    Previously there was `except Exception: pass` that was hiding any
    corruption or I/O error on close.
    """
    client = MagicMock()
    client.flush = MagicMock()  # flush ok
    client.close.side_effect = RuntimeError("disk full")
    pool._instances["test:broken"] = client

    with caplog.at_level(logging.WARNING, logger="core.qdrant_pool"):
        pool.close_qdrant_client()

    assert any(
        "Qdrant pool close failed" in rec.message
        and "disk full" in rec.message
        for rec in caplog.records
    ), f"Expected warning not found in logs: {[r.message for r in caplog.records]}"
    assert pool._instances == {}


def test_close_handles_missing_flush_gracefully(caplog):
    """If the client has no flush(), continues with close() without crashing."""
    client = MagicMock(spec=["close"])  # only close, no flush
    pool._instances["test:no-flush"] = client

    with caplog.at_level(logging.DEBUG, logger="core.qdrant_pool"):
        pool.close_qdrant_client()

    client.close.assert_called_once()
    assert pool._instances == {}


def test_close_logs_warning_on_flush_failure(caplog):
    """If flush() raises, it is logged but close() is still called."""
    client = MagicMock()
    client.flush.side_effect = RuntimeError("flush boom")
    pool._instances["test:flush-fail"] = client

    with caplog.at_level(logging.WARNING, logger="core.qdrant_pool"):
        pool.close_qdrant_client()

    # close() was called despite the flush failing
    client.close.assert_called_once()
    assert any(
        "flush" in rec.message.lower() for rec in caplog.records
    )


# Bug #5 (2026-05-21): sentinel anti-regression that the close+reopen
# cycle on the same path within a single process does not leave the lock held.
# Note: this does NOT reproduce the multi-process race (which is what the
# real bug is about) — for that we'd need `multiprocessing` (fragile across
# pytest + macOS spawn). Instead this guards that the productor side
# (`close_qdrant_client` -> `QdrantLocal.close`) does release the POSIX
# flock cleanly within a single Python process. Combined with the
# `_startup_qdrant` retry-with-backoff in core/lifespan_qdrant.py, real
# multi-process restarts are now resilient to the ~ms-scale FD-release
# lag.
def test_close_and_reopen_same_path_releases_lock(tmp_path):
    """Closing the pool releases the .lock so the same path can be reopened."""
    from qdrant_client import QdrantClient

    path = str(tmp_path / "qdrant-cycle")
    # First open: takes the lock
    pool._instances.clear()
    c1 = QdrantClient(path=path)
    pool._instances[f"path:{path}"] = c1

    # Close releases the POSIX flock + closes the FD
    pool.close_qdrant_client()
    assert pool._instances == {}

    # Reopen at the same path within the same process must NOT raise
    # RuntimeError("Storage folder ... is already accessed").
    c2 = QdrantClient(path=path)
    pool._instances[f"path:{path}"] = c2
    pool.close_qdrant_client()


# NEXE-SRV-WS3-06 (2026-07-10): the vectors dir holds PII embeddings, so it
# must be created owner-only (0o700) mirroring sqlite_store — not left to
# inherit the process umask (0o755 with the default umask 022), which would
# expose the embeddings to other local accounts on a shared Mac.
def test_create_client_chmods_vectors_dir_0o700(tmp_path):
    """_create_client must chmod the vectors dir to 0o700 right after mkdir."""
    import os
    import stat

    # Relax the umask so mkdir alone would leave a world-readable dir:
    # this proves the os.chmod (not the umask) is what enforces 0o700.
    old_umask = os.umask(0o022)
    try:
        path = str(tmp_path / "vectors-perms")
        client = pool._create_client(path, None)
        try:
            mode = stat.S_IMODE(os.stat(path).st_mode)
            assert mode == 0o700, f"Expected 0o700, got {oct(mode)}"
        finally:
            client.close()
    finally:
        os.umask(old_umask)


def test_create_client_hardens_preexisting_lax_dir(tmp_path):
    """Even if the dir already exists with lax perms, it is tightened to 0o700."""
    import os
    import stat

    old_umask = os.umask(0o022)
    try:
        p = tmp_path / "vectors-preexisting"
        p.mkdir()
        os.chmod(p, 0o755)  # world-readable/traversable before _create_client
        assert stat.S_IMODE(os.stat(p).st_mode) == 0o755

        client = pool._create_client(str(p), None)
        try:
            mode = stat.S_IMODE(os.stat(p).st_mode)
            assert mode == 0o700, f"Expected 0o700, got {oct(mode)}"
        finally:
            client.close()
    finally:
        os.umask(old_umask)


class TestProbeAndObservation:
    """#891 — the pool grows the only place that ASKS whether Qdrant is there.

    Before this, nothing asked: the RAG check read the installed package
    version and the lifespan set qdrant_available = True right after a mkdir,
    without contacting anything in external mode. The watcher's Qdrant eye,
    added the day before, read that flag — so it could not fire while the
    server served.
    """

    def setup_method(self):
        import core.qdrant_pool as pool
        pool._last_observation = None

    def test_a_store_that_refuses_the_connection_is_not_available(self):
        from core.qdrant_pool import probe_qdrant

        ok, detail = probe_qdrant(url="http://127.0.0.1:59999", timeout=3.0)
        assert ok is False
        assert detail, "a failure has to say why"

    def test_a_client_that_raises_is_not_available(self):
        from unittest.mock import patch

        import core.qdrant_pool as pool

        with patch.object(pool, "get_qdrant_client", side_effect=RuntimeError("already accessed")):
            ok, detail = pool.probe_qdrant(path="/tmp/whatever", timeout=3.0)
        assert ok is False
        assert "already accessed" in detail

    def test_a_store_that_never_answers_times_out_instead_of_hanging(self):
        import time
        from unittest.mock import patch

        import core.qdrant_pool as pool

        def _forever(*_a, **_kw):
            time.sleep(30)

        started = time.monotonic()
        with patch.object(pool, "get_qdrant_client", side_effect=_forever):
            ok, detail = pool.probe_qdrant(path="/tmp/whatever", timeout=0.3)
        elapsed = time.monotonic() - started

        assert ok is False
        assert "no answer" in detail
        assert elapsed < 5, (
            f"the probe took {elapsed:.1f}s: a wedged store must not hold up "
            "whoever asked — health endpoints and the watcher both call this"
        )

    def test_the_observation_is_reused_instead_of_probing_again(self):
        """qdrant_status() is what readers call, and readers run on the event
        loop. It must answer from the last observation, not open a probe."""
        from unittest.mock import patch

        import core.qdrant_pool as pool

        with patch.object(pool, "get_qdrant_client") as client:
            client.return_value.get_collections.return_value.collections = []
            pool.probe_qdrant(path="/tmp/whatever", timeout=3.0)
            calls_after_probe = client.call_count
            pool.qdrant_status()
            pool.qdrant_status()

        assert client.call_count == calls_after_probe, (
            "qdrant_status() probed again; on the event loop that stalls the server"
        )

    def test_with_no_observation_at_all_it_probes_rather_than_lying(self):
        from unittest.mock import patch

        import core.qdrant_pool as pool

        with patch.object(pool, "get_qdrant_client", side_effect=RuntimeError("nope")):
            ok, _ = pool.qdrant_status()
        assert ok is False, "the cold path must ask, not assume"

    def test_a_stale_observation_says_how_old_it_is(self):
        from unittest.mock import patch

        import core.qdrant_pool as pool

        with patch.object(pool, "get_qdrant_client") as client:
            client.return_value.get_collections.return_value.collections = []
            pool.probe_qdrant(path="/tmp/whatever", timeout=3.0)

        ok, detail = pool.qdrant_status(max_age=-1)  # force staleness
        assert ok is True
        assert "last seen" in detail, "a stale reading must not pass as fresh"
