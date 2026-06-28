"""
────────────────────────────────────
Server Nexe
Author: Jordi Goy 
Location: core/paths/helpers.py
Description: Path helpers and convenience functions for quick access to Nexe directories.

www.jgoy.net · https://server-nexe.org
────────────────────────────────────
"""

import logging
import os
from pathlib import Path
from typing import Callable, Optional

from .detection import get_repo_root

logger = logging.getLogger(__name__)

def get_project_path(*parts: str) -> Path:
  """
  Build a path relative to the project root.

  Args:
    *parts: Path components (e.g. "plugins", "core", "security")

  Returns:
    Absolute path

  Examples:
    >>> security_dir = get_project_path("plugins", "core", "security")
    >>> config = get_project_path("personality", "server.toml")
  """
  return get_repo_root().joinpath(*parts)

def get_plugins_path(*parts: str) -> Path:
  """Shortcut for paths under plugins/"""
  return get_project_path("plugins", *parts)

def get_memory_path(*parts: str) -> Path:
  """Shortcut for paths under memory/"""
  return get_project_path("memory", *parts)

def get_core_path(*parts: str) -> Path:
  """Shortcut for paths under core/"""
  return get_project_path("core", *parts)

def get_personality_path(*parts: str) -> Path:
  """Shortcut for paths under personality/"""
  return get_project_path("personality", *parts)

def get_storage_path(*parts: str) -> Path:
  """Shortcut for paths under storage/"""
  return get_project_path("storage", *parts)

def get_logs_dir() -> Path:
  """
  Determine the logs directory robustly.

  Priority:
  1. NEXE_LOGS_DIR environment variable (if set)
  2. If running from site-packages (pip install): ~/.nexe/logs/
  3. In development: {project_root}/storage/system-logs/

  Returns:
    Path to the base logs directory

  Examples:
    >>> logs = get_logs_dir()
    >>> security_logs = logs / "security"
    >>> audit_dir = logs / "security" / "audit"
  """
  if core_logs := os.getenv("NEXE_LOGS_DIR"):
    logs_base = Path(core_logs)
    # mode= és modulat per l'umask → chmod posterior per garantir 0o700
    logs_base.mkdir(parents=True, exist_ok=True, mode=0o700)
    os.chmod(logs_base, 0o700)
    return logs_base

  if "site-packages" in str(Path(__file__).resolve()):
    logs_base = Path.home() / ".nexe" / "logs"
    # mode= és modulat per l'umask → chmod posterior per garantir 0o700
    logs_base.mkdir(parents=True, exist_ok=True, mode=0o700)
    os.chmod(logs_base, 0o700)
    return logs_base

  project_root = get_repo_root()
  logs_base = project_root / "storage" / "system-logs"
  # mode= és modulat per l'umask → chmod posterior per garantir 0o700
  logs_base.mkdir(parents=True, exist_ok=True, mode=0o700)
  os.chmod(logs_base, 0o700)
  return logs_base

def get_config_dir() -> Path:
  """
  Return the configuration directory (personality/).
  """
  return get_repo_root() / "personality"

def get_data_dir(subdir: Optional[str] = None) -> Path:
  """
  Return the data directory.

  Priority:
  1. NEXE_DATA_DIR environment variable (Tauri sidecar injection)
  2. {project_root}/storage/data/ (standalone fallback)

  Args:
    subdir: Optional subdirectory within the data directory

  Returns:
    Path to the data directory
  """
  if data_env := os.getenv("NEXE_DATA_DIR"):
    data_dir = Path(data_env)
  else:
    data_dir = get_repo_root() / "storage" / "data"

  if subdir:
    data_dir = data_dir / subdir

  # mode= és modulat per l'umask → chmod posterior per garantir 0o700
  data_dir.mkdir(parents=True, exist_ok=True, mode=0o700)
  os.chmod(data_dir, 0o700)
  return data_dir

def get_cache_dir(subdir: Optional[str] = None) -> Path:
  """
  Return the cache directory.

  Priority:
  1. NEXE_CACHE_DIR environment variable (Tauri sidecar injection)
  2. {project_root}/storage/cache/ (standalone fallback)

  Args:
    subdir: Optional subdirectory within the cache directory

  Returns:
    Path to the cache directory
  """
  if cache_env := os.getenv("NEXE_CACHE_DIR"):
    cache_dir = Path(cache_env)
  else:
    cache_dir = get_repo_root() / "storage" / "cache"

  if subdir:
    cache_dir = cache_dir / subdir

  # mode= és modulat per l'umask → chmod posterior per garantir 0o700
  cache_dir.mkdir(parents=True, exist_ok=True, mode=0o700)
  os.chmod(cache_dir, 0o700)
  return cache_dir

def get_models_dir() -> Path:
  """
  Return the models directory for engine auto-discovery (MLX, llama.cpp, ...).

  Priority:
  1. NEXE_STORAGE_PATH environment variable (Tauri sidecar injection or user override)
  2. NEXE_DATA_DIR/models (sidecar mode — sibling of vectors/, cache/)
  3. storage/models relative to cwd (legacy dev mode)
  4. {project_root}/storage/models (standalone fallback)

  Unlike get_data_dir/get_cache_dir, this does NOT mkdir — models are
  pre-existing assets, not runtime state. The returned path may not exist;
  callers should check `.exists()` before iterating.
  """
  if storage_env := os.getenv("NEXE_STORAGE_PATH", "").strip():
    candidate = Path(storage_env).expanduser()
    if candidate.exists():
      return candidate

  if data_env := os.getenv("NEXE_DATA_DIR", "").strip():
    candidate = Path(data_env).expanduser() / "models"
    if candidate.exists():
      return candidate

  cwd_candidate = Path("storage/models")
  if cwd_candidate.exists():
    return cwd_candidate

  return get_repo_root() / "storage" / "models"


def discover_first_model(predicate: Callable[[Path], bool], label: str) -> str:
  """
  Auto-discover the first model under get_models_dir() matching a predicate.

  Scans the models directory (sorted alphabetically for determinism) and
  returns the absolute, resolved path of the first entry for which
  `predicate(path)` is True. Enables the "drop a model, restart, it just works"
  UX for engine configs (MLX, llama.cpp) without requiring an env var.

  Args:
    predicate: Callable applied to each entry in the models dir; the first
      match (alphabetically) is selected.
    label: Human-readable model description used in the discovery log line.

  Returns:
    Absolute path to the first matching model, or "" if the models directory
    is missing, empty, or nothing matches.
  """
  try:
    models_dir = get_models_dir()
    if models_dir.exists():
      candidates = sorted(p for p in models_dir.iterdir() if predicate(p))
      if candidates:
        path = str(candidates[0].resolve())
        logger.info("Auto-discovered %s at %s", label, path)
        return path
  except Exception as e:
    logger.debug("Auto-discover scan for %s failed: %s", label, e)
  return ""


get_system_logs_dir = get_logs_dir
get_core_root = get_repo_root

__all__ = [
  "get_project_path",
  "get_plugins_path",
  "get_memory_path",
  "get_core_path",
  "get_personality_path",
  "get_storage_path",
  "get_logs_dir",
  "get_config_dir",
  "get_data_dir",
  "get_cache_dir",
  "get_models_dir",
  "discover_first_model",
  "get_system_logs_dir",
  "get_core_root",
]