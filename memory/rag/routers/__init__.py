"""
────────────────────────────────────
Server Nexe
Version: 0.8
Author: Jordi Goy 
Location: memory/rag/routers/__init__.py
Description: No description available.

www.jgoy.net
────────────────────────────────────
"""

from .endpoints import (
  add_document_endpoint,
  search_endpoint,
  upload_file_endpoint,
  health_endpoint,
  info_endpoint,
  files_stats_endpoint,
)

from .ui import (
  serve_ui,
  serve_assets,
  serve_js,
)

__all__ = [
  "add_document_endpoint",
  "search_endpoint",
  "upload_file_endpoint",
  "health_endpoint",
  "info_endpoint",
  "files_stats_endpoint",
  "serve_ui",
  "serve_assets",
  "serve_js",
]