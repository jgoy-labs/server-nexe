"""
────────────────────────────────────
Server Nexe
Author: Jordi Goy 
Location: core/cli/__init__.py
Description: Central Nexe CLI 0.9 - Orchestrator for module CLIs.

www.jgoy.net · https://server-nexe.org
────────────────────────────────────
"""

from .cli import app, main

__all__ = ["app", "main"]
__version__ = "1.0.0"