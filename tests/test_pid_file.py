"""
────────────────────────────────────
Server Nexe — Tests
Location: tests/test_pid_file.py
Description: Tests for canonical PID file acquire/release (Bug #1, Fase 1B).
             PID file format: JSON {"pid": N, "port": P, "started": ISO}
────────────────────────────────────
"""

import json
import os
from pathlib import Path
from unittest.mock import patch

import pytest

from core.server.runner import _acquire_pidfile, _release_pidfile


def _read_pid(pid_path: Path) -> dict:
    """Helper: read the JSON PID file."""
    return json.loads(pid_path.read_text())


def _write_pid(pid_path: Path, pid: int, port: int = 9119, started: str = "2026-04-06T00:00:00+00:00"):
    """Helper: write a JSON PID file."""
    pid_path.write_text(json.dumps({"pid": pid, "port": port, "started": started}))


def test_acquire_pidfile_creates_when_missing(tmp_path: Path):
    """No pre-existing file → acquire succeeds and writes pid/port/started as JSON."""
    pid_path = tmp_path / "run" / "server.pid"
    assert not pid_path.exists()

    ok = _acquire_pidfile(pid_path, port=9119)
    assert ok is True
    assert pid_path.exists()

    data = _read_pid(pid_path)
    assert data["pid"] == os.getpid()
    assert data["port"] == 9119
    # ISO timestamp must be parseable
    from datetime import datetime
    datetime.fromisoformat(data["started"])


def test_acquire_pidfile_rejects_when_live_pid_holds_lock(tmp_path: Path):
    """Existing file with a live PID → acquire returns False."""
    pid_path = tmp_path / "server.pid"
    _write_pid(pid_path, pid=99999)

    # Mock os.kill to simulate the PID being alive (no exception raised)
    with patch("core.server.runner.os.kill", return_value=None):
        ok = _acquire_pidfile(pid_path, port=9119)

    assert ok is False
    # File must NOT be removed/overwritten
    assert pid_path.exists()
    assert _read_pid(pid_path)["pid"] == 99999


def test_acquire_pidfile_replaces_stale_dead_pid(tmp_path: Path):
    """Existing file with a dead PID → stale lock removed, new file written."""
    pid_path = tmp_path / "server.pid"
    _write_pid(pid_path, pid=99999)

    def _fake_kill(pid, sig):
        raise ProcessLookupError(f"No such process: {pid}")

    with patch("core.server.runner.os.kill", side_effect=_fake_kill):
        ok = _acquire_pidfile(pid_path, port=9119)

    assert ok is True
    assert pid_path.exists()
    assert _read_pid(pid_path)["pid"] == os.getpid()


def test_acquire_pidfile_replaces_corrupt_file(tmp_path: Path):
    """Corrupt content → file removed, new one written."""
    pid_path = tmp_path / "server.pid"
    pid_path.write_text("not-json-at-all\n")

    ok = _acquire_pidfile(pid_path, port=9119)
    assert ok is True
    assert _read_pid(pid_path)["pid"] == os.getpid()


def test_release_pidfile_removes_owned_file(tmp_path: Path):
    """_release_pidfile removes a file we own."""
    pid_path = tmp_path / "server.pid"
    _write_pid(pid_path, pid=os.getpid())

    _release_pidfile(pid_path)
    assert not pid_path.exists()


def test_release_pidfile_skips_foreign_file(tmp_path: Path):
    """_release_pidfile leaves files owned by another PID intact."""
    pid_path = tmp_path / "server.pid"
    _write_pid(pid_path, pid=99999)

    _release_pidfile(pid_path)
    assert pid_path.exists()


def test_release_pidfile_noop_when_missing(tmp_path: Path):
    """_release_pidfile is safe when the file does not exist."""
    pid_path = tmp_path / "nope.pid"
    _release_pidfile(pid_path)  # must not raise
    assert not pid_path.exists()


def test_acquire_pidfile_atomic_concurrent(tmp_path: Path):
    """Dos threads concurrents: exactament un guanya el lock, l'altre rep False.

    RED gate: amb la implementació no-atòmica (exists+write) tots dos poden
    guanyar simultàniament. Amb O_CREAT|O_EXCL exactament un guanya.
    """
    import threading

    pid_path = tmp_path / "run" / "server.pid"
    results = []
    barrier = threading.Barrier(2)

    def _try_acquire():
        barrier.wait()  # garanteix execució simultània
        ok = _acquire_pidfile(pid_path, port=9119)
        results.append(ok)

    t1 = threading.Thread(target=_try_acquire)
    t2 = threading.Thread(target=_try_acquire)
    t1.start()
    t2.start()
    t1.join()
    t2.join()

    # Exactament un True i un False
    assert sorted(results) == [False, True], (
        f"Esperàvem [False, True], obtingut {sorted(results)} — "
        "TOCTOU race: tots dos han adquirit el lock simultàniament"
    )
