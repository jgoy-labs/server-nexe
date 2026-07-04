"""B081: Windows-safe process liveness helper (core/server/process_utils.py).

POSIX paths exercise the real os.kill tri-state; Windows paths inject a fake
kernel32 (the real DLL only exists on the VM/CI, covered by a skipif class).
"""
import os
import sys

import pytest

from core.server import process_utils as pu
from core.server.process_utils import (
    _ERROR_ACCESS_DENIED,
    _WAIT_OBJECT_0,
    _WAIT_TIMEOUT,
    process_is_alive,
    process_liveness,
)

_ERROR_INVALID_PARAMETER = 87


# ── POSIX tri-state ─────────────────────────────────────────────────────────


def test_posix_dead_process_is_false(monkeypatch):
    monkeypatch.setattr(pu.sys, "platform", "linux")
    monkeypatch.setattr(os, "kill", lambda pid, sig: (_ for _ in ()).throw(ProcessLookupError))
    assert process_liveness(4242) is False
    assert process_is_alive(4242) is False


def test_posix_permission_is_uncertain_but_alive(monkeypatch):
    """PermissionError = exists but not signalable → None (uncertain) yet alive."""
    monkeypatch.setattr(pu.sys, "platform", "linux")
    monkeypatch.setattr(os, "kill", lambda pid, sig: (_ for _ in ()).throw(PermissionError))
    assert process_liveness(4242) is None
    assert process_is_alive(4242) is True


def test_posix_running_process_is_true(monkeypatch):
    monkeypatch.setattr(pu.sys, "platform", "linux")
    calls = []
    monkeypatch.setattr(os, "kill", lambda pid, sig: calls.append((pid, sig)))
    assert process_liveness(4242) is True
    assert process_is_alive(4242) is True
    assert calls == [(4242, 0), (4242, 0)]  # signal 0 only, no real signal


def test_posix_real_self_is_alive():
    assert process_is_alive(os.getpid()) is True


def test_pid_zero_and_negative_are_dead():
    # pid <= 0 must never read as alive (POSIX os.kill(0/-N, 0) = group signal).
    assert process_liveness(0) is False
    assert process_liveness(-1) is False
    assert process_is_alive(0) is False
    assert process_is_alive(-1) is False


# ── Windows path (fake kernel32) ────────────────────────────────────────────


class _FakeKernel32:
    """kernel32 double for the non-blocking liveness probe (timeout=0)."""

    def __init__(self, open_result=777, wait_result=_WAIT_TIMEOUT, last_error=0):
        self.open_result = open_result
        self.wait_result = wait_result
        self.last_error = last_error
        self.calls = []

    def OpenProcess(self, access, inherit, pid):  # noqa: N802
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


@pytest.fixture
def _win(monkeypatch):
    """Force the Windows branch and forbid os.kill (would be TerminateProcess)."""
    monkeypatch.setattr(pu.sys, "platform", "win32")

    def _forbidden(pid, sig):  # pragma: no cover - only trips on regression
        raise AssertionError("os.kill must not run on the Windows liveness path")

    monkeypatch.setattr(os, "kill", _forbidden)


def test_windows_wait_timeout_means_alive(_win):
    fake = _FakeKernel32(open_result=777, wait_result=_WAIT_TIMEOUT)
    assert process_liveness(4242, kernel32=fake) is True
    assert process_is_alive(4242, kernel32=fake) is True
    # uses a NON-blocking wait (timeout 0) and always closes the handle.
    assert ("WaitForSingleObject", 777, 0) in fake.calls
    assert ("CloseHandle", 777) in fake.calls


def test_windows_wait_object_0_means_dead(_win):
    fake = _FakeKernel32(open_result=777, wait_result=_WAIT_OBJECT_0)
    assert process_liveness(4242, kernel32=fake) is False
    assert process_is_alive(4242, kernel32=fake) is False
    assert ("CloseHandle", 777) in fake.calls


def test_windows_access_denied_is_uncertain(_win):
    """OpenProcess NULL + ERROR_ACCESS_DENIED → None (exists, inaccessible)."""
    fake = _FakeKernel32(open_result=0, last_error=_ERROR_ACCESS_DENIED)
    assert process_liveness(4242, kernel32=fake) is None
    assert process_is_alive(4242, kernel32=fake) is True
    # never waits when the handle is NULL.
    assert not any(c[0] == "WaitForSingleObject" for c in fake.calls)


def test_windows_invalid_parameter_means_dead(_win):
    """OpenProcess NULL + ERROR_INVALID_PARAMETER → no such process → False."""
    fake = _FakeKernel32(open_result=0, last_error=_ERROR_INVALID_PARAMETER)
    assert process_liveness(4242, kernel32=fake) is False
    assert process_is_alive(4242, kernel32=fake) is False


def test_windows_wait_failed_is_uncertain(_win):
    """WAIT_FAILED (0xFFFFFFFF) → uncertain (None) but is_alive stays conservative."""
    fake = _FakeKernel32(open_result=777, wait_result=0xFFFFFFFF)
    assert process_liveness(4242, kernel32=fake) is None
    assert process_is_alive(4242, kernel32=fake) is True
    assert ("CloseHandle", 777) in fake.calls


@pytest.mark.skipif(
    sys.platform != "win32",
    reason="real kernel32 integration — runs on the Windows VM/CI",
)
class TestWindowsRealKernel32:
    """Non-destructive proof against the real DLL (the os.kill(pid,0) hazard
    only manifests on Windows): probing a live child must NOT kill it."""

    def test_live_child_reported_alive_and_survives(self):
        import subprocess

        child = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(3)"])
        try:
            assert process_is_alive(child.pid) is True
            # The probe must be side-effect-free: the child is still running.
            assert child.poll() is None
        finally:
            child.terminate()
            child.wait(timeout=10)

    def test_finished_child_reported_dead(self):
        import subprocess

        child = subprocess.Popen([sys.executable, "-c", "pass"])
        child.wait(timeout=10)
        # The Popen object still holds the process handle, so the PID is not
        # recycled: on Windows WaitForSingleObject sees the terminated process,
        # on POSIX wait() reaped the zombie → os.kill(pid, 0) raises. Both → dead.
        assert process_is_alive(child.pid) is False
