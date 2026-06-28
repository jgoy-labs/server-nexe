"""
────────────────────────────────────
Server Nexe
Author: Jordi Goy
Location: core/uptime.py
Description: Single source of truth for server uptime (B075-C1). /health and
    /admin/system/health used to report a fixed label ("operational" /
    "available") dressed up as a metric. Both now report the TRUE process uptime
    in seconds, so the health checks stop lying.

    The value comes from the OS process-creation time (psutil) — NOT a marker
    captured when this module is imported, which would under-report by the whole
    module-load / RAG-warmup window (this module is loaded late, during router
    registration). A monotonic marker is kept only as the fallback when psutil
    is unavailable.

www.jgoy.net · https://server-nexe.org
────────────────────────────────────
"""

import os
import time

# Fallback source: a monotonic marker captured at first import. Never negative,
# but misses the pre-import startup window — so it is used ONLY if the OS
# process-creation time (the accurate source below) cannot be read.
_IMPORT_MONO = time.monotonic()

try:
  import psutil

  _PROC = psutil.Process(os.getpid())
  _PROC.create_time()  # probe once: raises if the platform can't supply it
  _HAVE_PSUTIL = True
except Exception:  # psutil missing / sandboxed / create_time unsupported
  _HAVE_PSUTIL = False


def uptime_seconds() -> float:
  """Seconds elapsed since the process actually started.

  Prefers the OS process-creation time so the value is the real uptime,
  independent of when this module happens to be imported. Wall-clock time can
  step backwards (NTP), so the result is clamped at 0. Falls back to a monotonic
  marker captured at import when psutil is unavailable.
  """
  if _HAVE_PSUTIL:
    try:
      return max(0.0, time.time() - _PROC.create_time())
    except Exception:
      pass
  return max(0.0, time.monotonic() - _IMPORT_MONO)


def uptime_str() -> str:
  """Whole-second uptime as a string (``HealthResponse.uptime`` is typed ``str``)."""
  return str(int(uptime_seconds()))
