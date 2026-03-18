"""
────────────────────────────────────
Server Nexe
Version: 0.8
Author: Jordi Goy 
Location: core/cli/__init__.py
Description: CLI Central Nexe 0.8 - Orquestrador de CLIs de mòduls.

www.jgoy.net · https://server-nexe.org
────────────────────────────────────
"""

from .cli import app, main

__all__ = ["app", "main"]
__version__ = "1.0.0"