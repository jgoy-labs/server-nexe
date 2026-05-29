"""
------------------------------------
Server Nexe
Author: Jordi Goy
Location: plugins/web_ui_module/api/routes.py
Description: FastAPI route orchestrator for the web_ui module.
             Delegates to submodules: routes_auth, routes_static,
             routes_sessions, routes_files, routes_chat, routes_memory.

www.jgoy.net · https://server-nexe.org
------------------------------------
"""

import asyncio
import logging
from fastapi import APIRouter, Depends

from plugins.web_ui_module.core.memory_helper import get_memory_helper  # noqa: F401 — re-export for test patches
from plugins.web_ui_module.core.compactor import compact_session  # noqa: F401 — re-export for test patches
from plugins.web_ui_module.core.rag_handler import generate_rag_metadata  # noqa: F401 — re-export

# Import RAG header parser (re-export for tests)
try:
    from memory.rag.header_parser import parse_rag_header  # noqa: F401
except ImportError:
    parse_rag_header = None  # type: ignore[assignment]  # noqa: F841

from .routes_auth import make_require_ui_auth, register_auth_routes
from .routes_static import register_static_routes
from .routes_sessions import register_session_routes
from .routes_files import register_file_routes
from .routes_chat import register_chat_routes
from .routes_memory import register_memory_routes

logger = logging.getLogger(__name__)


# ── Session cleanup ──────────────────────────────────────────────

async def _session_cleanup_loop(session_mgr):
    """Background loop that removes inactive sessions every hour."""
    while True:
        await asyncio.sleep(3600)
        try:
            removed = session_mgr.cleanup_inactive(max_age_hours=24)
            if removed:
                logger.info("Session cleanup: %d sessions removed", removed)
        except Exception as e:
            logger.warning("Session cleanup failed: %s", e)


def start_session_cleanup_task(session_mgr):
    """Start session cleanup background task. Call from lifespan startup.

    Returns the asyncio.Task so the caller can cancel it on shutdown (N04).
    """
    return asyncio.create_task(_session_cleanup_loop(session_mgr))


# ── Router factory ───────────────────────────────────────────────

class _SessionManagerProxy:
    """Late-binding proxy to module_instance.session_manager.

    create_router() is invoked by the loader *before* initialize() runs
    (see core/loader/manifest_base._get_module). At that time the plugin
    has not yet created its real SessionManager. Capturing
    module_instance.session_manager as a local would snapshot None (or a
    pre-crypto placeholder), and the routes would never see the real
    manager built in initialize().

    This proxy re-reads module_instance.session_manager on every attribute
    access, so the routes always hit the current live instance.
    """

    __slots__ = ("_module",)

    def __init__(self, module_instance):
        self._module = module_instance

    def __getattr__(self, name: str):
        target = self._module.session_manager
        if target is None:
            raise RuntimeError(
                "SessionManager accessed before WebUIModule.initialize() completed"
            )
        return getattr(target, name)


def create_router(module_instance) -> APIRouter:
    """
    Creates the APIRouter with all web_ui module endpoints.

    Receives module_instance (WebUIModule) to access:
      - module_instance.session_manager
      - module_instance.file_handler
      - module_instance.ui_dir  (static/ui directory)
    """
    # Late-binding proxy so route closures always read the live
    # session_manager, even though the loader calls create_router()
    # before initialize() builds it.
    session_mgr = _SessionManagerProxy(module_instance)
    file_handler = module_instance.file_handler
    _module_ref = module_instance

    router = APIRouter(prefix="/ui", tags=["ui", "web", "demo"])

    # Auth dependency (shared across all submodules)
    _require_ui_auth = make_require_ui_auth()

    # Register all route groups
    register_auth_routes(router, require_ui_auth=_require_ui_auth, session_mgr=session_mgr)
    # Reverted (2026-05-21): the sidecar serves the full UI again. The
    # earlier split (skip static routes in sidecar, let Tauri serve a local
    # copy at public/ui/) caused two parallel copies of the UI to drift —
    # client-side i18n fixes shipped to plugins/web_ui_module/ui/ never
    # reached the Tauri copy, so the bundled DMG kept showing stale strings
    # and a literal {{NEXE_VERSION}} placeholder. Tauri now navigates the
    # webview to http://127.0.0.1:{port}/ once the sidecar is ready.
    register_static_routes(router, module_ref=_module_ref)
    register_session_routes(router, session_mgr=session_mgr, require_ui_auth=_require_ui_auth)
    register_file_routes(router, session_mgr=session_mgr, file_handler=file_handler, require_ui_auth=_require_ui_auth)
    register_chat_routes(router, session_mgr=session_mgr, require_ui_auth=_require_ui_auth)
    register_memory_routes(router, require_ui_auth=_require_ui_auth)

    # Open an external https?:// URL in the system default browser.
    # Used by the sidecar UI to open footer links (server-nexe.com, GitHub,
    # etc.) without relying on Tauri IPC, which is unavailable at HTTP origins.
    @router.get("/open-external", operation_id="open_external_url")
    async def open_external_url(
        url: str,
        _auth: None = Depends(_require_ui_auth),
    ):
        import platform  # noqa: PLC0415
        import subprocess  # noqa: PLC0415
        if not url.startswith(("https://", "http://")):
            from fastapi import HTTPException  # noqa: PLC0415
            raise HTTPException(status_code=400, detail="Only https/http URLs allowed")
        system = platform.system()
        if system == "Darwin":
            subprocess.Popen(["open", url])  # nosec B603 B607
        elif system == "Linux":
            subprocess.Popen(["xdg-open", url])  # nosec B603 B607
        return {"ok": True}

    return router
