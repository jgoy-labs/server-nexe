"""
────────────────────────────────────
Server Nexe
Author: Jordi Goy
Location: core/server/runner.py
Description: Server runner and main entry point. main() loads config, validates port

www.jgoy.net · https://server-nexe.org
────────────────────────────────────
"""

import logging
import os
import signal
import subprocess
import sys
import threading
import time

# ═══════════════════════════════════════════════════════════════════════════
# LOAD .env AT MODULE LEVEL (before any imports that depend on env vars)
# This ensures environment variables are available for all module-level code
# ═══════════════════════════════════════════════════════════════════════════
from dotenv import load_dotenv
load_dotenv()

# --- UI CONSTANTS ---
RED = "\033[1;31m"
GREEN = "\033[1;32m"
YELLOW = "\033[1;33m"
BLUE = "\033[1;34m"
CYAN = "\033[1;36m"
BOLD = "\033[1m"
RESET = "\033[0m"

import uvicorn

logger = logging.getLogger(__name__)

from .helpers import setup_signal_handlers, is_port_in_use, translate
from .factory import create_app


def kill_process_on_port(port: int) -> bool:
  """Kill any process using the specified port.

  Returns True if a process was killed, False otherwise.
  """
  try:
    # Find PID using lsof
    result = subprocess.run(
      ["lsof", "-ti", f":{port}"],
      capture_output=True,
      text=True
    )
    if result.returncode == 0 and result.stdout.strip():
      pids = result.stdout.strip().split('\n')
      for pid in pids:
        try:
          os.kill(int(pid), signal.SIGTERM)
        except (ProcessLookupError, ValueError):
          pass
      # Wait a moment for process to terminate
      time.sleep(0.5)
      return True
  except Exception as e:
    logger.debug("Failed to kill process on port %s: %s", port, e)
  return False

def _start_parent_watchdog():
  """If launched from the tray app, monitor that the parent is still alive.

  When NEXE_TRAY_PID is set, a daemon thread checks every 30s if that
  process still exists. If the tray dies (e.g. Force Quit), the server
  shuts itself down to avoid orphaned processes consuming RAM.
  """
  tray_pid_str = os.environ.get("NEXE_TRAY_PID")
  if not tray_pid_str:
    return

  try:
    tray_pid = int(tray_pid_str)
  except ValueError:
    logger.warning("Invalid NEXE_TRAY_PID=%r — parent watchdog disabled", tray_pid_str)
    return

  def _watchdog():
    while True:
      time.sleep(30)
      try:
        os.kill(tray_pid, 0)  # Signal 0 = check if alive, no actual signal
      except ProcessLookupError:
        logger.info("Tray process (PID %d) no longer running — shutting down server", tray_pid)
        os.kill(os.getpid(), signal.SIGTERM)
        return
      except PermissionError:
        pass  # Process exists but we can't signal it — still alive

  t = threading.Thread(target=_watchdog, daemon=True)
  t.start()
  logger.debug("Parent watchdog started — monitoring tray PID %d", tray_pid)


def _maybe_launch_tray():
    """Launch the macOS tray icon if on macOS and no tray is already running."""
    from pathlib import Path

    # Guard 1: Already launched from tray
    if os.environ.get("NEXE_TRAY_PID"):
        logger.debug("Tray already running (NEXE_TRAY_PID set) — skipping tray launch")
        return

    # Guard 2: macOS only
    if sys.platform != "darwin":
        return

    # Guard 3: Docker/headless — no GUI
    if os.environ.get("NEXE_DOCKER") or os.environ.get("CONTAINER"):
        return

    # Guard 4: User opted out
    if os.environ.get("NEXE_NO_TRAY"):
        return

    # Guard 5: Check rumps availability
    try:
        import rumps  # noqa: F401
    except ImportError:
        logger.debug("rumps not installed — tray not available")
        return

    # Guard 6: Kill stale tray before launching fresh one
    try:
        result = subprocess.run(
            ["pgrep", "-f", "installer.tray"],
            capture_output=True, text=True, timeout=5,
        )
        if result.returncode == 0 and result.stdout.strip():
            stale_pids = [int(p) for p in result.stdout.strip().split('\n') if p.strip()]
            for pid in stale_pids:
                try:
                    os.kill(pid, signal.SIGTERM)
                except (ProcessLookupError, PermissionError):
                    pass
            time.sleep(1)
            # Force kill if still alive (rumps may ignore SIGTERM)
            for pid in stale_pids:
                try:
                    os.kill(pid, signal.SIGKILL)
                except (ProcessLookupError, PermissionError):
                    pass
            time.sleep(0.3)
            logger.debug("Killed stale tray process(es) — launching fresh one")
    except Exception:
        pass

    # Launch tray in --attach mode
    project_root = Path(__file__).resolve().parent.parent
    venv_python = project_root / "venv" / "bin" / "python"
    python_exe = str(venv_python) if venv_python.exists() else sys.executable

    server_pid = os.getpid()

    try:
        subprocess.Popen(
            [python_exe, "-m", "installer.tray", "--attach", "--server-pid", str(server_pid)],
            cwd=str(project_root),
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            start_new_session=True,  # Fully detach from terminal
        )
        logger.info("Tray launched in attach mode (server PID %d)", server_pid)
    except Exception as e:
        logger.debug("Could not launch tray: %s", e)


def main():
  """
  Main entry point for running the server directly.

  Loads configuration and starts uvicorn with the application factory.
  """
  setup_signal_handlers()
  _start_parent_watchdog()

  # Note: .env is now loaded at module level (top of file) for better test compatibility

  # Check basic security config
  if not os.getenv("NEXE_PRIMARY_API_KEY"):
       logger.warning("No NEXE_PRIMARY_API_KEY found in .env. Authentication might fail or rely on defaults.")

  app = create_app()

  config = app.state.config
  i18n = app.state.i18n
  project_root = app.state.project_root

  logger.info(
    translate(i18n, "server_core.startup.starting_from", "Starting Nexe 0.9 from: {path}", path=str(project_root))
  )

  server_config = config.get('core', {}).get('server', {})
  host = server_config.get('host', '127.0.0.1')
  port = server_config.get('port', 9119)
  workers = server_config.get('workers', 1)
  if workers > 1:
    logger.warning(
      "Multiple workers detected. "
      "Note that rate-limits are in-memory and not shared across processes. "
      "Bootstrap tokens are shared via SQLite."
    )

  reload = server_config.get('reload', False)

  if is_port_in_use(host, port):
    logger.warning(
      translate(
        i18n,
        "server_core.errors.port_in_use",
        "Port {port} is already in use at {host}.",
        host=host,
        port=port
      )
    )
    # When launched from tray (no terminal), auto-kill the old process
    headless = os.environ.get("NEXE_TRAY_PID") or not sys.stdin.isatty()
    if headless:
      if kill_process_on_port(port):
        logger.info(translate(i18n, "core.server.process_killed",
          "Previous process on port {port} terminated.", port=port))
      else:
        logger.error(translate(i18n, "core.server.kill_failed",
          "Could not terminate process on port {port}.", port=port))
        sys.exit(1)
    else:
      # Interactive: ask user
      try:
        print(f"\n{YELLOW}Port {port} is in use. Kill existing process? [y/N]: {RESET}", end="")
        response = input().strip().lower()
        if response in ('y', 'yes'):
          if kill_process_on_port(port):
            logger.info(translate(i18n, "core.server.process_killed",
              "Previous process on port {port} terminated.", port=port))
          else:
            logger.error(translate(i18n, "core.server.kill_failed",
              "Could not terminate process on port {port}. Try manually: lsof -ti:{port} | xargs kill", port=port))
            sys.exit(1)
        else:
          logger.info(translate(i18n, "core.server.find_port_usage",
            "To find what's using the port: lsof -ti:{port}", port=port))
          sys.exit(1)
      except (EOFError, KeyboardInterrupt):
        print()
        sys.exit(1)

  logger.info(
    translate(i18n, "server_core.startup.starting_server_on", "Starting server on {host}:{port}", host=host, port=port)
  )

  # Quick reference commands
  logger.info(
    f"\n{BOLD}{RED}QUICK COMMANDS:{RESET}\n"
    f"  {CYAN}Interactive Chat:{RESET}  ./nexe chat\n"
    f"  {CYAN}View logs:{RESET}         ./nexe logs\n"
    f"  {CYAN}RAG ingest:{RESET}        ./nexe memory store \"text\"\n"
    f"  {CYAN}System status:{RESET}     ./nexe status\n"
    f"\n{BOLD}QUICK CONFIG:{RESET}\n"
    f"  To change personality (System Prompt):\n"
    f"  edit {YELLOW}personality/server.toml{RESET}\n"
    f"{YELLOW}Server running at: {host}:{port}{RESET}"
  )

  _maybe_launch_tray()

  try:
    uvicorn.run(
      "core.app:app",
      host=host,
      port=port,
      workers=workers,
      reload=reload,
      log_level="info",
      timeout_keep_alive=5,
      timeout_graceful_shutdown=10,
      limit_concurrency=100,
      limit_max_requests=None
    )
  except KeyboardInterrupt:
    logger.info(translate(i18n, "core.server.server_stopped_by_user",
      "Server stopped by user (Ctrl+C)"))
  except Exception as e:
    logger.error(translate(i18n, "core.server.server_startup_error",
      "Error starting server: {error}", error=str(e)))
    logger.exception(translate(i18n, "core.server.startup_error", "Server startup error: {error}", error=str(e)), exc_info=True)
    sys.exit(1)