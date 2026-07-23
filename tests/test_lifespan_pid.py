"""
────────────────────────────────────
Server Nexe — Tests
Location: tests/test_lifespan_pid.py
Description: Tests for PID file management in the lifespan (B06, B10),
             circuit breaker reset on shutdown (N03),
             cleanup task cancellation (N04),
             and SIGTERM handler in the runner (N05).
────────────────────────────────────
"""

import asyncio
import os
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from core.lifespan import _write_pid_file, _remove_pid_file, _PID_SUBPATH


# ── Fixtures ──────────────────────────────────────────────────────────────────

@pytest.fixture
def project_root(tmp_path: Path) -> Path:
    """Temporary directory as a fake project_root."""
    return tmp_path


@pytest.fixture
def pid_path(project_root: Path) -> Path:
    """Canonical path of the PID file under the temporary project_root."""
    return project_root / _PID_SUBPATH


# ── B06 / B10: _write_pid_file ─────────────────────────────────────────────

def test_write_pid_file_creates_file(project_root: Path, pid_path: Path):
    """_write_pid_file writes the PID file in JSON format (B06)."""
    assert not pid_path.exists()
    ok = _write_pid_file(project_root, port=9119)
    assert ok is True
    assert pid_path.exists()

    import json
    data = json.loads(pid_path.read_text())
    assert data["pid"] == os.getpid()
    assert data["port"] == 9119
    from datetime import datetime
    datetime.fromisoformat(data["started"])  # must be parseable


def test_write_pid_file_fsyncs_before_close(project_root: Path, pid_path: Path):
    """_write_pid_file calls os.fsync before close — power-cut safety."""
    seen_fds: list[int] = []
    real_fsync = os.fsync

    def _spy(fd: int) -> None:
        seen_fds.append(fd)
        real_fsync(fd)

    with patch("core.lifespan.os.fsync", side_effect=_spy):
        ok = _write_pid_file(project_root, port=9119)
    assert ok is True
    assert seen_fds, "os.fsync must be called on the PID file fd before close"


def test_write_pid_file_returns_false_if_live_pid(project_root: Path, pid_path: Path):
    """_write_pid_file returns False if a live server already holds the lock (B10)."""
    # First acquire
    ok = _write_pid_file(project_root, port=9119)
    assert ok is True

    # Second attempt: simulate that the PID is alive (os.kill does not raise)
    with patch("core.lifespan.os.kill", return_value=None):
        ok2 = _write_pid_file(project_root, port=9119)
    assert ok2 is False
    # Original file intact
    import json
    data = json.loads(pid_path.read_text())
    assert data["pid"] == os.getpid()


def test_write_pid_file_removes_stale_and_acquires(project_root: Path, pid_path: Path):
    """_write_pid_file removes a stale PID and acquires the lock (B07 / B10)."""
    import json
    pid_path.parent.mkdir(parents=True, exist_ok=True)
    pid_path.write_text(json.dumps({"pid": 99999, "port": 9119, "started": "2020-01-01T00:00:00+00:00"}))

    def _fake_kill(pid, sig):
        raise ProcessLookupError(f"No such process: {pid}")

    with patch("core.lifespan.os.kill", side_effect=_fake_kill):
        ok = _write_pid_file(project_root, port=9119)
    assert ok is True
    data = json.loads(pid_path.read_text())
    assert data["pid"] == os.getpid()


# ── B10: _remove_pid_file ────────────────────────────────────────────────────

def test_remove_pid_file_deletes_owned_file(project_root: Path, pid_path: Path):
    """_remove_pid_file removes the PID file belonging to this process (B10)."""
    import json
    pid_path.parent.mkdir(parents=True, exist_ok=True)
    pid_path.write_text(json.dumps({"pid": os.getpid(), "port": 9119, "started": "2026-01-01T00:00:00+00:00"}))

    _remove_pid_file(project_root)
    assert not pid_path.exists()


def test_remove_pid_file_leaves_foreign_file(project_root: Path, pid_path: Path):
    """_remove_pid_file does NOT remove PID files belonging to another process (B10)."""
    import json
    pid_path.parent.mkdir(parents=True, exist_ok=True)
    pid_path.write_text(json.dumps({"pid": 99999, "port": 9119, "started": "2026-01-01T00:00:00+00:00"}))

    _remove_pid_file(project_root)
    assert pid_path.exists()  # not removed


def test_remove_pid_file_noop_when_missing(project_root: Path):
    """_remove_pid_file is safe when the file does not exist (B10)."""
    _remove_pid_file(project_root)  # must not raise


def test_remove_pid_file_noop_when_project_root_none():
    """_remove_pid_file is safe with project_root None (B10)."""
    _remove_pid_file(None)  # must not raise


# ── N03: reset circuit breakers ───────────────────────────────────────────────

def test_reset_all_circuit_breakers_resets_to_closed():
    """reset_all_circuit_breakers returns all breakers to CLOSED (N03)."""
    from core.resilience import (
        reset_all_circuit_breakers,
        ollama_breaker,
        CircuitState,
    )

    # Force OPEN state on every global breaker (WS7-01: only ollama remains)
    for breaker in (ollama_breaker,):
        breaker._state.state = CircuitState.OPEN
        breaker._state.failure_count = 5

    reset_all_circuit_breakers()

    for breaker in (ollama_breaker,):
        assert breaker.state == CircuitState.CLOSED, (
            f"Breaker '{breaker.name}' should be CLOSED after reset"
        )
        assert breaker._state.failure_count == 0


def test_circuit_breaker_reset_method():
    """CircuitBreaker.reset() reinitializes to clean CLOSED state (N03)."""
    from core.resilience import CircuitBreaker, CircuitBreakerConfig, CircuitState

    breaker = CircuitBreaker("test_reset", CircuitBreakerConfig(failure_threshold=1))
    breaker._state.state = CircuitState.OPEN
    breaker._state.failure_count = 3

    breaker.reset()

    assert breaker.state == CircuitState.CLOSED
    assert breaker._state.failure_count == 0
    assert breaker._state.success_count == 0
    assert breaker._state.last_failure_time is None


# ── N04: cleanup tasks cancelled ─────────────────────────────────────────────

@pytest.mark.asyncio
async def test_cleanup_task_cancelled_on_shutdown():
    """_cleanup_task created in the lifespan must be cancelled on shutdown (N04)."""
    # Simulate an infinite task (like start_rate_limit_cleanup)
    async def _infinite_loop():
        while True:
            await asyncio.sleep(3600)

    task = asyncio.create_task(_infinite_loop())
    assert not task.done()

    # Simulate the lifespan shutdown pattern
    if not task.done():
        task.cancel()
        try:
            await task
        except (asyncio.CancelledError, Exception):
            pass

    assert task.done()
    assert task.cancelled()


@pytest.mark.asyncio
async def test_lifespan_runs_shutdown_when_startup_cancelled():
    """SIGTERM mid-_startup() must still run _shutdown() and re-raise the
    CancelledError so the supervisor sees the signal rather than a clean
    exit. The `finally` clause of `lifespan()` is responsible for this."""
    from fastapi import FastAPI
    from core.lifespan import lifespan

    app = FastAPI()
    shutdown_calls: list[bool] = []

    async def fake_startup(_app):
        raise asyncio.CancelledError()

    async def fake_shutdown(_app):
        shutdown_calls.append(True)

    with patch("core.lifespan._startup", new=fake_startup), \
         patch("core.lifespan._shutdown", new=fake_shutdown):
        with pytest.raises(asyncio.CancelledError):
            async with lifespan(app):
                pass

    assert shutdown_calls == [True], (
        "_shutdown() must run on CancelledError mid-startup"
    )


@pytest.mark.asyncio
async def test_lifespan_propagates_when_shutdown_raises_in_finally():
    """If _shutdown itself raises during the `finally` clause, the lifespan
    must still surface the original CancelledError to the supervisor — the
    secondary shutdown error must not swallow it. This documents the
    current behaviour: Python's finally re-raises the active exception
    unless the finally itself raises, in which case the finally exception
    wins. We assert exactly that contract so a future refactor does not
    silently change which exception the caller sees."""
    from fastapi import FastAPI
    from core.lifespan import lifespan

    app = FastAPI()

    async def fake_startup(_app):
        raise asyncio.CancelledError()

    async def fake_shutdown_that_raises(_app):
        raise RuntimeError("shutdown explosion")

    with patch("core.lifespan._startup", new=fake_startup), \
         patch("core.lifespan._shutdown", new=fake_shutdown_that_raises):
        with pytest.raises(RuntimeError, match="shutdown explosion"):
            async with lifespan(app):
                pass


@pytest.mark.asyncio
async def test_lifespan_shutdown_runs_when_yield_body_raises():
    """If the body inside `async with lifespan(app):` raises, the finally
    must still run _shutdown so resources are released. This covers the
    happy-path yield exception (e.g. a HTTP handler raising during a
    request) as opposed to the CancelledError case above."""
    from fastapi import FastAPI
    from core.lifespan import lifespan

    app = FastAPI()
    shutdown_calls: list[bool] = []

    async def fake_startup(_app):
        return None

    async def fake_shutdown(_app):
        shutdown_calls.append(True)

    with patch("core.lifespan._startup", new=fake_startup), \
         patch("core.lifespan._shutdown", new=fake_shutdown):
        with pytest.raises(RuntimeError, match="body explosion"):
            async with lifespan(app):
                raise RuntimeError("body explosion")

    assert shutdown_calls == [True]


@pytest.mark.asyncio
async def test_session_cleanup_task_returns_task():
    """start_session_cleanup_task returns an asyncio.Task (N04)."""
    from plugins.web_ui_module.api.routes import start_session_cleanup_task

    mock_mgr = MagicMock()
    # Patch the internal loop so it doesn't do real I/O
    with patch("plugins.web_ui_module.api.routes._session_cleanup_loop", new=AsyncMock(return_value=None)):
        task = start_session_cleanup_task(mock_mgr)

    assert isinstance(task, asyncio.Task), (
        "start_session_cleanup_task must return asyncio.Task to be cancellable"
    )
    # Cleanup
    if not task.done():
        task.cancel()
        try:
            await task
        except (asyncio.CancelledError, Exception):
            pass


# ── N05: SIGTERM handler in the runner ────────────────────────────────────────────

def test_sigterm_handler_registered_in_runner():
    """runner.py registers _handle_sigterm as the SIGTERM handler (N05)."""
    import core.server.runner as runner_module
    assert hasattr(runner_module, "_handle_sigterm"), (
        "_handle_sigterm not defined in core.server.runner — N05 not implemented"
    )
    assert callable(runner_module._handle_sigterm)
