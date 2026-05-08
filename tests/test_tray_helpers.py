"""
────────────────────────────────────
Server Nexe
Author: Jordi Goy
Location: tests/test_tray_helpers.py
Description: Unit tests for tray launch helper functions extracted from core/server/runner.py.

www.jgoy.net · https://server-nexe.org
────────────────────────────────────
"""

import os
import signal
import sys
from pathlib import Path
from unittest.mock import MagicMock, call, patch

import pytest

from core.server.runner import (
    _is_tray_already_running,
    _is_tray_supported,
    _kill_stale_tray,
    _maybe_launch_tray,
)


class TestIsTrayAlreadyRunning:
    """Test _is_tray_already_running helper."""

    def test_returns_true_when_pid_set(self):
        """Returns True when NEXE_TRAY_PID is in the environment."""
        with patch.dict(os.environ, {"NEXE_TRAY_PID": "1234"}):
            assert _is_tray_already_running() is True

    def test_returns_false_when_pid_not_set(self):
        """Returns False when NEXE_TRAY_PID is absent."""
        with patch.dict(os.environ):
            os.environ.pop("NEXE_TRAY_PID", None)
            assert _is_tray_already_running() is False


class TestIsTraySupported:
    """Test _is_tray_supported helper."""

    def test_returns_false_on_non_macos(self):
        """Returns False immediately on non-macOS platforms."""
        with patch("sys.platform", "linux"):
            assert _is_tray_supported() is False

    def test_returns_false_on_docker(self):
        """Returns False when NEXE_DOCKER env var is set."""
        with patch("sys.platform", "darwin"), \
             patch.dict(os.environ, {"NEXE_DOCKER": "1", "CONTAINER": "", "NEXE_NO_TRAY": ""}):
            assert _is_tray_supported() is False

    def test_returns_false_on_container(self):
        """Returns False when CONTAINER env var is set."""
        with patch("sys.platform", "darwin"), \
             patch.dict(os.environ, {"NEXE_DOCKER": "", "CONTAINER": "1", "NEXE_NO_TRAY": ""}):
            assert _is_tray_supported() is False

    def test_returns_false_when_no_tray_set(self):
        """Returns False when user opts out via NEXE_NO_TRAY."""
        with patch("sys.platform", "darwin"), \
             patch.dict(os.environ, {"NEXE_DOCKER": "", "CONTAINER": "", "NEXE_NO_TRAY": "1"}):
            assert _is_tray_supported() is False

    def test_returns_false_when_rumps_not_installed(self):
        """Returns False when rumps cannot be imported."""
        with patch("sys.platform", "darwin"), \
             patch.dict(os.environ, {"NEXE_DOCKER": "", "CONTAINER": "", "NEXE_NO_TRAY": ""}), \
             patch.dict(sys.modules, {"rumps": None}):
            assert _is_tray_supported() is False

    def test_returns_true_when_all_conditions_met(self):
        """Returns True when macOS, no blocking env vars, and rumps is available."""
        with patch("sys.platform", "darwin"), \
             patch.dict(os.environ), \
             patch.dict(sys.modules, {"rumps": MagicMock()}):
            os.environ.pop("NEXE_DOCKER", None)
            os.environ.pop("CONTAINER", None)
            os.environ.pop("NEXE_NO_TRAY", None)
            assert _is_tray_supported() is True


class TestKillStaleTray:
    """Test _kill_stale_tray helper."""

    def test_no_stale_pids_no_kill(self):
        """When pgrep finds nothing, os.kill is never called."""
        mock_result = MagicMock()
        mock_result.returncode = 1
        mock_result.stdout = ""
        with patch("subprocess.run", return_value=mock_result), \
             patch("os.kill") as mock_kill:
            _kill_stale_tray()
            mock_kill.assert_not_called()

    def test_stale_pid_receives_sigterm_and_sigkill(self):
        """When pgrep finds a stale PID, both SIGTERM and SIGKILL are sent."""
        def fake_pgrep(cmd, **kwargs):
            result = MagicMock()
            if "installer.tray" in cmd:
                result.returncode = 0
                result.stdout = "9999\n"
            else:
                result.returncode = 1
                result.stdout = ""
            return result

        with patch("subprocess.run", side_effect=fake_pgrep), \
             patch("os.kill") as mock_kill, \
             patch("time.sleep"):
            _kill_stale_tray()

        kill_args = [c.args for c in mock_kill.call_args_list]
        assert (9999, signal.SIGTERM) in kill_args
        assert (9999, signal.SIGKILL) in kill_args


class TestMaybeLaunchTray:
    """Integration tests for _maybe_launch_tray orchestration."""

    def test_skips_all_when_already_running(self):
        """If NEXE_TRAY_PID is set, _is_tray_supported is never called."""
        with patch("core.server.runner._is_tray_already_running", return_value=True), \
             patch("core.server.runner._is_tray_supported") as mock_supported:
            _maybe_launch_tray()
            mock_supported.assert_not_called()

    def test_skips_kill_and_launch_when_not_supported(self):
        """If not supported, _kill_stale_tray and _launch_tray_process are not called."""
        with patch("core.server.runner._is_tray_already_running", return_value=False), \
             patch("core.server.runner._is_tray_supported", return_value=False), \
             patch("core.server.runner._kill_stale_tray") as mock_kill, \
             patch("core.server.runner._launch_tray_process") as mock_launch:
            _maybe_launch_tray()
            mock_kill.assert_not_called()
            mock_launch.assert_not_called()

    def test_calls_kill_and_launch_with_project_root(self):
        """When supported, delegates to _kill_stale_tray and _launch_tray_process."""
        project_root = Path("/fake/root")
        with patch("core.server.runner._is_tray_already_running", return_value=False), \
             patch("core.server.runner._is_tray_supported", return_value=True), \
             patch("core.server.runner._kill_stale_tray") as mock_kill, \
             patch("core.server.runner._launch_tray_process") as mock_launch:
            _maybe_launch_tray(project_root)
            mock_kill.assert_called_once()
            mock_launch.assert_called_once_with(project_root)
