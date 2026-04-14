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

import json
import os
import subprocess
import sys
import threading
import time
import webbrowser
from pathlib import Path

from .tray_monitor import RamMonitor as _RamMonitor, format_bytes as _format_bytes, format_uptime as _format_uptime
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


NS_STATUS_WINDOW_LEVEL = 25


def _front_alert(title=None, message=None, ok=None, cancel=None, other=None, **_):
    """NSAlert always-on-top (assumeix _ForegroundContext ja actiu)."""
    try:
        from AppKit import NSAlert, NSAlertStyleWarning
    except Exception:
        kwargs = {}
        if title is not None: kwargs["title"] = title
        if message is not None: kwargs["message"] = message
        if ok is not None: kwargs["ok"] = ok
        if cancel is not None: kwargs["cancel"] = cancel
        if other is not None: kwargs["other"] = other
        return rumps.alert(**kwargs)

    alert = NSAlert.alloc().init()
    if title is not None:
        alert.setMessageText_(str(title))
    if message is not None:
        alert.setInformativeText_(str(message))
    alert.setAlertStyle_(NSAlertStyleWarning)

    alert.addButtonWithTitle_(str(ok) if ok is not None else "OK")
    if cancel is not None:
        alert.addButtonWithTitle_(str(cancel))
    if other is not None:
        alert.addButtonWithTitle_(str(other))

    window = alert.window()
    window.setLevel_(NS_STATUS_WINDOW_LEVEL)
    window.makeKeyAndOrderFront_(None)

    response = alert.runModal()
    if response == 1000:
        return 1
    elif response == 1001:
        return 0
    elif response == 1002:
        return -1
    return response


class _ForegroundContext:
    """Promociona activation policy a .regular per un bloc d'alertes, i la
    torna al valor anterior al sortir. Evita flip-flop entre alertes."""
    def __init__(self):
        self.old_policy = None

    def __enter__(self):
        try:
            from AppKit import NSApp, NSApplicationActivationPolicyRegular
            self.old_policy = NSApp.activationPolicy()
            NSApp.setActivationPolicy_(NSApplicationActivationPolicyRegular)
            NSApp.activateIgnoringOtherApps_(True)
        except Exception:
            pass
        return self

    def __exit__(self, *exc):
        if self.old_policy is not None:
            try:
                from AppKit import NSApp
                NSApp.setActivationPolicy_(self.old_policy)
            except Exception:
                pass


# ═══════════════════════════════════════════════════════════════════════════
# PATHS
# ═══════════════════════════════════════════════════════════════════════════
PROJECT_ROOT = Path(__file__).parent.parent.resolve()
ICON_DIR = Path(__file__).parent / "tray_icons"
ICON_RUNNING = str(ICON_DIR / "icon_running.png") if (ICON_DIR / "icon_running.png").exists() else None
ICON_STOPPED = str(ICON_DIR / "icon_stopped.png") if (ICON_DIR / "icon_stopped.png").exists() else None

# Server config — read from core.config (Q4.2 fix). Falls back to env vars
# if core.config is not importable (e.g. tray launched outside the project).
try:
    from core.config import get_default_port, get_server_url
    SERVER_PORT = get_default_port()
    WEB_UI_URL = f"{get_server_url()}/ui"
except Exception:
    SERVER_PORT = int(os.environ.get("NEXE_SERVER_PORT", "9119"))
    WEB_UI_URL = f"http://{os.environ.get('NEXE_SERVER_HOST', '127.0.0.1')}:{SERVER_PORT}/ui"

# PID file (written by core/server/runner.py — used as fallback for Quit)
PID_FILE = PROJECT_ROOT / "storage" / "run" / "server.pid"


def _send_sigterm_from_pid_file(pid_file: Path) -> None:
    """Send SIGTERM to the server process recorded in pid_file.

    Used as fallback in _quit() when neither _attach_pid nor server_process is set
    (e.g. tray launched independently, server started separately via CLI).
    Safe to call when file is absent or PID is already dead.
    """
    import signal as _signal
    if not pid_file.exists():
        return
    try:
        data = json.loads(pid_file.read_text())
        pid = data.get("pid")
        if not pid:
            return
        os.kill(pid, 0)  # Check alive — raises ProcessLookupError if dead
        os.kill(pid, _signal.SIGTERM)
    except (ProcessLookupError, PermissionError, json.JSONDecodeError, OSError, ValueError):
        pass


# format_bytes, format_uptime and _RamMonitor imported from tray_monitor.py


# ═══════════════════════════════════════════════════════════════════════════
# TRAY APP
# ═══════════════════════════════════════════════════════════════════════════
class NexeTray(rumps.App):
    """macOS menu bar app for controlling the Nexe server."""

    def __init__(self, attach_pid=None):
        self._attach_pid = attach_pid
        self.lang = _detect_lang()
        self.strings = T.get(self.lang, T["ca"])

        # Read version from pyproject.toml (single source of truth)
        _version = "0.9"
        try:
            import tomllib
            _toml_path = PROJECT_ROOT / "pyproject.toml"
            if _toml_path.exists():
                with open(_toml_path, "rb") as f:
                    _version = tomllib.load(f).get("project", {}).get("version", _version)
        except Exception:
            pass
        self._version = _version

        super().__init__(
            name="server.nexe",
            icon=ICON_STOPPED,
            template=False,
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

        # Version item (non-clickable)
        self._version_item = rumps.MenuItem(f"server.nexe v{self._version}")
        self._version_item.set_callback(None)

        # Bug #9: Documentation link in main menu (replaces duplicate website
        # entry — website is still available in the Settings submenu).
        self._docs_item = rumps.MenuItem(
            self.strings["docs"],
            callback=self._open_docs,
        )

        # Build menu
        self.menu = [
            self._version_item,
            None,
            self.status_item,
            None,
            self.toggle_item,
            self.open_ui_item,
            self.open_logs_item,
            None,
            self.ram_item,
            self.uptime_item,
            None,
            self._docs_item,
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
            _front_alert(
                title="Nexe",
                message="Python venv not found. Please run the installer first.",
            )
            self.toggle_item.title = self.t("start")
            return

        # ─── PID file check (Bug #1): detect orphan server ────────────────
        pidfile = PROJECT_ROOT / "storage" / "run" / "server.pid"
        if pidfile.exists():
            try:
                data = json.loads(pidfile.read_text())
                existing_pid = int(data["pid"])
                try:
                    os.kill(existing_pid, 0)  # liveness probe
                    # PID alive — orphan server (not owned by this tray)
                    self.status_item.title = f"Server orfe detectat (PID {existing_pid})"
                    self.toggle_item.title = self.t("start")
                    self.icon = ICON_RUNNING
                    return
                except (ProcessLookupError, OSError):
                    pass  # stale, runner will clean it up on start
            except (ValueError, KeyError, OSError, json.JSONDecodeError):
                pass  # corrupt, runner will handle it

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

    def _format_ram_label(self, mon) -> str:
        """Format RAM label as 'Nexe: X · Model: Y' (B3)."""
        nexe_bytes = mon.cached_ram if mon else 0
        model_bytes = mon.cached_model_ram if mon else 0
        if nexe_bytes <= 0 and model_bytes <= 0:
            return "—"
        nexe_str = _format_bytes(nexe_bytes) if nexe_bytes > 0 else "—"
        model_str = _format_bytes(model_bytes) if model_bytes > 0 else "—"
        return f"Nexe: {nexe_str} · Model: {model_str}"

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
            ram_label = self._format_ram_label(mon)
            if ram_label != "—":
                self.ram_item.title = self.t("ram", ram=ram_label)
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
        ram_label = self._format_ram_label(mon)
        if ram_label != "—":
            self.ram_item.title = self.t("ram", ram=ram_label)

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

    def _open_docs(self, _sender):
        # Bug #9: docs subdomain may not exist yet — server-nexe.com root
        # is a safe fallback (Jordi will set up /docs separately).
        webbrowser.open("https://server-nexe.com/docs")

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

        # Resultat final també s'ha de veure a front (NSStatusWindowLevel + .regular)
        with _ForegroundContext():
            if failed:
                _front_alert(
                    title=self.t("uninstall_title"),
                    message=self.t("uninstall_partial", details=details),
                )
            else:
                _front_alert(
                    title=self.t("uninstall_title"),
                    message=self.t("uninstall_done", details=details),
                )

        # Terminació: rumps.quit_application() a vegades no tanca el procés si
        # el run loop esta dins un callback, i queda una icona zombie al menubar.
        # Fem sortida explícita: quit rumps + pkill totes les trays + os._exit.
        try:
            rumps.quit_application()
        except Exception:
            pass
        # Matar qualsevol altre nexe-tray/installer.tray orfe (no tocar PIDs
        # del servidor — stop_server_func ja els ha aturat).
        try:
            subprocess.Popen(
                ["pkill", "-f", "nexe-tray|installer.tray"],
                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
            )
        except Exception:
            pass
        # Sortir de veritat (bypass de qualsevol run loop pendent)
        import os as _os
        _os._exit(0)

    def _quit(self, _sender):
        self._stop_ram_monitor()
        # Always stop the server when quitting tray.
        # _stop_server() handles: (a) attach mode via _attach_pid,
        # (b) self-started mode via server_process.
        # Fallback (c): PID file, for when tray was started independently.
        if not self._attach_pid and not self.server_process:
            self._stop_server_via_pid_file()
        else:
            self._stop_server()
        if self._server_log_fh:
            try:
                self._server_log_fh.close()
            except Exception:
                pass
            self._server_log_fh = None
        rumps.quit_application()

    def _stop_server_via_pid_file(self):
        """Send SIGTERM to server using storage/run/server.pid as fallback."""
        _send_sigterm_from_pid_file(PID_FILE)


# ═══════════════════════════════════════════════════════════════════════════
# ENTRY POINT
# ═══════════════════════════════════════════════════════════════════════════
def main():
    # Bug #2: rename the tray process so it shows as "nexe-tray" instead of
    # "Python" in `ps aux` and Activity Monitor. Force Quit still shows
    # "Python" (requires CFBundleName via a real .app bundle — deferred to v0.9.1).
    try:
        import setproctitle
        setproctitle.setproctitle("nexe-tray")
    except ImportError:
        pass  # Optional dependency

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
