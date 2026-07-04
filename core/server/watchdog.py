"""Parent process watchdog — monitors the parent process PID (tray/Tauri).

If the parent dies (Force Quit, Ctrl+C in the `pnpm tauri dev` terminal, crash),
the sidecar terminates itself with SIGTERM to avoid orphans consuming RAM, ports and
locks (for example, Qdrant's fcntl lock at /Users/<user>/.nexe/data/vectors).

This module is extracted from `core/server/runner.py` (F2.A11) to avoid import
cycles when `core/lifespan.py` needs to invoke it in sidecar mode.
`runner.py` keeps re-exporting the function for backward compatibility.

Platform note (Windows port): on Windows, ``os.kill(pid, 0)`` is NOT a
liveness probe — CPython maps any signal outside CTRL_C_EVENT/CTRL_BREAK_EVENT
to ``TerminateProcess(handle, sig)``, so the POSIX-style poll would *kill the
Tauri parent* on its first iteration. The Windows path below blocks on
``WaitForSingleObject`` over a ``SYNCHRONIZE`` handle instead (instant death
detection, zero polling, and the open handle anchors the PID against reuse).
"""
from __future__ import annotations

import logging
import os
import signal
import sys
import threading
import time

# Win32 constants + typed kernel32 adapter live in process_utils (shared with
# the liveness probe); re-exported here so existing references keep working.
from core.server.process_utils import (
    _INFINITE,
    _SYNCHRONIZE,
    _WAIT_OBJECT_0,
    _Kernel32,
)

logger = logging.getLogger(__name__)

# Grace period after asking uvicorn for a graceful shutdown on Windows before
# force-exiting. Storage is SQLite/SQLCipher in WAL mode (crash-safe), so the
# hard fallback loses at most in-flight responses, never data integrity.
_WIN_GRACE_SECONDS = 15.0


def _wait_parent_exit_posix(parent_pid: int, poll_interval: float) -> None:
    """Block until the parent process exits (POSIX poll, signal 0)."""
    while True:
        # Check immediately on first iteration (no initial sleep window where
        # a parent that died right after spawn would leave us orphaned).
        try:
            os.kill(parent_pid, 0)  # Signal 0 = check if alive, no actual signal
        except ProcessLookupError:
            return
        except PermissionError:
            pass  # Process exists but we can't signal it — still alive
        time.sleep(poll_interval)


def _wait_parent_exit_windows(parent_pid: int, kernel32=None) -> bool:
    """Block until the parent process exits (Windows, WaitForSingleObject).

    Returns True when the parent is gone (caller must shut the server down),
    False when monitoring is impossible (caller leaves the server running —
    the Job Object KILL_ON_JOB_CLOSE on the Tauri side still covers orphans).

    `kernel32` is injectable for tests; the default resolves the real DLL.

    Note on return codes: a process handle can only yield WAIT_OBJECT_0 or
    WAIT_FAILED here (WAIT_ABANDONED exists only for mutexes, WAIT_TIMEOUT
    only with a finite timeout); anything unexpected lands in the safe
    "cannot monitor" branch below.
    """
    if kernel32 is None:  # pragma: no cover - exercised only on Windows
        kernel32 = _Kernel32()

    handle = kernel32.OpenProcess(_SYNCHRONIZE, False, parent_pid)
    if not handle:
        # ERROR_INVALID_PARAMETER → parent already dead. ERROR_ACCESS_DENIED
        # would be unexpected for a same-user Tauri parent; in both cases the
        # safe side is shutting down rather than risking an orphan.
        logger.warning(
            "OpenProcess(%d) failed (err=%d) — assuming parent is gone",
            parent_pid,
            kernel32.GetLastError(),
        )
        return True
    try:
        result = kernel32.WaitForSingleObject(handle, _INFINITE)
    finally:
        kernel32.CloseHandle(handle)
    if result == _WAIT_OBJECT_0:
        return True
    logger.warning(
        "WaitForSingleObject on parent PID %d returned 0x%X — parent watchdog disabled",
        parent_pid,
        result,
    )
    return False


def _terminate_self() -> None:
    """Shut this server down because the parent died.

    POSIX: SIGTERM to self → uvicorn's signal handler drains connections and
    runs the lifespan shutdown.

    Windows: ``os.kill(os.getpid(), SIGTERM)`` would be TerminateProcess on
    *ourselves* (hard kill, no cleanup). Prefer ``signal.raise_signal(SIGTERM)``,
    which goes through the CRT and reaches the Python-level handler uvicorn
    installed in the main thread → graceful shutdown. If the loop has not
    wound down within the grace period (handler missing, shutdown wedged),
    force-exit — WAL storage keeps the data crash-safe.
    """
    if sys.platform == "win32":
        try:
            signal.raise_signal(signal.SIGTERM)
        except (ValueError, OSError) as exc:
            logger.warning("signal.raise_signal(SIGTERM) failed (%s) — hard exit", exc)
            os._exit(1)
        time.sleep(_WIN_GRACE_SECONDS)
        logger.warning(
            "Server still alive %.0fs after SIGTERM — forcing exit", _WIN_GRACE_SECONDS
        )
        os._exit(1)
    else:
        os.kill(os.getpid(), signal.SIGTERM)


def start_parent_watchdog(poll_interval: float = 30.0) -> None:
    """If launched from the tray app (or Tauri sidecar), monitor that the
    parent is still alive.

    When NEXE_TRAY_PID is set, a daemon thread watches that process. If the
    tray dies (e.g. Force Quit, `pnpm tauri dev` killed with Ctrl+C, Tauri
    crash), the server shuts itself down to avoid orphaned processes
    consuming RAM and holding Qdrant locks.

    poll_interval applies to the POSIX poll only (30s standalone tray, 2s in
    sidecar mode via `core/lifespan.py`, F2.A11). The Windows path blocks on
    WaitForSingleObject, so detection is instant regardless of the value.
    """
    tray_pid_str = os.environ.get("NEXE_TRAY_PID")
    if not tray_pid_str:
        return

    try:
        tray_pid = int(tray_pid_str)
    except ValueError:
        logger.warning("Invalid NEXE_TRAY_PID=%r — parent watchdog disabled", tray_pid_str)
        return

    def _watchdog() -> None:
        if sys.platform == "win32":
            if not _wait_parent_exit_windows(tray_pid):
                return  # cannot monitor — leave the server running
        else:
            _wait_parent_exit_posix(tray_pid, poll_interval)
        logger.info(
            "Tray process (PID %d) no longer running — shutting down server",
            tray_pid,
        )
        _terminate_self()

    t = threading.Thread(target=_watchdog, daemon=True)
    t.start()
    logger.debug(
        "Parent watchdog started — monitoring tray PID %d (poll %.1fs)",
        tray_pid,
        poll_interval,
    )
