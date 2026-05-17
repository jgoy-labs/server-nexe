"""
────────────────────────────────────
Server Nexe
Author: Jordi Goy
Location: core/app.py
Description: Main entry point and facade for Nexe 0.9 FastAPI server.

www.jgoy.net · https://server-nexe.org
────────────────────────────────────
"""

import logging
import os
from pathlib import Path
from typing import Optional

from fastapi import FastAPI

from core.server.factory import create_app as _create_app
from core.server.runner import main as _main

if not logging.getLogger().handlers:
  logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
  )


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

  Resolves BUG-NX-5 (F2.6): importing core.app no longer eagerly instantiates
  the FastAPI app at import time. The app is created on first attribute access
  (e.g. when uvicorn resolves `core.app:app`), so importing the module on a
  read-only filesystem or in unit tests does not trigger factory side effects.
  """
  global _app_instance
  if _app_instance is None:
    force_reload = os.getenv('NEXE_FORCE_RELOAD', 'false').lower() == 'true'
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
__all__ = ['create_app', 'main', 'get_app']


if __name__ == '__main__':
  main()
