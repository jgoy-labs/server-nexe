"""
────────────────────────────────────
Server Nexe
Author: Jordi Goy 
Location: memory/memory/manifest.py
Description: Manifest for the Memory module following Nexe 0.8 pattern.

www.jgoy.net · https://server-nexe.org
────────────────────────────────────
"""

from .constants import MANIFEST, MODULE_ID

from .router import router_public

__all__ = [
  "MANIFEST",
  "MODULE_ID",
  "router_public"
]