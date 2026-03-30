"""
────────────────────────────────────
Server Nexe
Author: Jordi Goy 
Location: core/server/factory_app.py
Description: FastAPI Instance Creation for Nexe Server.

www.jgoy.net · https://server-nexe.org
────────────────────────────────────
"""

from fastapi import FastAPI
from typing import Any

from .helpers import translate

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

  app = FastAPI(
    title=translate(i18n, "server_core.api.title", "Nexe 0.8 API"),
    description=translate(
      i18n,
      "server_core.api.description",
      "**Nexe 0.8** — Local AI server with persistent memory.\n\n"
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
    version="0.9.0",
    lifespan=lifespan
  )

  setup_all_middleware(app, config, i18n)

  # Standard browser routes that generate unnecessary 404s in logs
  from fastapi.responses import JSONResponse, Response

  @app.get("/.well-known/appspecific/com.chrome.devtools.json", include_in_schema=False)
  async def chrome_devtools():
      return JSONResponse({})

  @app.get("/.well-known/{path:path}", include_in_schema=False)
  async def well_known(path: str):
      return Response(status_code=204)

  @app.get("/apple-touch-icon{rest:path}", include_in_schema=False)
  async def apple_touch_icon(rest: str):
      return Response(status_code=204)

  return app

__all__ = ['create_fastapi_instance']