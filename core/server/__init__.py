"""
────────────────────────────────────
Server Nexe
Author: Jordi Goy 
Location: core/server/__init__.py
Description: Nexe server package. Exposes create_app() (FastAPI factory) and main()

www.jgoy.net · https://server-nexe.org
────────────────────────────────────
"""

from .factory import create_app
from .runner import main

__all__ = ['create_app', 'main']