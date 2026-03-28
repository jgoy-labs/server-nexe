"""
------------------------------------
Server Nexe
Location: plugins/web_ui_module/api/routes_static.py
Description: Endpoints for serving UI HTML and static files.

www.jgoy.net · https://server-nexe.org
------------------------------------
"""

import os as _os
import time as _time
import logging
from fastapi import APIRouter, HTTPException
from fastapi.responses import HTMLResponse, Response

# Cache-bust: changes every time the server restarts
_BOOT_TS = str(int(_time.time()))

from plugins.web_ui_module.messages import get_message

logger = logging.getLogger(__name__)


def register_static_routes(router: APIRouter, *, module_ref):
    """Register endpoints: GET / (HTML), GET /static/{filename}"""

    # -- GET / (serve_ui) --

    @router.get("/", response_class=HTMLResponse)
    async def serve_ui():
        """Serve the main page with server language injected"""
        html_path = module_ref.ui_dir / "index.html"
        if not html_path.exists():
            raise HTTPException(status_code=404, detail=get_message(None, "webui.static.ui_not_found"))
        html = html_path.read_text(encoding="utf-8")
        from plugins.web_ui_module.api.routes_auth import get_server_lang
        lang = get_server_lang()
        html = html.replace('lang="en"', f'lang="{lang}"')
        # data-nexe-lang: read by app.js to apply i18n (CSP-safe, no inline script)
        html = html.replace('<html ', f'<html data-nexe-lang="{lang}" ')
        # Cache-bust: append ?v=timestamp to CSS and JS so the browser reloads them
        html = html.replace('.css"', f'.css?v={_BOOT_TS}"')
        html = html.replace('.js"', f'.js?v={_BOOT_TS}"')
        return HTMLResponse(content=html)

    # -- GET /static/{filename:path} --

    @router.get("/static/{filename:path}")
    async def serve_static(filename: str):
        """Serve CSS/JS"""
        file_path = (module_ref.ui_dir / filename).resolve()
        if not str(file_path).startswith(str(module_ref.ui_dir.resolve())):
            raise HTTPException(status_code=403, detail=get_message(None, "webui.static.forbidden"))
        if not file_path.exists():
            raise HTTPException(status_code=404, detail=get_message(None, "webui.static.file_not_found"))

        # Determine media type
        _mime = {
            ".css":   "text/css; charset=utf-8",
            ".js":    "application/javascript; charset=utf-8",
            ".svg":   "image/svg+xml",
            ".png":   "image/png",
            ".jpg":   "image/jpeg",
            ".jpeg":  "image/jpeg",
            ".ico":   "image/x-icon",
            ".woff2": "font/woff2",
            ".woff":  "font/woff",
            ".html":  "text/html; charset=utf-8",
            ".map":   "application/json",
        }
        media_type = _mime.get(file_path.suffix, "application/octet-stream")

        # Read file and return as Response with proper headers
        content = file_path.read_bytes()
        return Response(
            content=content,
            media_type=media_type,
            headers={
                "Cache-Control": "public, max-age=3600",
                "Content-Length": str(len(content))
            }
        )
