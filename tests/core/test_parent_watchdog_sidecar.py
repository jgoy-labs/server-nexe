"""F2.A11: tests for `_start_parent_watchdog` invocation in sidecar mode.

Validates the poll_interval parameter introduced for sidecar mode (2s default
via lifespan vs 30s default for standalone).

Context: el watchdog `_start_parent_watchdog` només s'invocava
des de `runner.main()`. En mode sidecar (Tauri llança `uvicorn core.app:app`),
`main()` mai s'executa → watchdog inactiu → si Tauri mor abrupte (Ctrl+C
terminal `pnpm tauri dev`, crash), el sidecar queda orfe consumint RAM i
mantenint el lock de Qdrant.

F2.A11 afegeix la crida al watchdog des de `lifespan.py:_startup_init` quan
`is_sidecar=True` (poll_interval=2s).
"""
import os
import threading

import pytest

from core.server.watchdog import start_parent_watchdog as _start_parent_watchdog


def test_watchdog_no_op_when_tray_pid_unset(monkeypatch, caplog):
    """No NEXE_TRAY_PID → return immediately, no thread spawned."""
    monkeypatch.delenv("NEXE_TRAY_PID", raising=False)
    started = []
    real_start = threading.Thread.start
    monkeypatch.setattr(threading.Thread, "start", lambda self: started.append(self))

    _start_parent_watchdog()

    assert started == []


def test_watchdog_no_op_with_invalid_tray_pid(monkeypatch, caplog):
    """Invalid NEXE_TRAY_PID (non-numeric) → log warning, no thread spawned."""
    monkeypatch.setenv("NEXE_TRAY_PID", "not_a_number")
    started = []
    monkeypatch.setattr(threading.Thread, "start", lambda self: started.append(self))

    with caplog.at_level("WARNING"):
        _start_parent_watchdog()

    assert started == []
    assert any("Invalid NEXE_TRAY_PID" in rec.message for rec in caplog.records)


def test_watchdog_spawns_daemon_thread_with_valid_pid(monkeypatch):
    """Valid NEXE_TRAY_PID → daemon thread started (not executed for the test)."""
    monkeypatch.setenv("NEXE_TRAY_PID", "12345")
    started = []
    monkeypatch.setattr(threading.Thread, "start", lambda self: started.append(self))

    _start_parent_watchdog(poll_interval=0.5)

    assert len(started) == 1
    assert started[0].daemon is True


def test_watchdog_accepts_custom_poll_interval(monkeypatch, caplog):
    """F2.A11: poll_interval kwarg respected (sidecar uses 2.0s vs default 30s)."""
    monkeypatch.setenv("NEXE_TRAY_PID", "12345")
    started = []
    monkeypatch.setattr(threading.Thread, "start", lambda self: started.append(self))

    with caplog.at_level("DEBUG"):
        _start_parent_watchdog(poll_interval=2.0)

    assert len(started) == 1
    assert any("poll 2.0s" in rec.message for rec in caplog.records)


def test_watchdog_default_poll_interval_is_30s(monkeypatch, caplog):
    """Backward compat: default poll_interval remains 30.0 (standalone tray)."""
    monkeypatch.setenv("NEXE_TRAY_PID", "12345")
    started = []
    monkeypatch.setattr(threading.Thread, "start", lambda self: started.append(self))

    with caplog.at_level("DEBUG"):
        _start_parent_watchdog()

    assert len(started) == 1
    assert any("poll 30.0s" in rec.message for rec in caplog.records)
