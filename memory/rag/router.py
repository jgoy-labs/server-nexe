"""
────────────────────────────────────
Server Nexe
Author: Jordi Goy
Location: memory/rag/router.py
Description: FastAPI router facade for RAG module (health/info only).

WS6-01/WS6-02: the standalone /rag/{document,search,upload,files/stats}
routes and the /rag/ui admin page were retired — the search was an
ephemeral in-memory substring matcher (not vector search) and the upload
path depended on a FileRAGSource that never existed. The chat pipeline's
RAG (MemoryAPI/Qdrant) is a separate, working path; the public contract
keeps the /v1/rag/* 501 stubs.

www.jgoy.net · https://server-nexe.org
────────────────────────────────────
"""

from fastapi import APIRouter, Depends

from plugins.security.core.auth import require_api_key
from .constants import MANIFEST
from .routers.endpoints import (
  health_endpoint,
  info_endpoint,
)

router_public = APIRouter(prefix="/rag", tags=["rag"])

@router_public.get("/health", dependencies=[Depends(require_api_key)], operation_id="rag_health")
async def _health():
  """RAG module health check. Delegates to endpoints.health_endpoint()."""
  return await health_endpoint()

@router_public.get("/info", dependencies=[Depends(require_api_key)], operation_id="rag_info")
async def _info():
  """RAG module information. Delegates to endpoints.info_endpoint()."""
  return await info_endpoint()

MODULE_METADATA = {
  "name": "rag",
  "version": MANIFEST["version"],
  "description": MANIFEST["description"],
  "router": router_public,
  "prefix": "/ui-control/rag",
  "tags": ["rag"],
  "ui_available": False,
}

def get_router():
  """Returns the module's public router."""
  return router_public

def get_metadata():
  """Returns module metadata."""
  return MODULE_METADATA

__all__ = [
  "router_public",
  "get_router",
  "get_metadata",
]
