"""Tests for _RamMonitor — background RAM polling for tray.py.

Verifies that:
- RAM polling runs in a background thread, never blocking the main thread
- Cached values are returned instantly
- Dead PIDs stop the polling loop
- Subprocess errors preserve the last valid cached value
- The monitor thread is a daemon (won't block process exit)
"""

import sys
import time
from pathlib import Path
from unittest.mock import MagicMock, patch

# Add project root to sys.path so we can import installer.tray
PROJECT_ROOT = Path(__file__).parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

# Mock rumps before importing tray (rumps is macOS-only)
sys.modules.setdefault("rumps", MagicMock())

from installer.tray import _RamMonitor  # noqa: E402


class TestRamMonitorCachesRam:
    """_RamMonitor updates cached_ram from subprocess output."""

    def test_monitor_caches_ram(self):
        mock_results = [
            MagicMock(returncode=0, stdout="  50000\n"),  # ps main
            MagicMock(returncode=1, stdout=""),            # pgrep (no children)
        ]

        with (
            patch("installer.tray.subprocess.run", side_effect=mock_results),
            patch("installer.tray.os.kill"),  # PID alive
        ):
            monitor = _RamMonitor(pid=12345, interval=0.1)
            time.sleep(0.3)
            monitor.stop()

        assert monitor.cached_ram == 50000 * 1024  # KB → bytes


class TestRamMonitorDeadPid:
    """Monitor stops polling when PID is dead."""

    def test_monitor_stops_on_dead_pid(self):
        with patch("installer.tray.os.kill", side_effect=ProcessLookupError):
            monitor = _RamMonitor(pid=99999, interval=0.1)
            time.sleep(0.3)

        # Thread should have exited
        assert not monitor._thread.is_alive()
        assert monitor.cached_ram == 0


class TestRamMonitorKeepsLastValue:
    """On subprocess error, cached_ram retains the last valid value."""

    def test_monitor_keeps_last_value_on_error(self):
        call_count = 0

        def side_effect(*args, **kwargs):
            nonlocal call_count
            call_count += 1
            if call_count <= 2:
                # First poll: success
                if call_count == 1:
                    return MagicMock(returncode=0, stdout="  30000\n")
                return MagicMock(returncode=1, stdout="")  # pgrep
            # Subsequent polls: failure
            raise OSError("subprocess failed")

        with (
            patch("installer.tray.subprocess.run", side_effect=side_effect),
            patch("installer.tray.os.kill"),
        ):
            monitor = _RamMonitor(pid=12345, interval=0.1)
            time.sleep(0.5)
            monitor.stop()

        # Should retain the value from the first successful read
        assert monitor.cached_ram == 30000 * 1024


class TestRamMonitorStopEvent:
    """stop() causes the thread to exit promptly."""

    def test_monitor_stop_event(self):
        with (
            patch("installer.tray.subprocess.run", return_value=MagicMock(returncode=1, stdout="")),
            patch("installer.tray.os.kill"),
        ):
            monitor = _RamMonitor(pid=12345, interval=60)  # long interval
            assert monitor._thread.is_alive()

            monitor.stop()
            monitor._thread.join(timeout=2)

            assert not monitor._thread.is_alive()


class TestRamMonitorDaemonThread:
    """Monitor thread is a daemon so it won't block process exit."""

    def test_monitor_thread_is_daemon(self):
        with (
            patch("installer.tray.subprocess.run", return_value=MagicMock(returncode=1, stdout="")),
            patch("installer.tray.os.kill"),
        ):
            monitor = _RamMonitor(pid=12345, interval=60)
            assert monitor._thread.daemon is True
            monitor.stop()


class TestRamMonitorTimeout:
    """Subprocess timeout is handled gracefully."""

    def test_monitor_handles_timeout(self):
        import subprocess as real_subprocess

        call_count = 0

        def side_effect(*args, **kwargs):
            nonlocal call_count
            call_count += 1
            if call_count <= 2:
                # First poll: success
                if call_count == 1:
                    return MagicMock(returncode=0, stdout="  20000\n")
                return MagicMock(returncode=1, stdout="")
            # Subsequent polls: timeout
            raise real_subprocess.TimeoutExpired(cmd="ps", timeout=2)

        with (
            patch("installer.tray.subprocess.run", side_effect=side_effect),
            patch("installer.tray.os.kill"),
        ):
            monitor = _RamMonitor(pid=12345, interval=0.1)
            time.sleep(0.5)
            monitor.stop()

        # Should retain value from first successful read despite timeouts
        assert monitor.cached_ram == 20000 * 1024


class TestUpdateStatsNoSubprocess:
    """_update_stats must never call subprocess.run directly."""

    def test_update_stats_source_has_no_subprocess(self):
        """Verify _update_stats source code does not contain subprocess.run.

        This is the critical safety check: the main-thread timer callback
        must never call subprocess.run, which would block the NSApplication
        event loop and freeze keyboard input on macOS.
        """
        tray_source = Path(__file__).parent.parent / "installer" / "tray.py"
        source = tray_source.read_text()

        # Extract _update_stats method body (from def to next def at same indent)
        import re
        match = re.search(
            r"(    def _update_stats\(self.*?\n)(.*?)(?=\n    def |\nclass |\n# ═)",
            source,
            re.DOTALL,
        )
        assert match, "Could not find _update_stats method in tray.py"
        method_body = match.group(0)

        assert "subprocess.run" not in method_body, (
            "_update_stats must not call subprocess.run — "
            "this blocks the main thread and freezes keyboard input"
        )
        assert "_get_process_ram" not in method_body, (
            "_update_stats must not call _get_process_ram — "
            "use _ram_monitor.cached_ram instead"
        )
