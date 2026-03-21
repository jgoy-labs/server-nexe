"""
────────────────────────────────────
Server Nexe
Location: installer/tray.py
Description: macOS menu bar app for controlling the Nexe server.
             Shows start/stop, RAM usage, and uptime.
             Uses rumps for native macOS NSStatusBar integration.
────────────────────────────────────
"""

import os
import signal
import subprocess
import sys
import time
import webbrowser
from pathlib import Path

import rumps

# ═══════════════════════════════════════════════════════════════════════════
# PATHS
# ═══════════════════════════════════════════════════════════════════════════
PROJECT_ROOT = Path(__file__).parent.parent.resolve()
ICON_DIR = Path(__file__).parent / "tray_icons"
ICON_RUNNING = str(ICON_DIR / "icon_running.png") if (ICON_DIR / "icon_running.png").exists() else None
ICON_STOPPED = str(ICON_DIR / "icon_stopped.png") if (ICON_DIR / "icon_stopped.png").exists() else None

# Server config
SERVER_PORT = 9119
WEB_UI_URL = f"http://localhost:{SERVER_PORT}/ui"

# ═══════════════════════════════════════════════════════════════════════════
# TRANSLATIONS
# ═══════════════════════════════════════════════════════════════════════════
T = {
    "ca": {
        "start": "▶ Engegar servidor",
        "stop": "⏹ Aturar servidor",
        "status_running": "Servidor actiu",
        "status_stopped": "Servidor aturat",
        "open_ui": "🌐 Obrir Web UI",
        "open_logs": "📄 Obrir logs",
        "ram": "🧠 RAM: {ram}",
        "uptime": "⏱ Temps: {uptime}",
        "quit": "Sortir",
        "starting": "Engegant...",
        "stopping": "Aturant...",
        "settings": "⚙️ Configuració",
        "uninstall": "🗑 Desinstal·lar Nexe",
        "uninstall_title": "Desinstal·lar Nexe",
        "uninstall_warning": "Això esborrarà TOTA la instal·lació de Nexe:\n\n• Models descarregats\n• Memòria i converses\n• Base de coneixement\n• Configuració\n\n{storage}\n\nAquesta acció NO es pot desfer.",
        "uninstall_confirm": "Estàs a punt d'esborrar Nexe i totes les seves dades permanentment.",
        "uninstall_checkbox": "Confirmo que vull esborrar-ho tot",
        "uninstall_done": "Nexe s'ha desinstal·lat correctament.\n\n{details}",
        "uninstall_partial": "Nexe s'ha aturat, però no s'ha pogut esborrar del tot.\n\n{details}\n\nEsborra manualment el que quedi.",
        "uninstall_storage": "Espai que s'alliberarà: {size}",
        "uninstall_removed": "Esborrat:",
        "uninstall_failed": "No s'ha pogut esborrar:",
    },
    "es": {
        "start": "▶ Iniciar servidor",
        "stop": "⏹ Detener servidor",
        "status_running": "Servidor activo",
        "status_stopped": "Servidor detenido",
        "open_ui": "🌐 Abrir Web UI",
        "open_logs": "📄 Abrir logs",
        "ram": "🧠 RAM: {ram}",
        "uptime": "⏱ Tiempo: {uptime}",
        "quit": "Salir",
        "starting": "Iniciando...",
        "stopping": "Deteniendo...",
        "settings": "⚙️ Configuración",
        "uninstall": "🗑 Desinstalar Nexe",
        "uninstall_title": "Desinstalar Nexe",
        "uninstall_warning": "Esto borrará TODA la instalación de Nexe:\n\n• Modelos descargados\n• Memoria y conversaciones\n• Base de conocimiento\n• Configuración\n\n{storage}\n\nEsta acción NO se puede deshacer.",
        "uninstall_confirm": "Estás a punto de borrar Nexe y todos sus datos permanentemente.",
        "uninstall_checkbox": "Confirmo que quiero borrarlo todo",
        "uninstall_done": "Nexe se ha desinstalado correctamente.\n\n{details}",
        "uninstall_partial": "Nexe se ha detenido, pero no se pudo borrar por completo.\n\n{details}\n\nBorra manualmente lo que quede.",
        "uninstall_storage": "Espacio que se liberará: {size}",
        "uninstall_removed": "Borrado:",
        "uninstall_failed": "No se pudo borrar:",
    },
    "en": {
        "start": "▶ Start Server",
        "stop": "⏹ Stop Server",
        "status_running": "Server running",
        "status_stopped": "Server stopped",
        "open_ui": "🌐 Open Web UI",
        "open_logs": "📄 Open logs",
        "ram": "🧠 RAM: {ram}",
        "uptime": "⏱ Uptime: {uptime}",
        "quit": "Quit",
        "starting": "Starting...",
        "stopping": "Stopping...",
        "settings": "⚙️ Settings",
        "uninstall": "🗑 Uninstall Nexe",
        "uninstall_title": "Uninstall Nexe",
        "uninstall_warning": "This will DELETE the entire Nexe installation:\n\n• Downloaded models\n• Memory and conversations\n• Knowledge base data\n• Configuration\n\n{storage}\n\nThis action CANNOT be undone.",
        "uninstall_confirm": "You are about to permanently delete Nexe and all its data.",
        "uninstall_checkbox": "I confirm I want to delete everything",
        "uninstall_done": "Nexe has been uninstalled successfully.\n\n{details}",
        "uninstall_partial": "Nexe has been stopped, but could not be fully deleted.\n\n{details}\n\nManually delete what remains.",
        "uninstall_storage": "Space to be freed: {size}",
        "uninstall_removed": "Removed:",
        "uninstall_failed": "Could not remove:",
    },
}


def _detect_lang():
    """Detect language from env or .env file."""
    lang = os.environ.get("NEXE_LANG", "")
    if lang in ("ca", "es", "en"):
        return lang
    env_file = PROJECT_ROOT / ".env"
    if env_file.exists():
        for line in env_file.read_text().splitlines():
            if line.startswith("NEXE_LANG="):
                val = line.split("=", 1)[1].strip().strip('"').strip("'")
                if val in ("ca", "es", "en"):
                    return val
    return "ca"


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


def _get_process_ram(pid):
    """Get RSS memory of a process and its children (macOS)."""
    try:
        # Use ps to get RSS of process tree (in KB)
        result = subprocess.run(
            ["ps", "-o", "rss=", "-p", str(pid)],
            capture_output=True, text=True, timeout=5,
        )
        if result.returncode == 0 and result.stdout.strip():
            rss_kb = int(result.stdout.strip())
            # Also get children
            children = subprocess.run(
                ["pgrep", "-P", str(pid)],
                capture_output=True, text=True, timeout=5,
            )
            if children.returncode == 0:
                for child_pid in children.stdout.strip().split("\n"):
                    if child_pid.strip():
                        child_rss = subprocess.run(
                            ["ps", "-o", "rss=", "-p", child_pid.strip()],
                            capture_output=True, text=True, timeout=5,
                        )
                        if child_rss.returncode == 0 and child_rss.stdout.strip():
                            rss_kb += int(child_rss.stdout.strip())
            return rss_kb * 1024  # Convert KB to bytes
    except Exception:
        pass
    return 0


# ═══════════════════════════════════════════════════════════════════════════
# TRAY APP
# ═══════════════════════════════════════════════════════════════════════════
class NexeTray(rumps.App):
    """macOS menu bar app for controlling the Nexe server."""

    def __init__(self):
        self.lang = _detect_lang()
        self.strings = T.get(self.lang, T["ca"])

        super().__init__(
            name="Nexe",
            icon=ICON_STOPPED,
            template=None,  # Full color icons (green/grey)
            quit_button=None,  # Custom quit to stop server first
        )

        # Server state
        self.server_process = None
        self.server_start_time = None
        self._server_log_path = PROJECT_ROOT / "storage" / "logs" / "server.log"
        self._server_log_fh = None

        # Menu items (keep references for dynamic updates)
        self.status_item = rumps.MenuItem(self.strings["status_stopped"])
        self.status_item.set_callback(None)  # Non-clickable

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

        # Settings submenu with uninstall
        self.settings_menu = rumps.MenuItem(self.strings["settings"])
        self.uninstall_item = rumps.MenuItem(
            self.strings["uninstall"],
            callback=self._uninstall,
        )
        self.settings_menu[self.strings["uninstall"]] = self.uninstall_item

        # Build menu
        self.menu = [
            self.status_item,
            None,  # separator
            self.toggle_item,
            self.open_ui_item,
            self.open_logs_item,
            None,  # separator
            self.ram_item,
            self.uptime_item,
            None,  # separator
            self.settings_menu,
            None,  # separator
            self.quit_item,
        ]

        # Update timer (every 3 seconds)
        self._timer = rumps.Timer(self._update_stats, 3)
        self._timer.start()

    def t(self, key, **kwargs):
        """Get translated string."""
        s = self.strings.get(key, key)
        if kwargs:
            s = s.format(**kwargs)
        return s

    # ── Server control ────────────────────────────────────────────────────

    def _toggle_server(self, sender):
        """Start or stop the server."""
        if self.server_process and self.server_process.poll() is None:
            self._stop_server()
        else:
            self._start_server()

    def _start_server(self):
        """Start the Nexe server as a subprocess."""
        self.toggle_item.title = self.t("starting")

        # Find the venv python
        venv_python = PROJECT_ROOT / "venv" / "bin" / "python"
        if not venv_python.exists():
            rumps.alert(
                title="Nexe",
                message="Python venv not found. Please run the installer first.",
            )
            self.toggle_item.title = self.t("start")
            return

        # Start server
        tray_pid = os.getpid()
        env = {
            **os.environ,
            "PYTHONUNBUFFERED": "1",
            "NEXE_TRAY_PID": str(tray_pid),  # Anti-zombie: server checks this
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

        # Blink icon until server is ready
        self.status_item.title = self.t("starting")
        import threading
        threading.Thread(target=self._wait_server_ready, daemon=True).start()

    def _wait_server_ready(self):
        """Wait for server to respond, blinking icon meanwhile."""
        import urllib.request
        import urllib.error

        blink_on = True
        max_wait = 15  # seconds
        start = time.time()

        while time.time() - start < max_wait:
            # Blink icon
            self.icon = ICON_RUNNING if blink_on else ICON_STOPPED
            blink_on = not blink_on

            # Check if server responds
            try:
                req = urllib.request.urlopen(
                    f"http://localhost:{SERVER_PORT}/health", timeout=2
                )
                if req.status == 200:
                    break
            except (urllib.error.URLError, OSError, ValueError):
                pass

            # Check if process died
            if self.server_process and self.server_process.poll() is not None:
                self.icon = ICON_STOPPED
                self.status_item.title = self.t("status_stopped")
                self.toggle_item.title = self.t("start")
                return

            time.sleep(0.5)

        # Server ready (or timeout)
        self.icon = ICON_RUNNING
        self.status_item.title = self.t("status_running")
        self.toggle_item.title = self.t("stop")

    def _stop_server(self):
        """Stop the running server."""
        if not self.server_process:
            return

        self.toggle_item.title = self.t("stopping")

        # Graceful shutdown
        try:
            self.server_process.terminate()
            self.server_process.wait(timeout=10)
        except subprocess.TimeoutExpired:
            try:
                self.server_process.kill()
                self.server_process.wait(timeout=5)
            except Exception:
                pass  # Last resort — process may already be gone

        # Close log file handle
        if self._server_log_fh:
            try:
                self._server_log_fh.close()
            except Exception:
                pass
            self._server_log_fh = None

        self.server_process = None
        self.server_start_time = None

        # Update UI
        self.icon = ICON_STOPPED
        self.status_item.title = self.t("status_stopped")
        self.toggle_item.title = self.t("start")
        self.ram_item.title = self.t("ram", ram="—")
        self.uptime_item.title = self.t("uptime", uptime="—")

    # ── Stats update ──────────────────────────────────────────────────────

    def _update_stats(self, _timer):
        """Periodically update RAM and uptime display."""
        if not self.server_process or self.server_process.poll() is not None:
            # Process died unexpectedly
            if self.server_process and self.server_process.poll() is not None:
                self.server_process = None
                self.server_start_time = None
                self.icon = ICON_STOPPED
                self.status_item.title = self.t("status_stopped")
                self.toggle_item.title = self.t("start")
                self.ram_item.title = self.t("ram", ram="—")
                self.uptime_item.title = self.t("uptime", uptime="—")
            return

        # RAM
        ram_bytes = _get_process_ram(self.server_process.pid)
        if ram_bytes > 0:
            self.ram_item.title = self.t("ram", ram=_format_bytes(ram_bytes))

        # Uptime
        if self.server_start_time:
            elapsed = time.time() - self.server_start_time
            self.uptime_item.title = self.t("uptime", uptime=_format_uptime(elapsed))

    # ── Actions ───────────────────────────────────────────────────────────

    def _open_web_ui(self, _sender):
        """Open the Web UI in the default browser."""
        webbrowser.open(WEB_UI_URL)

    def _open_logs(self, _sender):
        """Open the server log file in Console.app / default viewer."""
        if self._server_log_path.exists():
            subprocess.Popen(["open", str(self._server_log_path)])
        else:
            # Open the logs directory if no server.log yet
            log_dir = PROJECT_ROOT / "storage" / "logs"
            log_dir.mkdir(parents=True, exist_ok=True)
            subprocess.Popen(["open", str(log_dir)])

    def _calculate_storage(self):
        """Calculate total disk usage of the Nexe installation."""
        total = 0
        for path in [PROJECT_ROOT, Path("/Applications/Nexe.app")]:
            if path.exists():
                try:
                    for f in path.rglob("*"):
                        if f.is_file() and not f.is_symlink():
                            try:
                                total += f.stat().st_size
                            except OSError:
                                pass
                except OSError:
                    pass
        return _format_bytes(total) if total > 0 else "—"

    def _remove_from_dock(self):
        """Remove Nexe.app from the macOS Dock."""
        try:
            subprocess.run(["bash", "-c", """
python3 -c "
import subprocess, plistlib
dock = subprocess.run(['defaults', 'export', 'com.apple.dock', '-'], capture_output=True)
pl = plistlib.loads(dock.stdout)
before = len(pl.get('persistent-apps', []))
pl['persistent-apps'] = [a for a in pl.get('persistent-apps', [])
    if 'Nexe' not in str(a.get('tile-data', {}).get('file-label', ''))]
if len(pl['persistent-apps']) < before:
    out = plistlib.dumps(pl)
    subprocess.run(['defaults', 'import', 'com.apple.dock', '-'], input=out)
    subprocess.run(['killall', 'Dock'])
"
"""], capture_output=True, timeout=15)
            return True
        except Exception:
            return False

    def _show_final_confirm(self):
        """Show a second confirmation alert. Returns True only if user confirms."""
        response = rumps.alert(
            title=self.t("uninstall_title"),
            message=self.t("uninstall_confirm"),
            ok=self.t("uninstall_title"),
            cancel="No",
        )
        return response == 1

    def _uninstall(self, _sender):
        """Uninstall Nexe with two-step confirmation and full cleanup."""
        import shutil

        # Calculate storage before showing warning
        storage_text = self.t("uninstall_storage", size=self._calculate_storage())

        # First window: warning with what will be deleted
        response = rumps.alert(
            title=self.t("uninstall_title"),
            message=self.t("uninstall_warning", storage=storage_text),
            ok=self.t("uninstall_title"),
            cancel="No",
        )
        if response != 1:
            return

        # Second window: final confirmation
        if not self._show_final_confirm():
            return

        # Stop server
        self._stop_server()

        removed = []
        failed = []

        # Remove from Login Items
        try:
            subprocess.run([
                "osascript", "-e",
                'tell application "System Events" to delete login item "Nexe"'
            ], capture_output=True, timeout=10)
            removed.append("Login Items")
        except Exception:
            failed.append("Login Items")

        # Remove from Dock
        if self._remove_from_dock():
            removed.append("Dock")
        else:
            failed.append("Dock")

        # Remove /usr/local/bin/nexe symlink
        nexe_symlink = Path("/usr/local/bin/nexe")
        if nexe_symlink.is_symlink() or nexe_symlink.exists():
            try:
                nexe_symlink.unlink()
                removed.append("/usr/local/bin/nexe")
            except PermissionError:
                failed.append("/usr/local/bin/nexe (permis denegat)")
            except Exception:
                failed.append("/usr/local/bin/nexe")

        # Remove /Applications/Nexe.app
        nexe_app = Path("/Applications/Nexe.app")
        if nexe_app.exists():
            try:
                shutil.rmtree(nexe_app)
                removed.append("/Applications/Nexe.app")
            except Exception:
                failed.append("/Applications/Nexe.app")

        # Remove installation directory using a detached shell script
        # (can't delete ourselves while running — launch rm and quit)
        install_dir = PROJECT_ROOT
        cleanup_script = f"""#!/bin/bash
sleep 2
rm -rf "{install_dir}"
"""
        try:
            subprocess.Popen(
                ["bash", "-c", cleanup_script],
                start_new_session=True,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
            removed.append(str(install_dir))
        except Exception:
            failed.append(str(install_dir))

        # Build details report
        details = ""
        if removed:
            details += self.t("uninstall_removed") + "\n• " + "\n• ".join(removed)
        if failed:
            if details:
                details += "\n\n"
            details += self.t("uninstall_failed") + "\n• " + "\n• ".join(failed)

        # Show result
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
        """Stop server and quit the tray app."""
        self._stop_server()
        rumps.quit_application()


# ═══════════════════════════════════════════════════════════════════════════
# ENTRY POINT
# ═══════════════════════════════════════════════════════════════════════════
def main():
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--autostart", action="store_true",
                        help="Engega el servidor automaticament al obrir")
    args = parser.parse_args()

    app = NexeTray()
    if args.autostart:
        import threading
        def auto():
            import time
            import urllib.request
            import urllib.error
            time.sleep(0.5)
            app._start_server()
            # Wait for server to be ready before opening browser
            for _ in range(30):  # max 15 seconds (30 x 0.5s)
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
    main()
