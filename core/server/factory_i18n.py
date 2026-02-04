"""
────────────────────────────────────
Server Nexe
Version: 0.8
Author: Jordi Goy 
Location: core/server/factory_i18n.py
Description: I18n and Configuration Setup for FastAPI Factory.

www.jgoy.net
────────────────────────────────────
"""

from pathlib import Path
from typing import Tuple, Any

def setup_i18n_and_config(project_root: Path) -> Tuple[Any, Any, Any]:
  """
  Initialize i18n system, load configuration, and create ModuleManager.

  Args:
    project_root: Project root directory

  Returns:
    Tuple[ModularI18nManager, dict, ModuleManager]
  """
  from personality.i18n.modular_i18n import ModularI18nManager
  from personality.module_manager import ModuleManager
  from core.config import load_config

  config_path = project_root / "server.toml"
  if not config_path.exists():
    config_path = project_root / "personality" / "server.toml"

  i18n = ModularI18nManager(config_path, project_root)

  config = load_config(project_root, i18n)

  module_manager = ModuleManager(config_path)

  return i18n, config, module_manager

__all__ = ['setup_i18n_and_config']