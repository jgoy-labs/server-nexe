"""
────────────────────────────────────
Server Nexe
Version: 0.8
Author: Jordi Goy 
Location: core/server/__init__.py
Description: Package del servidor Nexe. Exposa create_app() (factory FastAPI) i main()

www.jgoy.net
────────────────────────────────────
"""

from .factory import create_app
from .runner import main

__all__ = ['create_app', 'main']