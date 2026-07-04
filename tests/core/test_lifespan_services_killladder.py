"""B081: the shutdown kill-ladder must work on Windows (no process groups).

On Windows os.killpg/os.getpgid don't exist (AttributeError) and signal.SIGKILL
is absent. Before the fix, the AttributeError from os.getpgid escaped the
(ProcessLookupError, OSError) except in _signal_process and the direct() fallback
never ran → Ollama orphaned on every shutdown. These tests simulate Windows from
a Mac by deleting those attributes and assert the direct per-process signal runs.
"""
import os
import signal

from core.lifespan_services import _signal_process, _stop_process


class _FakeProc:
    """Subprocess double; poll()=None (alive) so _stop_process enters the ladder."""

    def __init__(self, wait_raises=False):
        self.calls = []
        self._wait_raises = wait_raises
        self.pid = 12345

    def poll(self):
        return None

    def wait(self, timeout=None):
        self.calls.append(("wait", timeout))
        if self._wait_raises:
            raise TimeoutError("simulated timeout")
        return 0

    def send_signal(self, sig):
        self.calls.append(("send_signal", sig))

    def terminate(self):
        self.calls.append(("terminate",))

    def kill(self):
        self.calls.append(("kill",))


def _simulate_windows(monkeypatch):
    """Delete the POSIX-only process-group APIs (Windows has no killpg/getpgid)."""
    monkeypatch.delattr(os, "killpg", raising=False)
    monkeypatch.delattr(os, "getpgid", raising=False)


def test_signal_process_runs_direct_when_no_process_groups(monkeypatch):
    """Core of the Ollama-orphan bug: without killpg/getpgid, direct() must run."""
    _simulate_windows(monkeypatch)
    proc = _FakeProc()
    ran = []

    _signal_process(proc, signal.SIGINT, lambda: ran.append("direct"))

    assert ran == ["direct"]  # before the fix this never ran (AttributeError escaped)


def test_stop_process_signals_directly_on_windows(monkeypatch):
    """End-to-end: _stop_process delivers SIGINT directly (no killpg) on Windows."""
    _simulate_windows(monkeypatch)
    proc = _FakeProc()

    _stop_process(proc, "ollama")

    assert ("send_signal", signal.SIGINT) in proc.calls  # direct signal reached Ollama


def test_stop_process_full_ladder_without_sigkill(monkeypatch):
    """SIGKILL is absent on Windows; the ladder must reach process.kill() anyway."""
    _simulate_windows(monkeypatch)
    monkeypatch.delattr(signal, "SIGKILL", raising=False)
    proc = _FakeProc(wait_raises=True)  # force escalation to the last rung

    _stop_process(proc, "ollama")

    # Each rung's direct() ran; the SIGKILL rung fell back to process.kill().
    assert ("send_signal", signal.SIGINT) in proc.calls
    assert ("terminate",) in proc.calls
    assert ("kill",) in proc.calls


def test_signal_process_uses_killpg_on_posix(monkeypatch):
    """POSIX intact: with killpg/getpgid present, the group is signalled, not direct()."""
    if not hasattr(os, "killpg"):  # pragma: no cover - POSIX-only assertion
        import pytest

        pytest.skip("POSIX-only")
    killed = []
    monkeypatch.setattr(os, "getpgid", lambda pid: 4242)
    monkeypatch.setattr(os, "killpg", lambda pgid, sig: killed.append((pgid, sig)))
    proc = _FakeProc()
    ran = []

    _signal_process(proc, signal.SIGTERM, lambda: ran.append("direct"))

    assert killed == [(4242, signal.SIGTERM)]
    assert ran == []  # direct() must NOT run when killpg succeeds
