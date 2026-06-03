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
import signal
import subprocess
import time

logger = logging.getLogger(__name__)


def kill_process_on_port(port: int) -> bool:
  """Kill any process using the specified port.

  Returns True if a process was killed, False otherwise.
  """
  try:
    # Find PID using lsof
    result = subprocess.run(  # nosec B603 B607: port is typed int (kill_process_on_port signature); lsof via PATH (mono-user local)
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
