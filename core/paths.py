"""
────────────────────────────────────
Server Nexe
Version: 0.8
Author: Jordi Goy 
Location: core/paths.py
Description: FAÇADE per al mòdul paths - Re-export de core.paths/

www.jgoy.net
────────────────────────────────────
"""

from .paths import *

__all__ = [
  "get_repo_root",
  "reset_repo_root_cache",
  "DetectionMethod",
  "REQUIRED_MARKERS",
  "OPTIONAL_MARKERS",
  "NEXE_CORE_DIRS",

  "get_project_path",
  "get_core_path",
  "get_memory_path",
  "get_personality_path",
  "get_storage_path",
  "get_logs_dir",
  "get_config_dir",
  "get_data_dir",
  "get_cache_dir",
  "get_system_logs_dir",
  "get_core_root",
]