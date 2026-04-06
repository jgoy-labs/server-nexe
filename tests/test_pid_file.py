"""
────────────────────────────────────
Server Nexe — Tests
Location: tests/test_pid_file.py
Description: Tests for canonical PID file acquire/release (Bug #1, Fase 1B).
────────────────────────────────────
"""

import os
from pathlib import Path
from unittest.mock import patch

import pytest

from core.server.runner import _acquire_pidfile, _release_pidfile


def test_acquire_pidfile_creates_when_missing(tmp_path: Path):
    """No pre-existing file → acquire succeeds and writes pid/port/timestamp."""
    pid_path = tmp_path / "run" / "server.pid"
    assert not pid_path.exists()

    ok = _acquire_pidfile(pid_path, port=9119)
    assert ok is True
    assert pid_path.exists()

    lines = pid_path.read_text().strip().split("\n")
    assert len(lines) == 3
    assert int(lines[0]) == os.getpid()
    assert lines[1] == "9119"
    # ISO timestamp must be parseable
    from datetime import datetime
    datetime.fromisoformat(lines[2])


def test_acquire_pidfile_rejects_when_live_pid_holds_lock(tmp_path: Path):
    """Existing file with a live PID → acquire returns False."""
    pid_path = tmp_path / "server.pid"
    pid_path.write_text("99999\n9119\n2026-04-06T00:00:00+00:00\n")

    # Mock os.kill to simulate the PID being alive (no exception raised)
    with patch("core.server.runner.os.kill", return_value=None):
        ok = _acquire_pidfile(pid_path, port=9119)

    assert ok is False
    # File must NOT be removed/overwritten
    assert pid_path.exists()
    assert pid_path.read_text().startswith("99999\n")


def test_acquire_pidfile_replaces_stale_dead_pid(tmp_path: Path):
    """Existing file with a dead PID → stale lock removed, new file written."""
    pid_path = tmp_path / "server.pid"
    pid_path.write_text("99999\n9119\n2026-04-06T00:00:00+00:00\n")

    def _fake_kill(pid, sig):
        raise ProcessLookupError(f"No such process: {pid}")

    with patch("core.server.runner.os.kill", side_effect=_fake_kill):
        ok = _acquire_pidfile(pid_path, port=9119)

    assert ok is True
    assert pid_path.exists()
    assert int(pid_path.read_text().strip().split("\n")[0]) == os.getpid()


def test_acquire_pidfile_replaces_corrupt_file(tmp_path: Path):
    """Corrupt content → file removed, new one written."""
    pid_path = tmp_path / "server.pid"
    pid_path.write_text("not-a-number\nbroken\n")

    ok = _acquire_pidfile(pid_path, port=9119)
    assert ok is True
    assert int(pid_path.read_text().strip().split("\n")[0]) == os.getpid()


def test_release_pidfile_removes_owned_file(tmp_path: Path):
    """_release_pidfile removes a file we own."""
    pid_path = tmp_path / "server.pid"
    pid_path.write_text(f"{os.getpid()}\n9119\n2026-04-06T00:00:00+00:00\n")

    _release_pidfile(pid_path)
    assert not pid_path.exists()


def test_release_pidfile_skips_foreign_file(tmp_path: Path):
    """_release_pidfile leaves files owned by another PID intact."""
    pid_path = tmp_path / "server.pid"
    pid_path.write_text("99999\n9119\n2026-04-06T00:00:00+00:00\n")

    _release_pidfile(pid_path)
    assert pid_path.exists()


def test_release_pidfile_noop_when_missing(tmp_path: Path):
    """_release_pidfile is safe when the file does not exist."""
    pid_path = tmp_path / "nope.pid"
    _release_pidfile(pid_path)  # must not raise
    assert not pid_path.exists()
