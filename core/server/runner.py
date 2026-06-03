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
import logging.handlers
import os
import signal
import sys
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

import uvicorn  # noqa: E402  # after load_dotenv() so env vars apply to transitive imports

logger = logging.getLogger(__name__)

from .helpers import setup_signal_handlers, is_port_in_use, translate  # noqa: E402  # after load_dotenv()
from .factory import create_app  # noqa: E402  # after load_dotenv()
from core.version import __version__  # noqa: E402  # after load_dotenv()
# F2.A11 refactor: parent watchdog mogut a core/server/watchdog.py per trencar
# cicle imports (lifespan → runner → factory → endpoints → lifespan). Re-exportat
# aquí per backward compatibility amb runner.main() i tests.
from .watchdog import start_parent_watchdog as _start_parent_watchdog  # noqa: E402  # after load_dotenv()
# utilitats de ports mogudes a core/server/port_utils.py.
# Re-exportat aquí perquè _handle_port_conflict el resol al namespace de runner
# (els tests fan patch de core.server.runner.kill_process_on_port).
from .port_utils import kill_process_on_port  # noqa: E402  # after load_dotenv()
# lògica del tray moguda a core/server/tray_launcher.py.
# Re-exportats aquí per backward compatibility amb runner.main() i tests.
from .tray_launcher import (  # noqa: E402  # after load_dotenv()
    _is_tray_already_running,
    _is_tray_supported,
    _kill_stale_tray,
    _launch_tray_process,
    _maybe_launch_tray,
)


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
          # Empty: another process just created it with O_EXCL and is still writing.
          # Treat as locked — do NOT delete.
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


def _handle_port_conflict(host: str, port: int, headless: bool, sidecar: bool, i18n: object) -> None:
  """Handle port-in-use conflict. Exits or kills depending on mode.

  Extracted for testability. Called only when is_port_in_use() is True.
  """
  if sidecar:
    logger.error(
      "Sidecar mode: port %s at %s already occupied. "
      "Tauri must pre-reserve the port. Exiting.", port, host
    )
    sys.exit(1)
  elif headless:
    if kill_process_on_port(port):
      logger.info(translate(i18n, "core.server.process_killed",
        "Previous process on port {port} terminated.", port=port))
    else:
      logger.error(translate(i18n, "core.server.kill_failed",
        "Could not terminate process on port {port}.", port=port))
      sys.exit(1)
  else:
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


def _handle_sigterm(signum, frame):  # noqa: ARG001
  """SIGTERM handler (N05). Guarantees clean exit before uvicorn takes over.

  Once uvicorn starts, it handles SIGTERM itself and triggers the
  lifespan finally block (which cleans up the PID file). This handler covers
  the window between signal registration and when uvicorn takes control.
  """
  logger.info("SIGTERM received — exiting cleanly")
  sys.exit(0)


def _set_process_title() -> None:
  """Rename process to 'server-nexe' in ps/Activity Monitor (Bug #2).
  Force Quit still shows 'Python' (needs CFBundleName via .app bundle — v0.9.1).
  """
  try:
    import setproctitle
    setproctitle.setproctitle("server-nexe")
  except ImportError:
    pass  # Optional dependency


def _setup_file_logging() -> None:
  """Always write logs to storage/logs/server.log so the tray 'Open Logs'
  button works in both dev mode (./nexe go) and production (tray-launched).
  """
  _log_dir = Path(__file__).parent.parent.parent / "storage" / "logs"
  _log_dir.mkdir(parents=True, exist_ok=True)
  _server_log = _log_dir / "server.log"
  _fh = logging.handlers.TimedRotatingFileHandler(
    _server_log, when="midnight", interval=1, backupCount=7, encoding="utf-8"
  )
  _fh.setLevel(logging.DEBUG)
  _fh.setFormatter(logging.Formatter(
    "%(asctime)s - %(name)s - %(levelname)s - %(message)s"
  ))
  logging.getLogger().addHandler(_fh)


def _log_quick_commands_banner(host: str, port: int) -> None:
  """Print the quick-reference commands banner to the log."""
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


def _run_uvicorn_server(host: str, port: int, workers: int, reload: bool, i18n) -> None:
  """Start uvicorn with the application factory, handling KeyboardInterrupt cleanly."""
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


def main():
  """
  Main entry point for running the server directly.

  Loads configuration and starts uvicorn with the application factory.
  """
  _set_process_title()
  setup_signal_handlers()
  _start_parent_watchdog()
  _setup_file_logging()

  # Note: .env is now loaded at module level (top of file) for better test compatibility

  # Check basic security config
  if not os.getenv("NEXE_PRIMARY_API_KEY"):
       logger.warning("No NEXE_PRIMARY_API_KEY found in .env. Authentication might fail or rely on defaults.")

  app = create_app()

  config = app.state.config
  i18n = app.state.i18n
  project_root = app.state.project_root

  logger.info(
    translate(i18n, "server_core.startup.starting_from", f"Starting server-nexe {__version__} from: {{path}}", path=str(project_root))
  )

  from core.config import DEFAULT_HOST, DEFAULT_PORT, get_default_host, get_default_port
  server_config = config.get('core', {}).get('server', {})
  # NEXE_PORT/NEXE_HOST (injected by Tauri in sidecar mode)
  # tenen prioritat màxima sobre server_config. Sense aquest override, el
  # sidecar arrencaria al port del config.yaml i Tauri no el trobaria.
  env_port = os.environ.get("NEXE_PORT")
  port = int(env_port) if env_port else server_config.get('port', DEFAULT_PORT)
  env_host = os.environ.get("NEXE_HOST")
  host = env_host if env_host else server_config.get('host', DEFAULT_HOST)
  # NOTA: import de get_default_host/get_default_port reservat per a M0-bis
  # (F2) — substituiran els DEFAULT_* constants en el refactor real.
  _ = (get_default_host, get_default_port)  # noqa: F841 — reserved for F2
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
    headless = bool(os.environ.get("NEXE_TRAY_PID") or not sys.stdin.isatty())
    sidecar = bool(os.environ.get("NEXE_SIDECAR"))
    _handle_port_conflict(host, port, headless, sidecar, i18n)

  logger.info(
    translate(i18n, "server_core.startup.starting_server_on", "Starting server on {host}:{port}", host=host, port=port)
  )

  _log_quick_commands_banner(host, port)

  # ─── SIGTERM handler (N05) ────────────────────────────────────────────
  # Guarantees clean exit pre-uvicorn (function defined at module level).
  signal.signal(signal.SIGTERM, _handle_sigterm)

  # ─── PID file: managed by the lifespan (B06) ──────────────────────────
  # PID writing and cleanup have been moved to core/lifespan.py.
  # runner.py no longer manages the PID directly.

  _maybe_launch_tray()
  _run_uvicorn_server(host, port, workers, reload, i18n)