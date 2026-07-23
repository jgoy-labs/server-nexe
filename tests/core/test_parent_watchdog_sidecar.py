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

Windows port (B1): the POSIX probe `os.kill(pid, 0)` is TerminateProcess on
Windows (it would KILL the Tauri parent), so the Windows path blocks on
WaitForSingleObject instead. Those tests inject a fake kernel32.
"""
import os
import signal
import sys
import threading

import pytest

from core.server import watchdog as watchdog_mod
from core.server.watchdog import (
    _INFINITE,
    _SYNCHRONIZE,
    _WAIT_OBJECT_0,
    _terminate_self,
    _wait_parent_exit_posix,
    _wait_parent_exit_windows,
    start_parent_watchdog as _start_parent_watchdog,
)


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


# ── B1 Windows port: platform-specific helpers ──────────────────────────────


class _FakeKernel32:
    """Minimal kernel32 double for _wait_parent_exit_windows."""

    def __init__(self, open_result=1234, wait_result=_WAIT_OBJECT_0, last_error=0):
        self.open_result = open_result
        self.wait_result = wait_result
        self.last_error = last_error
        self.calls = []

    def OpenProcess(self, access, inherit, pid):  # noqa: N802 - Win32 casing
        self.calls.append(("OpenProcess", access, inherit, pid))
        return self.open_result

    def WaitForSingleObject(self, handle, timeout):  # noqa: N802
        self.calls.append(("WaitForSingleObject", handle, timeout))
        return self.wait_result

    def CloseHandle(self, handle):  # noqa: N802
        self.calls.append(("CloseHandle", handle))
        return 1

    def GetLastError(self):  # noqa: N802
        return self.last_error


def test_posix_wait_returns_when_parent_lookup_fails(monkeypatch):
    """ProcessLookupError from the signal-0 probe → parent is gone, return."""
    probes = []

    def fake_kill(pid, sig):
        probes.append((pid, sig))
        raise ProcessLookupError

    monkeypatch.setattr(os, "kill", fake_kill)

    _wait_parent_exit_posix(4242, poll_interval=0.01)

    assert probes == [(4242, 0)]


def test_posix_wait_treats_permission_error_as_alive(monkeypatch):
    """PermissionError = parent alive; keep polling until it disappears."""
    outcomes = [PermissionError, ProcessLookupError]

    def fake_kill(pid, sig):
        exc = outcomes.pop(0)
        raise exc

    monkeypatch.setattr(os, "kill", fake_kill)
    monkeypatch.setattr(watchdog_mod.time, "sleep", lambda s: None)

    _wait_parent_exit_posix(4242, poll_interval=0.01)

    assert outcomes == []  # both probes consumed


# ── NEXE-SRV-WS7-05: POSIX PID-reuse revalidation ──────────────────────────


def test_posix_wait_returns_when_identity_changes(monkeypatch):
    """PID stays 'alive' (os.kill OK) but its creation time changed → the PID
    was recycled onto another process → treat parent as gone and return."""
    monkeypatch.setattr(os, "kill", lambda pid, sig: None)  # PID number is live
    monkeypatch.setattr(watchdog_mod.time, "sleep", lambda s: None)
    # First revalidation reports a DIFFERENT creation time than the anchor.
    monkeypatch.setattr(watchdog_mod, "_parent_create_time", lambda pid: 2222.0)

    # anchor identity = 1111.0; live probe now yields 2222.0 → reuse detected
    _wait_parent_exit_posix(4242, poll_interval=0.01, identity=1111.0)  # must return


def test_posix_wait_keeps_polling_while_identity_matches(monkeypatch):
    """Same creation time = same process → keep polling until the PID vanishes."""
    kill_calls = []

    def fake_kill(pid, sig):
        kill_calls.append(pid)
        if len(kill_calls) >= 3:
            raise ProcessLookupError  # parent finally exits
        # else: alive

    monkeypatch.setattr(os, "kill", fake_kill)
    monkeypatch.setattr(watchdog_mod.time, "sleep", lambda s: None)
    # Identity is stable across polls → no false reuse trigger.
    monkeypatch.setattr(watchdog_mod, "_parent_create_time", lambda pid: 1111.0)

    _wait_parent_exit_posix(4242, poll_interval=0.01, identity=1111.0)

    assert len(kill_calls) == 3  # polled until ProcessLookupError, no early exit


def test_posix_wait_without_identity_ignores_create_time(monkeypatch):
    """identity=None (psutil unavailable) → fall back to bare signal-0 poll,
    never consult creation time (no regression vs the original behaviour)."""
    def boom(pid):  # pragma: no cover - must not be called
        raise AssertionError("_parent_create_time must not run when identity is None")

    monkeypatch.setattr(watchdog_mod, "_parent_create_time", boom)
    outcomes = [None, ProcessLookupError]  # alive once, then gone

    def fake_kill(pid, sig):
        outcome = outcomes.pop(0)
        if outcome is not None:
            raise outcome

    monkeypatch.setattr(os, "kill", fake_kill)
    monkeypatch.setattr(watchdog_mod.time, "sleep", lambda s: None)

    _wait_parent_exit_posix(4242, poll_interval=0.01)  # identity defaults to None

    assert outcomes == []


def test_parent_create_time_none_when_psutil_missing(monkeypatch):
    """No psutil → identity token is None (fail-open anchor)."""
    monkeypatch.setattr(watchdog_mod, "psutil", None)
    assert watchdog_mod._parent_create_time(4242) is None


def test_parent_create_time_none_on_lookup_failure(monkeypatch):
    """psutil raises (process gone / access denied) → None, never propagates."""
    class _FakePsutil:
        @staticmethod
        def Process(pid):  # noqa: N802
            raise RuntimeError("NoSuchProcess")

    monkeypatch.setattr(watchdog_mod, "psutil", _FakePsutil)
    assert watchdog_mod._parent_create_time(4242) is None


def test_parent_create_time_returns_value(monkeypatch):
    """Happy path: psutil supplies the creation time verbatim."""
    class _FakeProc:
        def create_time(self):
            return 98765.0

    class _FakePsutil:
        @staticmethod
        def Process(pid):  # noqa: N802
            return _FakeProc()

    monkeypatch.setattr(watchdog_mod, "psutil", _FakePsutil)
    assert watchdog_mod._parent_create_time(4242) == 98765.0


def test_windows_wait_parent_death_detected():
    """WAIT_OBJECT_0 → parent gone (True) and the handle is closed."""
    fake = _FakeKernel32(open_result=777, wait_result=_WAIT_OBJECT_0)

    assert _wait_parent_exit_windows(4242, kernel32=fake) is True
    assert ("OpenProcess", _SYNCHRONIZE, False, 4242) in fake.calls
    assert ("WaitForSingleObject", 777, _INFINITE) in fake.calls
    assert ("CloseHandle", 777) in fake.calls


def test_windows_wait_openprocess_null_means_parent_gone(caplog):
    """OpenProcess NULL (parent dead or inaccessible) → safe side: True."""
    fake = _FakeKernel32(open_result=0, last_error=87)  # ERROR_INVALID_PARAMETER

    with caplog.at_level("WARNING"):
        assert _wait_parent_exit_windows(4242, kernel32=fake) is True

    assert any("OpenProcess(4242) failed" in rec.message for rec in caplog.records)
    assert not any(call[0] == "WaitForSingleObject" for call in fake.calls)


def test_windows_wait_failed_disables_watchdog(caplog):
    """WAIT_FAILED → cannot monitor: return False (server keeps running)."""
    fake = _FakeKernel32(open_result=777, wait_result=0xFFFFFFFF)

    with caplog.at_level("WARNING"):
        assert _wait_parent_exit_windows(4242, kernel32=fake) is False

    assert ("CloseHandle", 777) in fake.calls
    assert any("parent watchdog disabled" in rec.message for rec in caplog.records)


def test_terminate_self_posix_sends_sigterm(monkeypatch):
    """POSIX: SIGTERM to self (uvicorn handler does the graceful shutdown)."""
    monkeypatch.setattr(watchdog_mod.sys, "platform", "linux")
    sent = []
    monkeypatch.setattr(os, "kill", lambda pid, sig: sent.append((pid, sig)))

    _terminate_self()

    assert sent == [(os.getpid(), signal.SIGTERM)]


def test_terminate_self_windows_raises_then_forces_exit(monkeypatch):
    """Windows: signal.raise_signal(SIGTERM) first, hard os._exit after the grace."""
    monkeypatch.setattr(watchdog_mod.sys, "platform", "win32")
    raised = []
    slept = []
    exited = []
    monkeypatch.setattr(watchdog_mod.signal, "raise_signal", lambda sig: raised.append(sig))
    monkeypatch.setattr(watchdog_mod.time, "sleep", lambda s: slept.append(s))
    monkeypatch.setattr(os, "_exit", lambda code: exited.append(code))

    _terminate_self()

    assert raised == [signal.SIGTERM]
    assert slept == [watchdog_mod._WIN_GRACE_SECONDS]
    assert exited == [1]


def test_terminate_self_windows_never_uses_os_kill(monkeypatch):
    """Regression guard: os.kill(self) on Windows would be TerminateProcess."""
    monkeypatch.setattr(watchdog_mod.sys, "platform", "win32")
    monkeypatch.setattr(watchdog_mod.signal, "raise_signal", lambda sig: None)
    monkeypatch.setattr(watchdog_mod.time, "sleep", lambda s: None)
    monkeypatch.setattr(os, "_exit", lambda code: None)

    def forbidden_kill(pid, sig):  # pragma: no cover - only on regression
        raise AssertionError("os.kill must not run on the Windows suicide path")

    monkeypatch.setattr(os, "kill", forbidden_kill)

    _terminate_self()


def test_watchdog_thread_windows_disabled_when_unmonitorable(monkeypatch):
    """Dispatcher: Windows wait returning False → no _terminate_self call."""
    monkeypatch.setenv("NEXE_TRAY_PID", "4242")
    monkeypatch.setattr(watchdog_mod.sys, "platform", "win32")
    monkeypatch.setattr(watchdog_mod, "_wait_parent_exit_windows", lambda pid: False)
    terminated = []
    monkeypatch.setattr(watchdog_mod, "_terminate_self", lambda: terminated.append(1))

    threads = []
    real_init = threading.Thread.start

    def capture_start(self):
        threads.append(self)
        real_init(self)

    monkeypatch.setattr(threading.Thread, "start", capture_start)

    _start_parent_watchdog()
    threads[0].join(timeout=5)

    assert terminated == []


@pytest.mark.skipif(
    sys.platform != "win32",
    reason="real kernel32 integration — runs on the Windows VM/CI",
)
class TestWindowsRealKernel32:
    """Integration with the real typed kernel32 adapter (no fakes).

    Review feedback (external review 2026-06-12): the fake-based tests cannot catch
    ctypes signature bugs (HANDLE truncation, signed WAIT_FAILED), so the
    adapter must also be exercised against the real DLL.
    """

    def test_wait_returns_true_when_watched_process_dies(self):
        import subprocess

        child = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(2)"])
        try:
            assert _wait_parent_exit_windows(child.pid) is True
        finally:
            child.wait(timeout=10)

    def test_openprocess_on_finished_process_reports_parent_gone(self):
        import subprocess

        child = subprocess.Popen([sys.executable, "-c", "pass"])
        child.wait(timeout=10)
        # Either OpenProcess fails (PID released) or the wait returns
        # immediately (process object still alive via our Popen handle):
        # both paths must report "parent gone".
        assert _wait_parent_exit_windows(child.pid) is True


def test_watchdog_thread_windows_terminates_when_parent_dies(monkeypatch):
    """Dispatcher: Windows wait returning True → _terminate_self runs."""
    monkeypatch.setenv("NEXE_TRAY_PID", "4242")
    monkeypatch.setattr(watchdog_mod.sys, "platform", "win32")
    monkeypatch.setattr(watchdog_mod, "_wait_parent_exit_windows", lambda pid: True)
    terminated = []
    monkeypatch.setattr(watchdog_mod, "_terminate_self", lambda: terminated.append(1))

    threads = []
    real_start = threading.Thread.start

    def capture_start(self):
        threads.append(self)
        real_start(self)

    monkeypatch.setattr(threading.Thread, "start", capture_start)

    _start_parent_watchdog()
    threads[0].join(timeout=5)

    assert terminated == [1]
