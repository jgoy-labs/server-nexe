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


__all__ = ['create_app', 'main', 'app']

force_reload = os.getenv('NEXE_FORCE_RELOAD', 'false').lower() == 'true'
app = create_app(force_reload=force_reload)

if __name__ == '__main__':
  main()
