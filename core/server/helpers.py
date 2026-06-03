"""
────────────────────────────────────
Server Nexe
Author: Jordi Goy 
Location: core/server/helpers.py
Description: Utilitats pel servidor. Funcions: is_port_in_use() (socket check), setup_signal_handlers()

www.jgoy.net · https://server-nexe.org
────────────────────────────────────
"""

import logging
import signal
import socket
import sys

logger = logging.getLogger(__name__)

def is_port_in_use(host: str, port: int) -> bool:
  """
  Check if a port is already in use.

  Args:
    host: Host address to check
    port: Port number to check

  Returns:
    True if port is in use, False otherwise
  """
  with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
    try:
      s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
      s.bind((host, port))
      return False
    except OSError:
      return True

def setup_signal_handlers():
  """
  Setup graceful shutdown on SIGINT (Ctrl+C) and SIGTERM.
  """
  def signal_handler(signum, frame):
    signame = signal.Signals(signum).name
    logger.info("Received signal %s, shutting down server...", signame)
    sys.exit(0)

  signal.signal(signal.SIGINT, signal_handler)
  signal.signal(signal.SIGTERM, signal_handler)

# translate() viu ara a core.i18n_utils (font canònica).
# Re-exportem aquí perquè els call-sites (`from .helpers import translate`)
# segueixin funcionant amb la mateixa signatura.
from core.i18n_utils import translate  # noqa: E402,F401