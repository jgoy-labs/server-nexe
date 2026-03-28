"""
────────────────────────────────────
Server Nexe
Author: Jordi Goy 
Location: memory/rag/routers/ui.py
Description: UI endpoints for the RAG module.

www.jgoy.net · https://server-nexe.org
────────────────────────────────────
"""

from pathlib import Path

from fastapi.responses import FileResponse, HTMLResponse

MODULE_PATH = Path(__file__).parent.parent
UI_PATH = MODULE_PATH / "ui"

async def serve_ui():
  """Serveix la UI del RAG module."""
  index_path = UI_PATH / "index.html"

  if not index_path.exists():
    return HTMLResponse(
      content="""
      <html>
      <head><title>RAG Module</title></head>
      <body style="font-family: sans-serif; padding: 40px; text-align: center;">
        <h1>RAG Module</h1>
        <p>Retrieval-Augmented Generation System</p>
        <p><em>UI coming soon...</em></p>
        <hr>
        <p>Use API endpoints:</p>
        <ul style="list-style: none;">
          <li><code>POST /rag/document</code> - Add document</li>
          <li><code>POST /rag/search</code> - Search documents</li>
          <li><code>GET /rag/health</code> - Health check</li>
          <li><code>GET /rag/info</code> - Module info</li>
        </ul>
      </body>
      </html>
      """,
      status_code=200
    )

  with open(index_path, 'r', encoding='utf-8') as f:
    content = f.read()

  return HTMLResponse(content=content)

async def serve_assets(path: str):
  """Serve static assets (CSS)."""
  from plugins.security.core.validators import validate_safe_path

  assets_base = UI_PATH / "assets"
  safe_path = validate_safe_path(assets_base / path, assets_base)

  return FileResponse(safe_path)

async def serve_js(path: str):
  """Serveix els fitxers JavaScript."""
  from plugins.security.core.validators import validate_safe_path

  js_base = UI_PATH / "js"
  safe_path = validate_safe_path(js_base / path, js_base)

  return FileResponse(safe_path, media_type="application/javascript")

__all__ = [
  "serve_ui",
  "serve_assets",
  "serve_js",
]