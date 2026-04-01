"""
────────────────────────────────────
Server Nexe
Location: installer/tray.py
Description: macOS menu bar app for controlling the Nexe server.
             Shows start/stop, RAM usage, and uptime.
             Uses rumps for native macOS NSStatusBar integration.
             Orchestrator — delegates to submodules.
────────────────────────────────────
"""

import os
import subprocess
import sys
import threading
import time
import webbrowser
from pathlib import Path

from .tray_translations import T, _detect_lang

try:
    import rumps
    _HAS_RUMPS = True
except ImportError:
    _HAS_RUMPS = False
    # Stub so class definition doesn't fail on Linux
    class _RumpsStub:
        class App:
            def __init__(self, *a, **kw): pass
            def run(self): pass
        @staticmethod
        def clicked(*a, **kw):
            def decorator(f): return f
            return decorator
        @staticmethod
        def timer(interval):
            def decorator(f): return f
            return decorator
    rumps = _RumpsStub()

# ═══════════════════════════════════════════════════════════════════════════
# PATHS
# ═══════════════════════════════════════════════════════════════════════════
PROJECT_ROOT = Path(__file__).parent.parent.resolve()
ICON_DIR = Path(__file__).parent / "tray_icons"
ICON_RUNNING = str(ICON_DIR / "icon_running.png") if (ICON_DIR / "icon_running.png").exists() else None
ICON_STOPPED = str(ICON_DIR / "icon_stopped.png") if (ICON_DIR / "icon_stopped.png").exists() else None

# Server config
SERVER_PORT = 9119
WEB_UI_URL = f"http://127.0.0.1:{SERVER_PORT}/ui"


def _format_bytes(b):
    """Format bytes as human-readable string."""
    if b < 1024 ** 2:
        return f"{b / 1024:.0f} KB"
    if b < 1024 ** 3:
        return f"{b / (1024 ** 2):.1f} MB"
    return f"{b / (1024 ** 3):.2f} GB"


def _format_uptime(seconds):
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


# ═══════════════════════════════════════════════════════════════════════════
# RAM MONITOR — background thread, never blocks main event loop
# ═══════════════════════════════════════════════════════════════════════════
class _RamMonitor:
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


# ═══════════════════════════════════════════════════════════════════════════
# TRAY APP
# ═══════════════════════════════════════════════════════════════════════════
class NexeTray(rumps.App):
    """macOS menu bar app for controlling the Nexe server."""

    def __init__(self, attach_pid=None):
        self._attach_pid = attach_pid
        self.lang = _detect_lang()
        self.strings = T.get(self.lang, T["ca"])

        super().__init__(
            name="Nexe",
            icon=ICON_STOPPED,
            template=None,
            quit_button=None,
        )

        # Server state
        self.server_process = None
        self.server_start_time = None
        self._server_log_path = PROJECT_ROOT / "storage" / "logs" / "server.log"
        self._server_log_fh = None
        self._ram_monitor = None

        # Menu items
        self.status_item = rumps.MenuItem(self.strings["status_stopped"])
        self.status_item.set_callback(None)

        self.toggle_item = rumps.MenuItem(
            self.strings["start"],
            callback=self._toggle_server,
        )

        self.ram_item = rumps.MenuItem(self.strings["ram"].format(ram="—"))
        self.ram_item.set_callback(None)

        self.uptime_item = rumps.MenuItem(self.strings["uptime"].format(uptime="—"))
        self.uptime_item.set_callback(None)

        self.open_ui_item = rumps.MenuItem(
            self.strings["open_ui"],
            callback=self._open_web_ui,
        )

        self.open_logs_item = rumps.MenuItem(
            self.strings["open_logs"],
            callback=self._open_logs,
        )

        self.quit_item = rumps.MenuItem(
            self.strings["quit"],
            callback=self._quit,
        )

        # Settings submenu
        self.settings_menu = rumps.MenuItem(self.strings["settings"])

        self.website_item = rumps.MenuItem(
            self.strings["website"],
            callback=self._open_website,
        )
        self.donate_item = rumps.MenuItem(
            self.strings["donate"],
            callback=self._open_donate,
        )
        self.uninstall_item = rumps.MenuItem(
            self.strings["uninstall"],
            callback=self._uninstall,
        )
        self.settings_menu[self.strings["website"]] = self.website_item
        self.settings_menu[self.strings["donate"]] = self.donate_item
        self.settings_menu[self.strings["uninstall"]] = self.uninstall_item

        # Build menu
        self.menu = [
            self.status_item,
            None,
            self.toggle_item,
            self.open_ui_item,
            self.open_logs_item,
            None,
            self.ram_item,
            self.uptime_item,
            None,
            self.settings_menu,
            None,
            self.quit_item,
        ]

        # Update timer (every 5 seconds — RAM polling is in background thread)
        self._timer = rumps.Timer(self._update_stats, 5)
        self._timer.start()

        # If attaching to an already-running server, show as running immediately
        if self._attach_pid:
            self.server_start_time = time.time()
            self.icon = ICON_RUNNING
            self.status_item.title = self.t("status_running")
            self.toggle_item.title = self.t("stop")
            self._ram_monitor = _RamMonitor(self._attach_pid)

    def t(self, key, **kwargs):
        """Get translated string."""
        s = self.strings.get(key, key)
        if kwargs:
            s = s.format(**kwargs)
        return s

    # ── Server control ────────────────────────────────────────────────────

    def _toggle_server(self, sender):
        if self.server_process and self.server_process.poll() is None:
            self._stop_server()
        else:
            self._start_server()

    def _start_server(self):
        self.toggle_item.title = self.t("starting")

        venv_python = PROJECT_ROOT / "venv" / "bin" / "python"
        if not venv_python.exists():
            rumps.alert(
                title="Nexe",
                message="Python venv not found. Please run the installer first.",
            )
            self.toggle_item.title = self.t("start")
            return

        tray_pid = os.getpid()
        env = {
            **os.environ,
            "PYTHONUNBUFFERED": "1",
            "NEXE_TRAY_PID": str(tray_pid),
        }
        log_dir = PROJECT_ROOT / "storage" / "logs"
        log_dir.mkdir(parents=True, exist_ok=True)
        self._server_log_path = log_dir / "server.log"
        self._server_log_fh = open(self._server_log_path, "a")

        self.server_process = subprocess.Popen(
            [str(venv_python), "-m", "core.app"],
            cwd=str(PROJECT_ROOT),
            env=env,
            stdout=self._server_log_fh,
            stderr=subprocess.STDOUT,
        )
        self.server_start_time = time.time()

        self.status_item.title = self.t("starting")
        threading.Thread(target=self._wait_server_ready, daemon=True).start()

    def _wait_server_ready(self):
        import urllib.request
        import urllib.error

        blink_on = True
        max_wait = 20
        start = time.time()

        while time.time() - start < max_wait:
            self.icon = ICON_RUNNING if blink_on else ICON_STOPPED
            blink_on = not blink_on

            try:
                req = urllib.request.urlopen(
                    f"http://localhost:{SERVER_PORT}/health", timeout=2
                )
                if req.status == 200:
                    break
            except (urllib.error.URLError, OSError, ValueError):
                pass

            if self.server_process and self.server_process.poll() is not None:
                self.icon = ICON_STOPPED
                self.status_item.title = self.t("status_stopped")
                self.toggle_item.title = self.t("start")
                return

            time.sleep(0.5)

        self.icon = ICON_RUNNING
        self.status_item.title = self.t("status_running")
        self.toggle_item.title = self.t("stop")
        if self.server_process:
            self._ram_monitor = _RamMonitor(self.server_process.pid)

    def _stop_ram_monitor(self):
        if self._ram_monitor:
            self._ram_monitor.stop()
            self._ram_monitor = None

    def _stop_server(self):
        self._stop_ram_monitor()

        # Attach mode: server is external, send SIGTERM
        if self._attach_pid:
            self.toggle_item.title = self.t("stopping")
            try:
                import signal
                os.kill(self._attach_pid, signal.SIGTERM)
            except (ProcessLookupError, PermissionError):
                pass
            self._attach_pid = None
            self.server_start_time = None
            self.icon = ICON_STOPPED
            self.status_item.title = self.t("status_stopped")
            self.toggle_item.title = self.t("start")
            self.ram_item.title = self.t("ram", ram="—")
            self.uptime_item.title = self.t("uptime", uptime="—")
            return

        if not self.server_process:
            return

        self.toggle_item.title = self.t("stopping")

        try:
            self.server_process.terminate()
            self.server_process.wait(timeout=10)
        except subprocess.TimeoutExpired:
            try:
                self.server_process.kill()
                self.server_process.wait(timeout=5)
            except Exception:
                pass

        if self._server_log_fh:
            try:
                self._server_log_fh.close()
            except Exception:
                pass
            self._server_log_fh = None

        self.server_process = None
        self.server_start_time = None

        self.icon = ICON_STOPPED
        self.status_item.title = self.t("status_stopped")
        self.toggle_item.title = self.t("start")
        self.ram_item.title = self.t("ram", ram="—")
        self.uptime_item.title = self.t("uptime", uptime="—")

    # ── Stats update ──────────────────────────────────────────────────────

    def _update_stats(self, _timer):
        # Attach mode: monitor external server PID
        if self._attach_pid:
            try:
                os.kill(self._attach_pid, 0)  # check alive
            except ProcessLookupError:
                # Server died externally
                self._stop_ram_monitor()
                self._attach_pid = None
                self.server_start_time = None
                self.icon = ICON_STOPPED
                self.status_item.title = self.t("status_stopped")
                self.toggle_item.title = self.t("start")
                self.ram_item.title = self.t("ram", ram="—")
                self.uptime_item.title = self.t("uptime", uptime="—")
                return
            except PermissionError:
                pass  # alive but can't signal

            mon = self._ram_monitor
            ram_bytes = mon.cached_ram if mon else 0
            if ram_bytes > 0:
                self.ram_item.title = self.t("ram", ram=_format_bytes(ram_bytes))
            if self.server_start_time:
                elapsed = time.time() - self.server_start_time
                self.uptime_item.title = self.t("uptime", uptime=_format_uptime(elapsed))
            return

        if not self.server_process or self.server_process.poll() is not None:
            if self.server_process and self.server_process.poll() is not None:
                self._stop_ram_monitor()
                self.server_process = None
                self.server_start_time = None
                self.icon = ICON_STOPPED
                self.status_item.title = self.t("status_stopped")
                self.toggle_item.title = self.t("start")
                self.ram_item.title = self.t("ram", ram="—")
                self.uptime_item.title = self.t("uptime", uptime="—")
            return

        mon = self._ram_monitor
        ram_bytes = mon.cached_ram if mon else 0
        if ram_bytes > 0:
            self.ram_item.title = self.t("ram", ram=_format_bytes(ram_bytes))

        if self.server_start_time:
            elapsed = time.time() - self.server_start_time
            self.uptime_item.title = self.t("uptime", uptime=_format_uptime(elapsed))

    # ── Actions ───────────────────────────────────────────────────────────

    def _open_web_ui(self, _sender):
        webbrowser.open(WEB_UI_URL)

    def _open_logs(self, _sender):
        if self._server_log_path.exists():
            subprocess.Popen(["open", str(self._server_log_path)])
        else:
            log_dir = PROJECT_ROOT / "storage" / "logs"
            log_dir.mkdir(parents=True, exist_ok=True)
            subprocess.Popen(["open", str(log_dir)])

    def _open_website(self, _sender):
        webbrowser.open("https://server-nexe.com")

    def _open_donate(self, _sender):
        webbrowser.open("https://server-nexe.com/donate")

    def _uninstall(self, _sender):
        """Uninstall Nexe — delegates to tray_uninstaller."""
        from .tray_uninstaller import perform_uninstall

        removed, failed = perform_uninstall(PROJECT_ROOT, self.t, self._stop_server)
        if removed is None:
            return  # User cancelled

        # Build details report
        details = ""
        if removed:
            details += self.t("uninstall_removed") + "\n• " + "\n• ".join(removed)
        if failed:
            if details:
                details += "\n\n"
            details += self.t("uninstall_failed") + "\n• " + "\n• ".join(failed)

        if failed:
            rumps.alert(
                title=self.t("uninstall_title"),
                message=self.t("uninstall_partial", details=details),
            )
        else:
            rumps.alert(
                title=self.t("uninstall_title"),
                message=self.t("uninstall_done", details=details),
            )

        rumps.quit_application()

    def _quit(self, _sender):
        self._stop_ram_monitor()
        if not self._attach_pid:
            # Normal mode: tray owns the server, stop it
            self._stop_server()
        # Attach mode: just quit tray, leave server running in terminal
        if self._server_log_fh:
            try:
                self._server_log_fh.close()
            except Exception:
                pass
            self._server_log_fh = None
        rumps.quit_application()


# ═══════════════════════════════════════════════════════════════════════════
# ENTRY POINT
# ═══════════════════════════════════════════════════════════════════════════
def main():
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--autostart", action="store_true",
                        help="Engega el servidor automaticament al obrir")
    parser.add_argument("--attach", action="store_true",
                        help="Attach to an already-running server (don't start one)")
    parser.add_argument("--server-pid", type=int, default=None,
                        help="PID of the running server process to monitor")
    args = parser.parse_args()

    app = NexeTray(attach_pid=args.server_pid if args.attach else None)
    if args.autostart and not args.attach:
        def auto():
            import time
            import urllib.request
            import urllib.error
            time.sleep(0.5)
            app._start_server()
            for _ in range(40):  # 20s timeout (M1 8GB pot trigar)
                try:
                    req = urllib.request.urlopen(
                        f"http://localhost:{SERVER_PORT}/health", timeout=2
                    )
                    if req.status == 200:
                        import webbrowser
                        webbrowser.open(WEB_UI_URL)
                        break
                except (urllib.error.URLError, OSError, ValueError):
                    pass
                time.sleep(0.5)
        threading.Thread(target=auto, daemon=True).start()
    app.run()


if __name__ == "__main__":
    if not _HAS_RUMPS:
        print("Nexe tray app requires macOS (rumps). Skipping on this platform.")
        sys.exit(0)
    main()
