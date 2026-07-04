"""Cross-platform, Windows-safe process liveness helpers.

Factored out of ``core/server/watchdog.py`` so the single-instance PID guards
and the supervisor liveness probe share one correct implementation instead of
each re-deriving ``os.kill(pid, 0)``.

Platform note (Windows port): on Windows ``os.kill(pid, 0)`` is NOT a reliable
liveness probe. CPython routes signal 0 (== ``CTRL_C_EVENT``) to
``GenerateConsoleCtrlEvent`` rather than a process query, so without a console
it raises a generic ``OSError`` (a live process reads as dead) and with one it
returns silently (a dead process reads as alive). Either way the POSIX poll is
unusable. The Windows path below queries the process directly via
``OpenProcess(SYNCHRONIZE)`` + a non-blocking ``WaitForSingleObject(handle, 0)``
and never signals the target.

Policy: default to ALIVE on uncertainty (access-denied, unexpected wait code).
A liveness probe answers "is the previous instance still running?"; treating an
ambiguous answer as "dead" would wrongly reclaim a live instance's PID file and
spawn a second server (port clash + Qdrant lock contention). This is the
OPPOSITE of the watchdog's policy (which collapses uncertainty to "parent dead"
to avoid leaving orphans) — hence a separate helper, not a shared call. The
watchdog reuses ``_Kernel32`` and the constants from here, keeping its own
blocking wait and policy.
"""
from __future__ import annotations

import logging
import os
import sys
from typing import Optional

logger = logging.getLogger(__name__)

# Win32 constants (module-level so tests and watchdog can reference them;
# harmless on POSIX).
_SYNCHRONIZE = 0x00100000
_WAIT_OBJECT_0 = 0x00000000
_WAIT_TIMEOUT = 0x00000102
_INFINITE = 0xFFFFFFFF
_ERROR_ACCESS_DENIED = 5


class _Kernel32:  # pragma: no cover - exercised only on Windows
    """Typed kernel32 adapter.

    ctypes defaults every restype/argtype to C int (signed 32-bit). Kernel
    HANDLEs are documented to carry only 32 significant bits, so the naive
    binding *happens* to work, but it relies on sign-extension folklore and
    renders WAIT_FAILED as -1. Declaring the real signatures removes both
    hazards. `use_last_error=True` + `ctypes.get_last_error()` is the only
    reliable way to read the error code (a raw GetLastError() call can be
    clobbered by ctypes' own machinery between calls).
    """

    def __init__(self) -> None:
        import ctypes

        self._ctypes = ctypes
        dll = ctypes.WinDLL("kernel32", use_last_error=True)
        dll.OpenProcess.restype = ctypes.c_void_p
        dll.OpenProcess.argtypes = (ctypes.c_uint32, ctypes.c_int, ctypes.c_uint32)
        dll.WaitForSingleObject.restype = ctypes.c_uint32
        dll.WaitForSingleObject.argtypes = (ctypes.c_void_p, ctypes.c_uint32)
        dll.CloseHandle.restype = ctypes.c_int
        dll.CloseHandle.argtypes = (ctypes.c_void_p,)
        self._dll = dll

    def OpenProcess(self, access, inherit, pid):  # noqa: N802 - Win32 casing
        return self._dll.OpenProcess(access, inherit, pid)

    def WaitForSingleObject(self, handle, timeout):  # noqa: N802
        return self._dll.WaitForSingleObject(handle, timeout)

    def CloseHandle(self, handle):  # noqa: N802
        return self._dll.CloseHandle(handle)

    def GetLastError(self):  # noqa: N802
        return self._ctypes.get_last_error()


def _process_liveness_windows(pid: int, kernel32=None) -> Optional[bool]:
    """Windows liveness probe: OpenProcess + non-blocking WaitForSingleObject.

    Returns True (running), False (terminated) or None (uncertain: access
    denied / unexpected wait code). `kernel32` is injectable for tests; the
    default resolves the real DLL. Unlike the watchdog (which blocks on
    ``_INFINITE`` to detect parent death), this uses ``timeout=0`` for an
    instantaneous point-in-time check.
    """
    if kernel32 is None:  # pragma: no cover - exercised only on Windows
        kernel32 = _Kernel32()

    handle = kernel32.OpenProcess(_SYNCHRONIZE, False, pid)
    if not handle:
        err = kernel32.GetLastError()
        if err == _ERROR_ACCESS_DENIED:
            return None  # exists but not openable by us → uncertain
        # ERROR_INVALID_PARAMETER (87) and friends → no such process.
        return False
    try:
        result = kernel32.WaitForSingleObject(handle, 0)
    finally:
        kernel32.CloseHandle(handle)
    if result == _WAIT_OBJECT_0:
        return False  # signaled = process has terminated
    if result == _WAIT_TIMEOUT:
        return True  # not signaled = still running
    # WAIT_FAILED / anything unexpected → uncertain (see module docstring).
    logger.warning(
        "WaitForSingleObject(%d) returned 0x%X — liveness uncertain", pid, result
    )
    return None


def process_liveness(pid: int, kernel32=None) -> Optional[bool]:
    """Tri-state liveness — cross-platform, Windows-safe.

    Returns True (running), False (no such process), or None (uncertain: the
    process exists but we cannot determine its state — POSIX ``PermissionError``
    or Windows ``ERROR_ACCESS_DENIED``). Callers that only need a boolean should
    use :func:`process_is_alive`; callers that must distinguish "exists but
    inaccessible" (e.g. the supervisor endpoint's 500 vs 503) read the None.
    """
    if pid <= 0:
        # POSIX os.kill(0/-N, 0) signals process GROUPS, not a single process
        # (and would read as "alive"); a corrupt PID file with 0/negative must
        # mean "no such process" on every platform.
        return False
    if sys.platform == "win32":
        return _process_liveness_windows(pid, kernel32)
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return None
    return True


def process_is_alive(pid: int, kernel32=None) -> bool:
    """Return True if ``pid`` is a running process — cross-platform, Windows-safe.

    Uncertain cases (permission denied, unexpected wait code) resolve to ALIVE:
    a liveness guard must not reclaim a PID file it cannot prove is dead (see
    module docstring). Never uses ``os.kill`` on Windows.
    """
    return process_liveness(pid, kernel32) is not False
