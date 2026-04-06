"""
────────────────────────────────────
Server Nexe
Location: installer/tray_monitor.py
Description: Background RAM monitor for the Nexe tray app.
             Extracted from tray.py to reduce file size.
────────────────────────────────────
"""

import os
import subprocess
import threading


def format_bytes(b):
    """Format bytes as human-readable string."""
    if b < 1024 ** 2:
        return f"{b / 1024:.0f} KB"
    if b < 1024 ** 3:
        return f"{b / (1024 ** 2):.1f} MB"
    return f"{b / (1024 ** 3):.2f} GB"


def format_uptime(seconds):
    """Format seconds as human-readable uptime."""
    seconds = int(seconds)
    if seconds < 60:
        return f"{seconds}s"
    minutes = seconds // 60
    if minutes < 60:
        return f"{minutes}m {seconds % 60:02d}s"
    hours = minutes // 60
    mins = minutes % 60
    if hours < 24:
        return f"{hours}h {mins:02d}m"
    days = hours // 24
    return f"{days}d {hours % 24}h {mins:02d}m"


class RamMonitor:
    """Background thread that polls process RAM without blocking the main thread.

    The main thread (NSApplication event loop / rumps) must never call
    subprocess.run — doing so blocks keyboard event delivery on macOS.
    This class runs all subprocess calls in a daemon thread and exposes
    a cached_ram property that can be read instantly from any thread.
    """

    def __init__(self, pid, interval=10):
        self._pid = pid
        self._interval = interval
        self._cached_ram = 0
        self._lock = threading.Lock()
        self._stop_event = threading.Event()
        self._thread = threading.Thread(target=self._poll_loop, daemon=True)
        self._thread.start()

    @property
    def cached_ram(self):
        with self._lock:
            return self._cached_ram

    def stop(self):
        self._stop_event.set()

    def _poll_loop(self):
        while not self._stop_event.is_set():
            try:
                os.kill(self._pid, 0)
            except ProcessLookupError:
                break
            except PermissionError:
                pass  # alive but can't signal

            ram = self._read_ram()
            if ram > 0:
                with self._lock:
                    self._cached_ram = ram

            self._stop_event.wait(self._interval)

    def _read_ram(self):
        """Read RSS of process + children. Runs in background thread only."""
        try:
            result = subprocess.run(
                ["ps", "-o", "rss=", "-p", str(self._pid)],
                capture_output=True, text=True, timeout=2,
            )
            if result.returncode != 0 or not result.stdout.strip():
                return 0
            rss_kb = int(result.stdout.strip())
            children = subprocess.run(
                ["pgrep", "-P", str(self._pid)],
                capture_output=True, text=True, timeout=2,
            )
            if children.returncode == 0:
                for child_pid in children.stdout.strip().split("\n"):
                    if child_pid.strip():
                        child_rss = subprocess.run(
                            ["ps", "-o", "rss=", "-p", child_pid.strip()],
                            capture_output=True, text=True, timeout=2,
                        )
                        if child_rss.returncode == 0 and child_rss.stdout.strip():
                            rss_kb += int(child_rss.stdout.strip())
            return rss_kb * 1024
        except Exception:
            return 0
