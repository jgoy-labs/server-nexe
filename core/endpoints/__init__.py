"""
────────────────────────────────────
Server Nexe
Author: Jordi Goy 
Location: core/endpoints/__init__.py
Description: Package d'endpoints FastAPI. Exposa root_router (/, /health, /api/info) i

www.jgoy.net · https://server-nexe.org
────────────────────────────────────
"""

from .root import router as root_router
from .modules import router as modules_router
from .v1 import router_v1
from .sidecar_stubs import router as sidecar_stubs_router

__all__ = ['root_router', 'modules_router', 'router_v1', 'sidecar_stubs_router']