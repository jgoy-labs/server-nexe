"""
────────────────────────────────────
Server Nexe
Version: 0.8
Author: Jordi Goy 
Location: core/server/factory_app.py
Description: FastAPI Instance Creation for Nexe Server.

www.jgoy.net
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
      "**Nexe 0.8** — Servidor IA local amb memòria persistent.\n\n"
      "## Autenticació\n"
      "La majoria d'endpoints requereixen `X-API-Key` header.\n\n"
      "## Grups d'endpoints\n"
      "- **system** — Health checks, status i circuit breakers\n"
      "- **v1 / chat** — Chat completion amb RAG opcional (OpenAI-compatible)\n"
      "- **memory-v1** — Memòria semàntica persistent (store/search)\n"
      "- **modules** — Mòduls i plugins carregats\n"
      "- **bootstrap** — Inicialització de sessió (mode development)\n"
      "- **system-admin** — Restart i supervisió del servidor\n"
      "- **rag-v1 / embeddings-v1 / documents-v1** — Endpoints en desenvolupament (retornen 501)"
    ),
    version="0.8.0",
    lifespan=lifespan
  )

  setup_all_middleware(app, config, i18n)

  return app

__all__ = ['create_fastapi_instance']