"""
────────────────────────────────────
Server Nexe
Version: 0.8
Author: Jordi Goy 
Location: core/paths/helpers.py
Description: Path helpers and convenience functions for quick access to Nexe directories.

www.jgoy.net · https://server-nexe.org
────────────────────────────────────
"""

import os
from pathlib import Path
from typing import Optional

from .detection import get_repo_root

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
    logs_base.mkdir(parents=True, exist_ok=True)
    return logs_base

  if "site-packages" in str(Path(__file__).resolve()):
    logs_base = Path.home() / ".nexe" / "logs"
    logs_base.mkdir(parents=True, exist_ok=True)
    return logs_base

  project_root = get_repo_root()
  logs_base = project_root / "storage" / "system-logs"
  logs_base.mkdir(parents=True, exist_ok=True)
  return logs_base

def get_config_dir() -> Path:
  """
  Return the configuration directory (personality/).
  """
  return get_repo_root() / "personality"

def get_data_dir(subdir: Optional[str] = None) -> Path:
  """
  Return the data directory (storage/data/).

  Args:
    subdir: Optional subdirectory within storage/data/

  Returns:
    Path to the data directory
  """
  data_dir = get_repo_root() / "storage" / "data"

  if subdir:
    data_dir = data_dir / subdir

  data_dir.mkdir(parents=True, exist_ok=True)
  return data_dir

def get_cache_dir(subdir: Optional[str] = None) -> Path:
  """
  Return the cache directory (storage/cache/).

  Args:
    subdir: Optional subdirectory within storage/cache/

  Returns:
    Path to the cache directory
  """
  cache_dir = get_repo_root() / "storage" / "cache"

  if subdir:
    cache_dir = cache_dir / subdir

  cache_dir.mkdir(parents=True, exist_ok=True)
  return cache_dir

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
  "get_system_logs_dir",
  "get_core_root",
]