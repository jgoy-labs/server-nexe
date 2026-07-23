"""
WS7-04: kill_process_on_port must only kill server-nexe LISTENERS.

Guards under test (core/server/port_utils.py):
- lsof is restricted to TCP listeners (never clients connected to the port)
- each PID is identity-checked (_pid_is_nexe) before SIGTERM
- the return value is honest: True only if a nexe process was signalled
"""

import signal
import subprocess
from unittest.mock import MagicMock, patch

from core.server.port_utils import _pid_is_nexe, kill_process_on_port


def _completed(stdout: str, returncode: int = 0) -> subprocess.CompletedProcess:
    return subprocess.CompletedProcess(args=[], returncode=returncode, stdout=stdout, stderr="")


class TestPidIsNexe:

    @patch("core.server.port_utils.subprocess.run")
    def test_nexe_cmdline_matches(self, mock_run):
        mock_run.return_value = _completed("python -m core.app --port 9119\n")
        assert _pid_is_nexe(1234) is True

    @patch("core.server.port_utils.subprocess.run")
    def test_server_nexe_title_matches(self, mock_run):
        mock_run.return_value = _completed("server-nexe\n")
        assert _pid_is_nexe(1234) is True

    @patch("core.server.port_utils.subprocess.run")
    def test_foreign_process_does_not_match(self, mock_run):
        mock_run.return_value = _completed("/Applications/Safari.app/Contents/MacOS/Safari\n")
        assert _pid_is_nexe(1234) is False

    @patch("core.server.port_utils.subprocess.run", side_effect=OSError("ps missing"))
    def test_ps_failure_fails_closed(self, mock_run):
        assert _pid_is_nexe(1234) is False


class TestKillProcessOnPortGuard:

    @patch("core.server.port_utils.time.sleep")
    @patch("core.server.port_utils.os.kill")
    @patch("core.server.port_utils.subprocess.run")
    def test_lsof_restricted_to_listeners(self, mock_run, mock_kill, _sleep):
        """The lsof invocation must carry -sTCP:LISTEN (clients are never targets)."""
        mock_run.return_value = _completed("", returncode=1)
        kill_process_on_port(9119)
        lsof_args = mock_run.call_args_list[0].args[0]
        assert "-sTCP:LISTEN" in lsof_args

    @patch("core.server.port_utils.time.sleep")
    @patch("core.server.port_utils.os.kill")
    @patch("core.server.port_utils.subprocess.run")
    def test_foreign_listener_is_not_killed(self, mock_run, mock_kill, _sleep, caplog):
        """A non-nexe listener on the port is logged and left alone; returns False."""
        mock_run.side_effect = [
            _completed("4242\n"),                    # lsof → one listener PID
            _completed("/usr/bin/some-other-daemon\n"),  # ps → foreign cmdline
        ]
        with caplog.at_level("WARNING"):
            assert kill_process_on_port(9119) is False
        mock_kill.assert_not_called()
        assert "refusing to kill" in caplog.text

    @patch("core.server.port_utils.time.sleep")
    @patch("core.server.port_utils.os.kill")
    @patch("core.server.port_utils.subprocess.run")
    def test_nexe_listener_is_killed(self, mock_run, mock_kill, _sleep):
        """A nexe listener is SIGTERMed and the call returns True."""
        mock_run.side_effect = [
            _completed("4242\n"),                          # lsof
            _completed("python -m core.app --port 9119\n"),  # ps → nexe
        ]
        assert kill_process_on_port(9119) is True
        mock_kill.assert_called_once_with(4242, signal.SIGTERM)

    @patch("core.server.port_utils.time.sleep")
    @patch("core.server.port_utils.os.kill", side_effect=ProcessLookupError)
    @patch("core.server.port_utils.subprocess.run")
    def test_dead_nexe_pid_counts_as_success(self, mock_run, mock_kill, _sleep):
        """If the nexe PID vanished before SIGTERM, the port is already free →
        True (no spurious sys.exit(1) in the headless caller — race regression)."""
        mock_run.side_effect = [
            _completed("4242\n"),
            _completed("server-nexe\n"),
        ]
        assert kill_process_on_port(9119) is True
