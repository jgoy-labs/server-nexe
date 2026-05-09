"""
────────────────────────────────────
Server Nexe
Author: Jordi Goy
Location: tests/test_sidecar_port_guard.py
Description: P1-SIDECAR-PORT — NEXE_SIDECAR=1 prevents kill_process_on_port
             from running and triggers sys.exit(1) instead.

www.jgoy.net · https://server-nexe.org
────────────────────────────────────
"""

import pytest
from unittest.mock import patch, MagicMock

from core.server.runner import _handle_port_conflict


class TestSidecarPortGuard:
    def test_sidecar_refuses_kill(self):
        """NEXE_SIDECAR=1 + headless + port occupied → no kill, sys.exit(1)."""
        with patch("core.server.runner.kill_process_on_port") as mock_kill:
            with pytest.raises(SystemExit) as exc_info:
                _handle_port_conflict(
                    host="127.0.0.1",
                    port=8000,
                    headless=True,
                    sidecar=True,
                    i18n=None,
                )
            assert exc_info.value.code == 1
            mock_kill.assert_not_called()

    def test_headless_non_sidecar_kills(self):
        """headless=True + sidecar=False → kill_process_on_port IS called."""
        with patch("core.server.runner.kill_process_on_port", return_value=True) as mock_kill:
            _handle_port_conflict(
                host="127.0.0.1",
                port=8000,
                headless=True,
                sidecar=False,
                i18n=None,
            )
            mock_kill.assert_called_once_with(8000)

    def test_headless_kill_fails_exits(self):
        """headless + sidecar=False + kill fails → sys.exit(1)."""
        with patch("core.server.runner.kill_process_on_port", return_value=False):
            with pytest.raises(SystemExit) as exc_info:
                _handle_port_conflict(
                    host="127.0.0.1",
                    port=8000,
                    headless=True,
                    sidecar=False,
                    i18n=None,
                )
            assert exc_info.value.code == 1

    def test_sidecar_flag_overrides_headless(self):
        """sidecar=True takes priority even if headless=False."""
        with patch("core.server.runner.kill_process_on_port") as mock_kill:
            with pytest.raises(SystemExit):
                _handle_port_conflict(
                    host="127.0.0.1",
                    port=8000,
                    headless=False,
                    sidecar=True,
                    i18n=None,
                )
            mock_kill.assert_not_called()
