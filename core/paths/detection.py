"""
────────────────────────────────────
Server Nexe
Version: 0.8
Author: Jordi Goy 
Location: core/paths/detection.py
Description: Core detection logic per Nexe root.

www.jgoy.net · https://server-nexe.org
────────────────────────────────────
"""

import os
import logging
import threading
from pathlib import Path
from typing import Optional
from functools import lru_cache
from enum import Enum

from .validation import _is_valid_core_root, _log_detection_success, _log_detection_failure

logger = logging.getLogger(__name__)

class DetectionMethod(Enum):
  """Root detection methods (for metrics and logging)"""
  ENV_VAR = "NEXE_HOME environment variable"
  START_PATH = "start_path parameter (testing/override)"
  MARKER_FILE = "Marker files (server.toml, pyproject.toml, .git)"
  SITE_PACKAGES = "Python site-packages detection"
  FALLBACK_CWD = "Path.cwd() fallback (UNSAFE, deprecated)"

REQUIRED_MARKERS = [
  "personality/server.toml",
]

OPTIONAL_MARKERS = [
  "pyproject.toml",
  ".git",
]

NEXE_CORE_DIRS = ["plugins", "core", "memory", "storage"]

_cache_lock = threading.Lock()
_detection_history = []

def reset_repo_root_cache():
  """
  Clear get_repo_root() cache for testing or dynamic NEXE_HOME changes.

  Thread-safe.

  Typical test usage:
    >>> import os
    >>> os.environ["NEXE_HOME"] = "/new/path"
    >>> reset_repo_root_cache()
    >>> root = get_repo_root()
  """
  with _cache_lock:
    get_repo_root.cache_clear()
    _detection_history.clear()
    logger.debug("get_repo_root() cache cleared")

@lru_cache(maxsize=1)
def get_repo_root(start_path: Optional[Path] = None) -> Path:
  """
  Detect Nexe server root with robust multi-layer strategy.

  Priority order (most to least reliable):
  1. NEXE_HOME environment variable (highest priority, production)
  2. start_path parameter (for testing/explicit override)
  3. Marker file heuristics (server.toml, pyproject.toml, .git)
  4. Site-packages detection (pip install)
  5. ERROR (no unsafe cwd fallback)

  Args:
    start_path: Initial path to start search (optional, for tests)

  Returns:
    Absolute path to Nexe root

  Raises:
    RuntimeError: If no strategy detects a valid root

  Examples:
    >>>
    >>> import os
    >>> os.environ["NEXE_HOME"] = "/opt/nexe"
    >>> root = get_repo_root()
    >>> assert root == Path("/opt/nexe")

    >>>
    >>> root = get_repo_root()
    >>> assert (root / "personality/server.toml").exists()

    >>>
    >>> root = get_repo_root(start_path=Path("/tmp/nexe-test"))
  """

  if core_home := os.getenv("NEXE_HOME"):
    path = Path(core_home).resolve()
    is_valid, reasons = _is_valid_core_root(path)

    if is_valid:
      _log_detection_success(DetectionMethod.ENV_VAR, path, reasons)
      return path
    else:
      _log_detection_failure(DetectionMethod.ENV_VAR, path, reasons)
      raise RuntimeError(
        f"NEXE_HOME points to invalid root: {core_home}\n"
        f"Reasons:\n" + "\n".join(f" {r}" for r in reasons) + "\n\n"
        f"Solutions:\n"
        f" 1. Fix NEXE_HOME: export NEXE_HOME=/correct/path\n"
        f" 2. Remove NEXE_HOME: unset NEXE_HOME\n"
      )

  if start_path:
    path = start_path.resolve()
    is_valid, reasons = _is_valid_core_root(path)

    if is_valid:
      _log_detection_success(DetectionMethod.START_PATH, path, reasons)
      return path
    _log_detection_failure(DetectionMethod.START_PATH, path, reasons)

  if root := _detect_via_markers():
    return root

  if root := _detect_via_site_packages():
    return root

  raise RuntimeError(
    "Could not detect Nexe 0.8 root.\n\n"
    "No strategy found a valid root:\n"
    f" 1. NEXE_HOME env var: {'not set' if not os.getenv('NEXE_HOME') else 'invalid'}\n"
    f" 2. Markers (server.toml): not found\n"
    f" 3. Site-packages: not detected\n\n"
    "Solutions:\n"
    " 1. Set NEXE_HOME: export NEXE_HOME=/path/to/NEXE-0.8\n"
    " 2. Run from root: cd /path/to/NEXE-0.8\n"
    " 3. Pass --project-root: nexe-security --project-root /path/to/NEXE-0.8\n\n"
    f"Current directory: {Path.cwd()}\n"
    f"paths.py location: {Path(__file__).parent}\n"
  )

def _detect_via_markers() -> Optional[Path]:
  """
  Detect root by walking up directories from __file__ looking for markers.

  This is the best strategy for development.
  """
  current = Path(__file__).resolve().parent.parent.parent

  for level in range(10):
    is_valid, reasons = _is_valid_core_root(current)

    if is_valid:
      _log_detection_success(DetectionMethod.MARKER_FILE, current, reasons)
      return current

    parent = current.parent
    if parent == current:
      break
    current = parent

  logger.debug(f"Markers not found walking up from {Path(__file__)}")
  return None

def _detect_via_site_packages() -> Optional[Path]:
  """
  Detect if running from pip installation (site-packages).

  In this case, use ~/.nexe/ as root for data/configuration.
  """
  current_file = Path(__file__).resolve()

  if "site-packages" in str(current_file):
    core_home = Path.home() / ".nexe"
    core_home.mkdir(parents=True, exist_ok=True)

    logger.info(
      f"Detected pip installation. "
      f"Using {core_home} for data/configuration"
    )

    with _cache_lock:
      _detection_history.append({
        'method': DetectionMethod.SITE_PACKAGES,
        'path': str(core_home),
        'success': True
      })

    return core_home

  return None

__all__ = [
  "DetectionMethod",
  "REQUIRED_MARKERS",
  "OPTIONAL_MARKERS",
  "NEXE_CORE_DIRS",
  "get_repo_root",
  "reset_repo_root_cache",
]