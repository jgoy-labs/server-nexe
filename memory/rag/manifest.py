"""
────────────────────────────────────
Server Nexe
Version: 0.8
Author: Jordi Goy 
Location: memory/rag/manifest.py
Description: Manifest for the RAG module following Nexe 0.8 pattern.

www.jgoy.net
────────────────────────────────────
"""

from .constants import MANIFEST, MODULE_ID

def get_router():
  """
  Retorna el router públic del mòdul.

  Facade que delega a router.py per evitar imports pesats.
  """
  from .router import get_router as _get_router
  return _get_router()

def get_metadata():
  """
  Retorna metadata del mòdul.

  Facade que delega a router.py.
  """
  from .router import get_metadata as _get_metadata
  return _get_metadata()

def __getattr__(name: str):
  if name == "router_public":
    from .router import router_public as _router_public
    globals()["router_public"] = _router_public
    return _router_public
  raise AttributeError(name)

__all__ = [
  "MANIFEST",
  "MODULE_ID",
  "get_router",
  "get_metadata",
]