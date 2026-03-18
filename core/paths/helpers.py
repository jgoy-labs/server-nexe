"""
────────────────────────────────────
Server Nexe
Version: 0.8
Author: Jordi Goy 
Location: core/paths/helpers.py
Description: Path helpers i convenience functions per accés ràpid a directoris Nexe.

www.jgoy.net · https://server-nexe.org
────────────────────────────────────
"""

import os
from pathlib import Path
from typing import Optional

from .detection import get_repo_root

def get_project_path(*parts: str) -> Path:
  """
  Construeix un path relatiu a l'arrel del projecte.

  Args:
    *parts: Components del path (e.g. "plugins", "core", "security")

  Returns:
    Path absolut

  Examples:
    >>> security_dir = get_project_path("plugins", "core", "security")
    >>> config = get_project_path("personality", "server.toml")
  """
  return get_repo_root().joinpath(*parts)

def get_plugins_path(*parts: str) -> Path:
  """Shortcut per paths a plugins/"""
  return get_project_path("plugins", *parts)

def get_memory_path(*parts: str) -> Path:
  """Shortcut per paths a memory/"""
  return get_project_path("memory", *parts)

def get_core_path(*parts: str) -> Path:
  """Shortcut per paths a core/"""
  return get_project_path("core", *parts)

def get_personality_path(*parts: str) -> Path:
  """Shortcut per paths a personality/"""
  return get_project_path("personality", *parts)

def get_storage_path(*parts: str) -> Path:
  """Shortcut per paths a storage/"""
  return get_project_path("storage", *parts)

def get_logs_dir() -> Path:
  """
  Determina el directori de logs de forma robusta.

  ACTUALITZAT v2.0.0: Ara usa get_repo_root() eliminant fallback cwd unsafe.

  Prioritat:
  1. Variable d'entorn NEXE_LOGS_DIR (si existeix)
  2. Si estem en site-packages (pip install): ~/.nexe/logs/
  3. En desenvolupament: {project_root}/storage/system-logs/

  Returns:
    Path al directori base de logs

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
  Retorna el directori de configuració (personality/).

  ACTUALITZAT v2.0.0: Usa get_repo_root() en lloc de find_project_root().
  """
  return get_repo_root() / "personality"

def get_data_dir(subdir: Optional[str] = None) -> Path:
  """
  Retorna el directori de dades (storage/data/).

  ACTUALITZAT v2.0.0: Usa get_repo_root() en lloc de find_project_root().

  Args:
    subdir: Subdirectori opcional dins de storage/data/

  Returns:
    Path al directori de dades
  """
  data_dir = get_repo_root() / "storage" / "data"

  if subdir:
    data_dir = data_dir / subdir

  data_dir.mkdir(parents=True, exist_ok=True)
  return data_dir

def get_cache_dir(subdir: Optional[str] = None) -> Path:
  """
  Retorna el directori de cache (storage/cache/).

  ACTUALITZAT v2.0.0: Usa get_repo_root() en lloc de find_project_root().

  Args:
    subdir: Subdirectori opcional dins de storage/cache/

  Returns:
    Path al directori de cache
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