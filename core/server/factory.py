"""
────────────────────────────────────
Server Nexe
Author: Jordi Goy 
Location: core/server/factory.py
Description: Application Factory pattern for creating and configuring the Nexe 0.8 FastAPI app.

www.jgoy.net · https://server-nexe.org
────────────────────────────────────
"""

import logging
import threading
import time
from pathlib import Path
from typing import Optional

from fastapi import FastAPI

from .helpers import translate
from .factory_i18n import setup_i18n_and_config
from .factory_app import create_fastapi_instance
from .factory_state import setup_app_state
from .factory_security import setup_security_logger, validate_production_security
from .factory_modules import discover_and_load_modules
from .factory_routers import register_core_routers

logger = logging.getLogger(__name__)

_app_instance: Optional[FastAPI] = None
_app_lock = threading.Lock()
_cache_project_root: Optional[Path] = None

def create_app(project_root: Optional[Path] = None, force_reload: bool = False) -> FastAPI:
  """
  Application factory - creates and configures FastAPI application.

  Singleton cached for performance (0.58s → <0.01s on subsequent calls).
  Thread-safe with double-check locking pattern.
  Refactored into modular components for maintainability.

  Args:
    project_root: Project root directory. If None, auto-detected.
    force_reload: Force rebuild app (useful for tests). Default: False.

  Returns:
    Configured FastAPI application instance

  Performance:
    - First call (cold): ~0.5-0.6s (i18n, config, module discovery)
    - Cached calls (warm): <0.01s (returns existing instance)
    - Tests should call reset_app_cache() in teardown

  Thread-safety:
    Uses threading.Lock with double-check locking to prevent race conditions
    when multiple workers/threads call create_app() simultaneously.
  """
  global _app_instance, _cache_project_root

  if project_root is None:
    project_root = Path(__file__).parent.parent.parent

  if _app_instance is not None and not force_reload:
    if _cache_project_root == project_root:
      logger.debug("Returning cached app instance (fast path <10ms)")
      return _app_instance
    else:
      logger.warning("project_root changed (%s → %s), rebuilding app", _cache_project_root, project_root)
      force_reload = True

  with _app_lock:
    if _app_instance is not None and not force_reload and _cache_project_root == project_root:
      logger.debug("Returning cached app instance (double-check)")
      return _app_instance

    if force_reload and _app_instance is not None:
      logger.info("Force reload requested - clearing singleton cache")
      _app_instance = None
      _cache_project_root = None

    logger.info("Building FastAPI app...")
    logger.info("  force_reload=%s", force_reload)
    start_time = time.time()

    i18n, config, module_manager = setup_i18n_and_config(project_root)

    app = create_fastapi_instance(i18n, config)

    setup_app_state(app, i18n, config, project_root, module_manager)

    setup_security_logger(app, project_root, i18n)

    validate_production_security(i18n, config)

    discover_and_load_modules(app, module_manager, project_root, i18n)

    register_core_routers(app, i18n)

    elapsed = time.time() - start_time
    logger.info(translate(i18n, "core.server.app_created",
               "Application created successfully in {elapsed:.3f}s", elapsed=elapsed))

    _app_instance = app
    _cache_project_root = project_root

    return app

def reset_app_cache() -> None:
  """
  Reset singleton cache - useful for tests.

  Thread-safe cache clearing for testing scenarios where you need
  to rebuild the app from scratch.
  """
  global _app_instance, _cache_project_root
  with _app_lock:
    _app_instance = None
    _cache_project_root = None
    logger.debug("App cache cleared")

__all__ = ['create_app', 'reset_app_cache']