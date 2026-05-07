"""
────────────────────────────────────
Server Nexe
Author: Jordi Goy
Location: core/cli/__init__.py
Description: Nexe Central CLI Orchestrator for module CLIs.

www.jgoy.net · https://server-nexe.org
────────────────────────────────────
"""

from core.version import __version__

from .cli import app, main

__all__ = ["app", "main", "__version__"]