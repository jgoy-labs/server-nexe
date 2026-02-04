"""
────────────────────────────────────
Server Nexe
Version: 0.8
Author: Jordi Goy 
Location: core/paths/__init__.py
Description: Façade públic per mòdul paths - unifica accés a detecció Nexe root,

www.jgoy.net
────────────────────────────────────
"""

from .detection import (
  get_repo_root,
  reset_repo_root_cache,
  DetectionMethod,
  REQUIRED_MARKERS,
  OPTIONAL_MARKERS,
  NEXE_CORE_DIRS,
)

from .helpers import (
  get_project_path,
  get_plugins_path,
  get_memory_path,
  get_core_path,
  get_personality_path,
  get_storage_path,
  get_logs_dir,
  get_config_dir,
  get_data_dir,
  get_cache_dir,
  get_system_logs_dir,
  get_core_root,
)

# compat.py mogut a _legacy/ - find_project_root() ja no disponible
# Usar get_repo_root() en el seu lloc

from .validation import (
  _is_valid_core_root,
  _log_detection_success,
  _log_detection_failure,
  _track_cwd_fallback_usage,
)

__all__ = [
  "get_repo_root",
  "reset_repo_root_cache",
  "DetectionMethod",
  "REQUIRED_MARKERS",
  "OPTIONAL_MARKERS",
  "NEXE_CORE_DIRS",

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

__version__ = "2.0.0"
__author__ = "Jordi Goy"
__description__ = "Nexe paths detection and helpers - IRONCLAD v2.0.0"