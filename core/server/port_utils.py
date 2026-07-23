"""
────────────────────────────────────
Server Nexe
Author: Jordi Goy
Location: core/server/port_utils.py
Description: Port utilities extracted from core/server/runner.py.
             kill_process_on_port and related TCP port helpers.

www.jgoy.net · https://server-nexe.org
────────────────────────────────────
"""

import logging
import os
import re
import signal
import subprocess
import time

logger = logging.getLogger(__name__)

# WS7-04: same identity pattern as core/cli/cli.py (B109) — only ever kill our own processes.
_NEXE_CMDLINE = re.compile(r"server-nexe|core\.app")


def _pid_is_nexe(pid: int) -> bool:
  """Return True if the PID's command line looks like a server-nexe process."""
  try:
    result = subprocess.run(  # nosec B603 B607: pid is typed int; ps via PATH (mono-user local)
      ["ps", "-p", str(pid), "-o", "command="],
      capture_output=True,
      text=True
    )
    return bool(_NEXE_CMDLINE.search(result.stdout))
  except Exception:
    return False


def kill_process_on_port(port: int) -> bool:
  """Kill any server-nexe process LISTENING on the specified port.

  WS7-04: only TCP listeners are considered (never clients connected to the
  port) and each PID is identity-checked against the nexe cmdline pattern
  before SIGTERM — foreign processes are logged and left alone.

  Returns True only if at least one nexe process was actually signalled.
  """
  try:
    # Find listener PIDs using lsof (listeners only — plain `-ti :port`
    # would also return CLIENT processes connected to the port).
    result = subprocess.run(  # nosec B603 B607: port is typed int (kill_process_on_port signature); lsof via PATH (mono-user local)
      ["lsof", "-ti", f":{port}", "-sTCP:LISTEN"],
      capture_output=True,
      text=True
    )
    if result.returncode == 0 and result.stdout.strip():
      pids = result.stdout.strip().split('\n')
      killed_any = False
      for pid in pids:
        try:
          pid_int = int(pid)
        except ValueError:
          continue
        if not _pid_is_nexe(pid_int):
          logger.warning(
            "Port %s is held by a non-nexe process (PID %s) — refusing to kill it.",
            port, pid_int
          )
          continue
        try:
          os.kill(pid_int, signal.SIGTERM)
          killed_any = True
        except ProcessLookupError:
          # The nexe PID vanished between lsof and SIGTERM (typical race:
          # the old instance finishing its shutdown while the tray relaunches).
          # The goal — our process no longer holds the port — is already met,
          # so this counts as success (matches the pre-WS7-04 behaviour and
          # keeps the headless caller from sys.exit(1) on a now-free port).
          killed_any = True
      if killed_any:
        # Wait a moment for process to terminate
        time.sleep(0.5)
        return True
  except Exception as e:
    logger.debug("Failed to kill process on port %s: %s", port, e)
  return False
