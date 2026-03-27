"""
────────────────────────────────────
Server Nexe
Version: 0.8
Author: Jordi Goy 
Location: core/server/factory_state.py
Description: App State Management for FastAPI Dependency Injection.

www.jgoy.net · https://server-nexe.org
────────────────────────────────────
"""

from fastapi import FastAPI
from pathlib import Path
from typing import Any

def setup_app_state(app: FastAPI, i18n: Any, config: dict, project_root: Path, module_manager: Any) -> None:
  """
  Configure app state for Dependency Injection.

  Args:
    app: FastAPI application
    i18n: I18n manager
    config: Configuration dictionary
    project_root: Project root path
    module_manager: ModuleManager instance
  """
  from core.bootstrap_tokens import initialize_tokens
  from core.lifespan import get_server_state
  from core.endpoints.modules import configure_dependencies as configure_modules_deps

  from core.module_registry import ModuleRegistry
  app.state.module_registry = ModuleRegistry()
  app.state.modules = {}

  server_state = get_server_state()
  server_state.project_root = project_root
  server_state.i18n = i18n
  server_state.config = config
  server_state.module_manager = module_manager
  server_state.configure_modules_callback = configure_modules_deps

  initialize_tokens(project_root)

  app.state.i18n = i18n
  app.state.config = config
  app.state.project_root = project_root
  app.state.module_manager = module_manager
  app.state.container = "0.8.2-DI" # Compatibility flag

__all__ = ['setup_app_state']
