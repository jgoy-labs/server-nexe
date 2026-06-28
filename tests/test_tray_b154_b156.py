"""
────────────────────────────────────
Server Nexe
Author: Jordi Goy
Location: tests/test_tray_b154_b156.py
Description:
  B154 — _wait_server_ready must not report ICON_RUNNING after the readiness
         timeout when the process has died (or server_process is None after a
         concurrent Stop). A live-but-slow process must still resolve to Running.
  B156 — _start_server must not leak the server.log file handle: it must close a
         stale handle before reopening (re-entry) and release the just-opened
         handle if subprocess.Popen fails.

  rumps is macOS-only and is mocked elsewhere as a bare MagicMock, which makes
  NexeTray (a rumps.App subclass) unusable. We load a private copy of
  installer.tray with a REAL rumps.App base, then restore sys.modules so the
  rest of the suite is unaffected.

www.jgoy.net · https://server-nexe.org
────────────────────────────────────
"""
import importlib
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

PROJECT_ROOT = Path(__file__).parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))


def _load_real_tray_module():
    """Import a fresh installer.tray with a real rumps.App base, then restore
    sys.modules so global state is untouched (other tests keep their module)."""
    saved_rumps = sys.modules.get("rumps")
    saved_tray = sys.modules.get("installer.tray")
    try:
        rmock = MagicMock()
        rmock.App = type("_RealApp", (), {"__init__": (lambda self, *a, **k: None)})
        sys.modules["rumps"] = rmock
        sys.modules.pop("installer.tray", None)
        return importlib.import_module("installer.tray")
    finally:
        if saved_tray is not None:
            sys.modules["installer.tray"] = saved_tray
        else:
            sys.modules.pop("installer.tray", None)
        if saved_rumps is not None:
            sys.modules["rumps"] = saved_rumps
        else:
            sys.modules.pop("rumps", None)


tray = _load_real_tray_module()
NexeTray = tray.NexeTray
ICON_RUNNING = tray.ICON_RUNNING
ICON_STOPPED = tray.ICON_STOPPED


def _bare_tray():
    t = NexeTray.__new__(NexeTray)
    t.strings = {}
    t.icon = None
    t.status_item = MagicMock()
    t.toggle_item = MagicMock()
    t._ram_monitor = None
    t.server_process = None
    t._server_log_fh = None
    return t


# ── B154 — _wait_server_ready post-timeout state ─────────────────────────────

class TestWaitServerReadyTimeout:
    def _run_past_timeout(self, t):
        fake_time = MagicMock()
        fake_time.time.side_effect = [1000.0, 9999.0, 9999.0]  # start, while-check → skip loop
        with patch.object(tray, "time", fake_time), patch.object(tray, "_RamMonitor", MagicMock()):
            t._wait_server_ready()

    def test_dead_process_after_timeout_is_stopped(self):
        """B154: the process died around the timeout → must NOT claim Running."""
        proc = MagicMock()
        proc.poll.return_value = 1  # exited
        proc.pid = 4321
        t = _bare_tray()
        t.server_process = proc
        self._run_past_timeout(t)
        assert t.icon == ICON_STOPPED

    def test_none_process_after_timeout_is_stopped(self):
        """B154: concurrent Stop left server_process=None → must NOT claim Running."""
        t = _bare_tray()
        t.server_process = None
        self._run_past_timeout(t)
        assert t.icon == ICON_STOPPED

    def test_live_process_after_timeout_is_running(self):
        """No over-blocking: a slow-but-alive process still resolves to Running."""
        proc = MagicMock()
        proc.poll.return_value = None  # alive
        proc.pid = 4321
        t = _bare_tray()
        t.server_process = proc
        self._run_past_timeout(t)
        assert t.icon == ICON_RUNNING


# ── B156 — _start_server log file-handle hygiene ─────────────────────────────

class TestStartServerHandleHygiene:
    def _prep_root(self, tmp_path):
        venv = tmp_path / "venv" / "bin"
        venv.mkdir(parents=True)
        (venv / "python").write_text("#!/bin/sh\n")
        (tmp_path / "storage" / "logs").mkdir(parents=True)
        return tmp_path

    def test_single_failed_start_releases_handle(self, tmp_path):
        """B156: if Popen fails, the just-opened log handle is released (not leaked)."""
        root = self._prep_root(tmp_path)
        t = _bare_tray()
        with (
            patch.object(tray, "PROJECT_ROOT", root),
            patch.object(tray.subprocess, "Popen", side_effect=OSError("boom")),
            patch.object(tray.threading, "Thread", MagicMock()),
        ):
            with pytest.raises(OSError):
                t._start_server()
        assert t._server_log_fh is None

    def test_no_handle_leak_across_failed_then_ok_start(self, tmp_path):
        """B156: a failed start followed by a successful one must not leak the
        first handle (closed before/at the second start)."""
        root = self._prep_root(tmp_path)
        t = _bare_tray()

        opened = []
        real_open = open

        def _spy_open(*a, **k):
            f = real_open(*a, **k)
            opened.append(f)
            return f

        with (
            patch.object(tray, "PROJECT_ROOT", root),
            patch.object(tray.threading, "Thread", MagicMock()),
            patch("builtins.open", side_effect=_spy_open),
            patch.object(tray.subprocess, "Popen", side_effect=[OSError("boom"), MagicMock()]),
        ):
            with pytest.raises(OSError):
                t._start_server()   # first: Popen fails
            t._start_server()       # second: Popen succeeds

        assert len(opened) >= 2, opened
        assert opened[0].closed is True, "first log handle leaked (not closed)"
