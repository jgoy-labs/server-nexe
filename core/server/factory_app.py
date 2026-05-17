"""
────────────────────────────────────
Server Nexe
Author: Jordi Goy 
Location: core/server/factory_app.py
Description: FastAPI Instance Creation for Nexe Server.

www.jgoy.net · https://server-nexe.org
────────────────────────────────────
"""

import logging
import os

from fastapi import FastAPI
from typing import Any

from .helpers import translate
from core.version import __version__

logger = logging.getLogger(__name__)

def create_fastapi_instance(i18n: Any, config: dict) -> FastAPI:
  """
  Create and configure FastAPI application instance.

  Args:
    i18n: I18n manager
    config: Configuration dictionary

  Returns:
    FastAPI application instance
  """
  from core.lifespan import lifespan
  from core.middleware import setup_all_middleware

  # Bug 22 (security): /docs, /redoc, /openapi.json reveal full API map.
  # Disable them outside development mode (NEXE_ENV=development) so production
  # installations don't leak internal endpoint structure.
  # F2.3 part 2: SidecarConfig.is_production és la font canònica; mantenim raw
  # env per distingir "development" vs "test" (ambdós permeten docs).
  _nexe_env = os.getenv("NEXE_ENV", "production").lower()
  try:
    from core.sidecar_config import get_sidecar_config
    if get_sidecar_config().is_production:
      _nexe_env = "production"
  except Exception as exc:
    logger.debug(
      "F2.3 part 2: SidecarConfig unavailable in create_fastapi_instance, "
      "using raw NEXE_ENV: %s",
      exc,
    )
  _docs_enabled = _nexe_env in ("development", "test")

  app = FastAPI(
    title=translate(i18n, "server_core.api.title", f"Nexe {__version__} API"),
    description=translate(
      i18n,
      "server_core.api.description",
      "**Nexe 0.9** — Local AI server with persistent memory.\n\n"
      "## Authentication\n"
      "Most endpoints require the `X-API-Key` header.\n\n"
      "## Endpoint groups\n"
      "- **system** — Health checks, status, and circuit breakers\n"
      "- **v1 / chat** — Chat completion with optional RAG (OpenAI-compatible)\n"
      "- **memory-v1** — Persistent semantic memory (store/search)\n"
      "- **modules** — Loaded modules and plugins\n"
      "- **bootstrap** — Session initialization (development mode)\n"
      "- **system-admin** — Server restart and supervision\n"
      "- **rag-v1 / embeddings-v1 / documents-v1** — Endpoints under development (return 501)"
    ),
    version=__version__,
    lifespan=lifespan,
    docs_url="/docs" if _docs_enabled else None,
    redoc_url="/redoc" if _docs_enabled else None,
    openapi_url="/openapi.json" if _docs_enabled else None,
  )

  setup_all_middleware(app, config, i18n)

  # Standard browser routes that generate unnecessary 404s in logs
  from fastapi.responses import JSONResponse, Response

  @app.get("/.well-known/appspecific/com.chrome.devtools.json", include_in_schema=False, operation_id="chrome_devtools")
  async def chrome_devtools():
      return JSONResponse({})

  @app.get("/.well-known/{path:path}", include_in_schema=False, operation_id="well_known")
  async def well_known(path: str):
      return Response(status_code=204)

  @app.get("/apple-touch-icon{rest:path}", include_in_schema=False, operation_id="apple_touch_icon")
  async def apple_touch_icon(rest: str):
      return Response(status_code=204)

  return app

__all__ = ['create_fastapi_instance']