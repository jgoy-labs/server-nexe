"""
────────────────────────────────────
Server Nexe
Author: Jordi Goy
Location: core/app.py
Description: Main entry point and facade for server-nexe FastAPI server.

www.jgoy.net · https://server-nexe.org
────────────────────────────────────
"""

import inspect
import logging
import os
from pathlib import Path
from typing import Optional

from core.env_utils import parse_truthy

from fastapi import FastAPI

from core.server.factory import create_app as _create_app
from core.server.runner import main as _main

if not logging.getLogger().handlers:
  logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
  )

logger = logging.getLogger(__name__)


# Uvicorn limits for the whole product (#918, decision of 23/08/2026, option b).
# They live here and not in the CLI runner because both start-up paths resolve the
# very same app string, "core.app:app": the CLI (core.server.runner) and the
# product (`python -m uvicorn core.app:app ...`, from the nexe-app sidecar and
# src-tauri/lib.rs). Two hand-synchronised lists diverge sooner or later, and #918
# was exactly that: the path the user runs had neither of these.
# Only the two parameters that really diverged are set here. timeout_keep_alive=5
# and limit_max_requests=None are uvicorn's own defaults and need no help.
UVICORN_LIMITS = {
  'timeout_graceful_shutdown': 10,
  'limit_concurrency': 100,
}


def _apply_uvicorn_limits() -> bool:
  """Apply UVICORN_LIMITS onto the live uvicorn.Config, whichever path started the server.

  Uvicorn imports the application from inside Config.load(), so while this module
  is being imported the Config being loaded sits on the call stack — for both
  start-up paths, which is what makes this the one place they cannot diverge.
  Both values are read late (limit_concurrency when a connection arrives,
  timeout_graceful_shutdown at shutdown), so setting them here takes effect.

  Returns:
    True when a live uvicorn.Config was found and updated, False otherwise
    (module imported by a test, a CLI command or any non-server context).
  """
  try:
    from uvicorn.config import Config as _UvicornConfig
  except ImportError:
    logger.debug("uvicorn not installed; no server to guard, skipping uvicorn limits")
    return False

  frame = inspect.currentframe()
  frame = frame.f_back if frame is not None else None
  while frame is not None:
    candidate = frame.f_locals.get('self')
    if isinstance(candidate, _UvicornConfig):
      for name, value in UVICORN_LIMITS.items():
        setattr(candidate, name, value)
      return True
    frame = frame.f_back

  # #950: limit_concurrency is a PROTECTION (the ceiling that stops the server
  # from accepting connections with no brake), not a style preference. If this
  # fires while a real server is starting, it runs without that ceiling and,
  # until now, nothing said so.
  logger.warning(
    "no live uvicorn.Config found on the call stack; %s were NOT applied — "
    "if a server is actually starting, it is running without its concurrency ceiling",
    UVICORN_LIMITS,
  )
  return False


# Applied at import time: uvicorn resolves "core.app:app" from inside Config.load(),
# so this is the moment the live Config is reachable on both paths.
_apply_uvicorn_limits()


def create_app(project_root: Optional[Path] = None, force_reload: bool = False) -> FastAPI:
  """
  Create and configure the FastAPI application (FACADE).

  This is the main application factory that delegates to
  core.server.factory.create_app().

  Args:
    project_root: Project root directory (auto-detected if None)
    force_reload: Force rebuild app (useful for restarts). Default: False.

  Returns:
    Configured FastAPI application instance

  Example:
    >>> app = create_app()
    >>>
  """
  return _create_app(project_root, force_reload)

def main():
  """
  Main entry point for running the server (FACADE).

  Delegates to core.server.runner.main().

  This function:
  - Loads configuration
  - Checks port availability
  - Creates FastAPI app
  - Runs Uvicorn server

  Example:
    $ python -m core.app
  """
  _main()


_app_instance: Optional[FastAPI] = None


def get_app() -> FastAPI:
  """Lazy accessor for the singleton FastAPI app instance.

  Importing core.app no longer eagerly instantiates
  the FastAPI app at import time. The app is created on first attribute access
  (e.g. when uvicorn resolves `core.app:app`), so importing the module on a
  read-only filesystem or in unit tests does not trigger factory side effects.
  """
  global _app_instance
  # Second chance for the limits: if this module was already imported before the
  # server started, the import-time call above ran outside Config.load(). Uvicorn
  # still resolves `app` from inside load(), so the live Config is reachable here.
  _apply_uvicorn_limits()
  if _app_instance is None:
    force_reload = parse_truthy(os.getenv('NEXE_FORCE_RELOAD', 'false'))
    _app_instance = create_app(force_reload=force_reload)
  return _app_instance


def __getattr__(name: str):
  """PEP 562 module-level lazy resolution of `app`.

  Uvicorn and tests use `from core.app import app`, which triggers this hook
  the first time `app` is accessed. After that, the singleton is cached on
  the module so subsequent accesses are O(1) without re-entering this hook.
  """
  if name == 'app':
    instance = get_app()
    globals()['app'] = instance
    return instance
  raise AttributeError(f"module 'core.app' has no attribute {name!r}")


# NOTE: 'app' is intentionally NOT in __all__: it is resolved lazily via
# PEP 562 __getattr__ above and is not a real module-level binding until
# first accessed. Listing it here would trigger ruff F822 / pyright
# reportUnsupportedDunderAll. Consumers should keep using
# `from core.app import app` (PEP 562 dispatches the access) or `get_app()`.
__all__ = ['create_app', 'main', 'get_app', 'UVICORN_LIMITS']


if __name__ == '__main__':
  main()
