"""
────────────────────────────────────
Server Nexe
Version: 0.8
Author: Jordi Goy
Location: core/paths/validation.py
Description: Robust Nexe root validation + detection logging.

www.jgoy.net · https://server-nexe.org
────────────────────────────────────
"""

import logging
import threading
from pathlib import Path
from typing import List, Tuple

logger = logging.getLogger(__name__)

NEXE_CORE_DIRS = ["plugins", "core", "memory", "storage"]

_cache_lock = threading.Lock()
_detection_history = []

def _is_valid_core_root(path: Path) -> Tuple[bool, List[str]]:
  """
  Multi-layer validation to ensure a path is a valid Nexe root.

  Criteria (ALL must be met):
  1. Path exists and is a directory
  2. Contains server.toml (REQUIRED)
  3. Has at least 2 of the 4 core directories (plugins, core, memory, storage)

  Args:
    path: Path to validate

  Returns:
    (is_valid, reasons): bool and list of validation messages

  Examples:
    >>> is_valid, reasons = _is_valid_core_root(Path("/opt/nexe"))
    >>> if is_valid:
    >>>   print("Valid root!")
    >>> else:
    >>>   print("\\n".join(reasons))
  """
  reasons = []

  if not path.exists():
    reasons.append(f"[ERROR] Path does not exist: {path}")
    return False, reasons

  if not path.is_dir():
    reasons.append(f"[ERROR] Path is not a directory: {path}")
    return False, reasons

  reasons.append(f"[OK] Path exists: {path}")

  config_file = path / "personality" / "server.toml"
  if not config_file.exists():
    reasons.append(f"[ERROR] Required config not found: {config_file}")
    return False, reasons

  reasons.append(f"[OK] Config found: {config_file}")

  found_dirs = [d for d in NEXE_CORE_DIRS if (path / d).is_dir()]
  if len(found_dirs) < 2:
    reasons.append(
      f"[ERROR] Incomplete Nexe structure: only {found_dirs} "
      f"(requires at least 2 of {NEXE_CORE_DIRS})"
    )
    return False, reasons

  reasons.append(f"[OK] Valid Nexe structure: {found_dirs}")

  return True, reasons

def _log_detection_success(
  method,
  path: Path,
  reasons: List[str],
  warning: bool = False
):
  """Detailed log of successful detection."""
  level = logging.WARNING if warning else logging.INFO
  prefix = "[WARN]" if warning else "[OK]"

  logger.log(
    level,
    f"{prefix} Nexe root detected via {method.value}:\n"
    f"  Path: {path}\n"
    f"  Validation:\n" + "\n".join(f"   {r}" for r in reasons)
  )

  with _cache_lock:
    _detection_history.append({
      'method': method,
      'path': str(path),
      'success': True,
      'warning': warning,
      'reasons': reasons
    })

def _log_detection_failure(
  method,
  path: Path,
  reasons: List[str]
):
  """Detailed log of failed detection."""
  logger.debug(
    f"[FAIL] Detection via {method.value} failed:\n"
    f"  Attempted path: {path}\n"
    f"  Reasons:\n" + "\n".join(f"   {r}" for r in reasons)
  )

  with _cache_lock:
    _detection_history.append({
      'method': method,
      'path': str(path),
      'success': False,
      'reasons': reasons
    })

def _track_cwd_fallback_usage():
  """
  Metric to monitor cwd fallback usage (legacy).

  This allows detecting when the system still depends on cwd
  and planning its removal.
  """
  import traceback
  stack = traceback.extract_stack()

  for frame in reversed(stack[:-3]):
    if 'get_repo_root' not in frame.name:
      caller = f"{frame.filename}:{frame.lineno} ({frame.name})"
      logger.warning("[METRIC] CWD fallback used from: %s", caller)
      break

__all__ = [
  "_is_valid_core_root",
  "_log_detection_success",
  "_log_detection_failure",
  "_track_cwd_fallback_usage",
]