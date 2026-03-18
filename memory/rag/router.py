"""
────────────────────────────────────
Server Nexe
Version: 0.8
Author: Jordi Goy 
Location: memory/rag/router.py
Description: FastAPI router facade for RAG module.

www.jgoy.net · https://server-nexe.org
────────────────────────────────────
"""

from typing import Any, Dict

from fastapi import APIRouter, Depends, File, UploadFile

from plugins.security.core.auth import require_api_key
from .constants import MANIFEST
from .routers.endpoints import (
  add_document_endpoint,
  search_endpoint,
  upload_file_endpoint,
  health_endpoint,
  info_endpoint,
  files_stats_endpoint,
)
from .routers.ui import serve_ui, serve_assets, serve_js

router_public = APIRouter(prefix="/rag", tags=["rag"])

@router_public.post("/document", dependencies=[Depends(require_api_key)])
async def _add_document(request: Dict[str, Any]):
  """Add document to RAG. Delegates to endpoints.add_document_endpoint()."""
  return await add_document_endpoint(request)

@router_public.post("/search", dependencies=[Depends(require_api_key)])
async def _search(request: Dict[str, Any]):
  """Search relevant documents. Delegates to endpoints.search_endpoint()."""
  return await search_endpoint(request)

@router_public.post("/upload", dependencies=[Depends(require_api_key)])
async def _upload(file: UploadFile = File(...), metadata: str = "{}"):
  """Upload file to RAG. Delegates to endpoints.upload_file_endpoint()."""
  return await upload_file_endpoint(file, metadata)

@router_public.get("/health")
async def _health():
  """RAG module health check. Delegates to endpoints.health_endpoint()."""
  return await health_endpoint()

@router_public.get("/info")
async def _info():
  """RAG module information. Delegates to endpoints.info_endpoint()."""
  return await info_endpoint()

@router_public.get("/files/stats", dependencies=[Depends(require_api_key)])
async def _files_stats():
  """Uploaded files statistics. Delegates to endpoints.files_stats_endpoint()."""
  return await files_stats_endpoint()

@router_public.get("/ui")
async def _serve_ui():
  """Serve RAG main UI. Delegates to ui.serve_ui()."""
  return await serve_ui()

@router_public.get("/ui/assets/{path:path}")
async def _serve_assets(path: str):
  """Serve UI static assets. Delegates to ui.serve_assets()."""
  return await serve_assets(path)

@router_public.get("/ui/js/{path:path}")
async def _serve_js(path: str):
  """Serve UI JavaScript files. Delegates to ui.serve_js()."""
  return await serve_js(path)

MODULE_METADATA = {
  "name": "rag",
  "version": MANIFEST["version"],
  "description": MANIFEST["description"],
  "router": router_public,
  "prefix": "/ui-control/rag",
  "tags": ["rag", "vector-search", "embeddings"],
  "ui_available": True,
  "ui_path": "/ui-control/rag/"
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