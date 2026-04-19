"""
------------------------------------
Server Nexe
Location: plugins/web_ui_module/api/routes_static.py
Description: Endpoints for serving UI HTML and static files.

www.jgoy.net · https://server-nexe.org
------------------------------------
"""

import time as _time
import logging
from fastapi import APIRouter, HTTPException, Depends
from fastapi.responses import HTMLResponse, Response

# Cache-bust: changes every time the server restarts
_BOOT_TS = str(int(_time.time()))

from plugins.web_ui_module.messages import get_message, get_i18n

logger = logging.getLogger(__name__)


try:
    from core.version import __version__ as _NEXE_VERSION
except Exception:
    _NEXE_VERSION = "unknown"


def register_static_routes(router: APIRouter, *, module_ref):
    """Register endpoints: GET / (HTML), GET /static/{filename}"""

    # -- GET / (serve_ui) --

    @router.get("/", response_class=HTMLResponse)
    async def serve_ui(i18n=Depends(get_i18n)):
        """Serve the main page with server language injected"""
        html_path = module_ref.ui_dir / "index.html"
        if not html_path.exists():
            raise HTTPException(status_code=404, detail=get_message(i18n, "webui.static.ui_not_found"))
        html = html_path.read_text(encoding="utf-8")
        from plugins.web_ui_module.api.routes_auth import get_server_lang
        lang = get_server_lang()
        html = html.replace('lang="en"', f'lang="{lang}"')
        # data-nexe-lang: read by app.js to apply i18n (CSP-safe, no inline script)
        html = html.replace('<html ', f'<html data-nexe-lang="{lang}" ')
        # Cache-bust: append ?v=timestamp to CSS and JS so the browser reloads them
        html = html.replace('.css"', f'.css?v={_BOOT_TS}"')
        html = html.replace('.js"', f'.js?v={_BOOT_TS}"')
        html = html.replace('{{NEXE_VERSION}}', f'v{_NEXE_VERSION}')
        return HTMLResponse(content=html)

    # -- GET /static/{filename:path} --

    @router.get("/static/{filename:path}")
    async def serve_static(filename: str, i18n=Depends(get_i18n)):
        """Serve CSS/JS"""
        file_path = (module_ref.ui_dir / filename).resolve()
        if not str(file_path).startswith(str(module_ref.ui_dir.resolve())):
            raise HTTPException(status_code=403, detail=get_message(i18n, "webui.static.forbidden"))
        if not file_path.exists():
            raise HTTPException(status_code=404, detail=get_message(i18n, "webui.static.file_not_found"))

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
        # CSS/JS: no-cache so ?v=boot_ts bust always works on restart.
        # Images, fonts, etc.: cacheable for 1h.
        _no_cache_exts = {".css", ".js", ".html"}
        is_no_cache = file_path.suffix in _no_cache_exts
        cache_header = (
            "no-cache, no-store, must-revalidate"
            if is_no_cache
            else "public, max-age=3600"
        )
        content = file_path.read_bytes()
        headers = {
            "Cache-Control": cache_header,
            "Content-Length": str(len(content)),
        }
        if is_no_cache:
            headers["Pragma"] = "no-cache"
            headers["Expires"] = "0"
        return Response(
            content=content,
            media_type=media_type,
            headers=headers,
        )
