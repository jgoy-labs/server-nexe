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
from datetime import datetime, timezone
from pathlib import Path

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

def _acquire_pidfile(pid_path: Path, port: int) -> bool:
  """Try to acquire the canonical server PID file using an atomic O_EXCL open.

  Returns True if acquired (file written), False if another live server
  already holds the lock. Stale lock files (dead PID, corrupt content)
  are removed automatically.

  Atomic: uses os.open(O_CREAT|O_EXCL|O_WRONLY) so two concurrent callers
  cannot both succeed — exactly one wins the race.
  """
  import json as _json

  pid_path.parent.mkdir(parents=True, exist_ok=True)
  content = _json.dumps({
    "pid": os.getpid(),
    "port": port,
    "started": datetime.now(timezone.utc).isoformat(),
  }).encode()

  for _attempt in range(2):  # up to 2 attempts: initial + after stale removal
    try:
      fd = os.open(str(pid_path), os.O_CREAT | os.O_EXCL | os.O_WRONLY)
      try:
        os.write(fd, content)
      finally:
        os.close(fd)
      return True
    except FileExistsError:
      # File exists — check if the holder is alive
      try:
        raw = pid_path.read_text()
        if not raw.strip():
          # Buit: un altre procés acaba de crear-lo amb O_EXCL i encara escriu.
          # Tractem com a locked — NO eliminem.
          logger.debug("PID file exists but empty — another process is acquiring it.")
          return False
        data = _json.loads(raw)
        existing_pid = int(data["pid"])
        existing_port = data.get("port", "?")
        try:
          os.kill(existing_pid, 0)  # signal 0 = liveness probe
          logger.error(
            "Server already running. PID: %s on port %s. Use './nexe stop' to stop it.",
            existing_pid, existing_port,
          )
          return False
        except (ProcessLookupError, OSError):
          logger.warning("Stale PID file found (PID %s dead), removing.", existing_pid)
          try:
            pid_path.unlink()
          except OSError:
            pass
          # retry the atomic open in next iteration
      except (ValueError, KeyError, OSError, Exception) as e:
        logger.warning("Corrupt PID file (%s), removing.", e)
        try:
          pid_path.unlink()
        except OSError:
          pass
        # retry the atomic open in next iteration

  # Should not reach here, but fail-safe
  logger.error("Could not acquire PID file after retries: %s", pid_path)
  return False


def _release_pidfile(pid_path: Path) -> None:
  """Remove the PID file if it exists and belongs to us."""
  try:
    if pid_path.exists():
      try:
        import json as _json
        data = _json.loads(pid_path.read_text())
        existing_pid = int(data["pid"])
      except Exception:
        existing_pid = None
      if existing_pid is None or existing_pid == os.getpid():
        pid_path.unlink()
  except OSError as e:
    logger.debug("Failed to release PID file %s: %s", pid_path, e)


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


def _maybe_launch_tray(_project_root: "Path | None" = None):
    """Launch the macOS tray icon if on macOS and no tray is already running.

    Args:
        _project_root: Override project root (tests only). If None, derived from __file__.
    """
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

    # Launch tray in --attach mode.
    #
    # Priority: NexeTray.app bundle (Gatekeeper-safe, macOS Sequoia provenance OK,
    # appears as "server-nexe" in Activity Monitor via CFBundleName).
    # Fallback: python -m installer.tray (dev mode, no bundle present).
    #
    # The bundle's entry point (NexeTray.app/Contents/MacOS/NexeTray) is a bash
    # script that exec's the venv Python with the same args via "$@", so
    # --attach and --server-pid are forwarded transparently.
    project_root = _project_root if _project_root is not None else Path(__file__).resolve().parent.parent
    venv_python = project_root / "venv" / "bin" / "python"
    python_exe = str(venv_python) if venv_python.exists() else sys.executable

    server_pid = os.getpid()
    tray_args = ["--attach", "--server-pid", str(server_pid)]

    tray_binary = project_root / "installer" / "NexeTray.app" / "Contents" / "MacOS" / "NexeTray"

    try:
        if tray_binary.exists():
            # App bundle path: Gatekeeper-safe, correct CFBundleName in Force Quit
            subprocess.Popen(
                [str(tray_binary)] + tray_args,
                cwd=str(project_root),
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                start_new_session=True,
            )
            logger.info("Tray launched via bundle (server PID %d)", server_pid)
        else:
            # Fallback for dev environments without the app bundle
            subprocess.Popen(
                [python_exe, "-m", "installer.tray"] + tray_args,
                cwd=str(project_root),
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                start_new_session=True,
            )
            logger.info("Tray launched via python -m (dev fallback, server PID %d)", server_pid)
    except Exception as e:
        logger.debug("Could not launch tray: %s", e)


def _handle_sigterm(signum, frame):  # noqa: ARG001
  """SIGTERM handler (N05). Garanteix sortida neta pre-uvicorn.

  Un cop uvicorn arrenca, ell mateix gestiona SIGTERM i dispara el
  lifespan finally (que neteja el PID file). Aquest handler cobreix la
  finestra entre el registre del senyal i el moment que uvicorn pren el control.
  """
  logger.info("SIGTERM received — exiting cleanly")
  sys.exit(0)


def main():
  """
  Main entry point for running the server directly.

  Loads configuration and starts uvicorn with the application factory.
  """
  # Bug #2: rename the process so it shows as "server-nexe" instead of "Python"
  # in `ps aux` and Activity Monitor. Force Quit still shows "Python" because
  # that requires CFBundleName via a real .app bundle (deferred to v0.9.1).
  try:
    import setproctitle
    setproctitle.setproctitle("server-nexe")
  except ImportError:
    pass  # Optional dependency

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

  from core.config import DEFAULT_HOST, DEFAULT_PORT
  server_config = config.get('core', {}).get('server', {})
  host = server_config.get('host', DEFAULT_HOST)
  port = server_config.get('port', DEFAULT_PORT)
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

  # ─── SIGTERM handler (N05) ────────────────────────────────────────────
  # Garanteix sortida neta pre-uvicorn (funció definida a nivell de mòdul).
  signal.signal(signal.SIGTERM, _handle_sigterm)

  # ─── PID file: gestionat pel lifespan (B06) ───────────────────────────
  # L'escriptura i neteja del PID s'han mogut a core/lifespan.py.
  # runner.py ja no gestiona el PID directament.

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