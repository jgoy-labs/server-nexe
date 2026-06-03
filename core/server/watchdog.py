"""Parent process watchdog — monitoritza el PID del procés pare (tray/Tauri).

Si el pare mor (Force Quit, Ctrl+C al terminal de `pnpm tauri dev`, crash),
el sidecar es suïcida amb SIGTERM per evitar orfes consumint RAM, ports i
locks (per exemple, lock fcntl de Qdrant a /Users/<user>/.nexe/data/vectors).

Aquest mòdul s'extreu de `core/server/runner.py` (F2.A11) per evitar cicles
d'imports quan `core/lifespan.py` necessita invocar-lo en mode sidecar.
`runner.py` continua reexportant la funció per backward compatibility.
"""
from __future__ import annotations

import logging
import os
import signal
import threading
import time

logger = logging.getLogger(__name__)


def start_parent_watchdog(poll_interval: float = 30.0) -> None:
    """If launched from the tray app (or Tauri sidecar), monitor that the
    parent is still alive.

    When NEXE_TRAY_PID is set, a daemon thread checks every poll_interval
    seconds if that process still exists. If the tray dies (e.g. Force Quit,
    `pnpm tauri dev` killed with Ctrl+C, Tauri crash), the server shuts
    itself down to avoid orphaned processes consuming RAM and holding
    Qdrant locks.

    poll_interval defaults to 30s for standalone (tray) launch; sidecar
    mode passes 2s via `core/lifespan.py` for fast cleanup (F2.A11).
    """
    tray_pid_str = os.environ.get("NEXE_TRAY_PID")
    if not tray_pid_str:
        return

    try:
        tray_pid = int(tray_pid_str)
    except ValueError:
        logger.warning("Invalid NEXE_TRAY_PID=%r — parent watchdog disabled", tray_pid_str)
        return

    def _watchdog() -> None:
        while True:
            # Check immediately on first iteration (no initial sleep window where
            # a parent that died right after spawn would leave us orphaned).
            try:
                os.kill(tray_pid, 0)  # Signal 0 = check if alive, no actual signal
            except ProcessLookupError:
                logger.info(
                    "Tray process (PID %d) no longer running — shutting down server",
                    tray_pid,
                )
                os.kill(os.getpid(), signal.SIGTERM)
                return
            except PermissionError:
                pass  # Process exists but we can't signal it — still alive
            time.sleep(poll_interval)

    t = threading.Thread(target=_watchdog, daemon=True)
    t.start()
    logger.debug(
        "Parent watchdog started — monitoring tray PID %d (poll %.1fs)",
        tray_pid,
        poll_interval,
    )
