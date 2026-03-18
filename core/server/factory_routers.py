"""
────────────────────────────────────
Server Nexe
Version: 0.8
Author: Jordi Goy 
Location: core/server/factory_routers.py
Description: Router Registration for Nexe Server Factory.

www.jgoy.net · https://server-nexe.org
────────────────────────────────────
"""

from fastapi import FastAPI
from typing import Any

from .exception_handlers import register_exception_handlers

def register_core_routers(app: FastAPI, i18n: Any) -> None:
  """
  Register all core routers (UI, endpoints, bootstrap, system).

  Args:
    app: FastAPI application
    i18n: I18n manager
  """
  from core.endpoints import root_router, modules_router, router_v1
  from core.endpoints.bootstrap import router as bootstrap_router
  from core.endpoints.system import get_router as get_system_router
  from core.metrics import metrics_router

  app.include_router(root_router)
  app.include_router(modules_router)

  app.include_router(router_v1)

  app.include_router(metrics_router)

  app.include_router(bootstrap_router)

  app.include_router(get_system_router())

  register_exception_handlers(app, i18n)

__all__ = ['register_core_routers']