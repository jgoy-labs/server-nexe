"""
------------------------------------
Server Nexe
Author: Jordi Goy
Location: plugins/web_ui_module/api/routes.py
Description: Orquestrador de rutes FastAPI del modul web_ui.
             Delega a submoduls: routes_auth, routes_static,
             routes_sessions, routes_files, routes_chat, routes_memory.

www.jgoy.net · https://server-nexe.org
------------------------------------
"""

import asyncio
import logging
from fastapi import APIRouter

from plugins.web_ui_module.core.memory_helper import get_memory_helper  # noqa: F401 — re-export for test patches
from plugins.web_ui_module.core.compactor import compact_session  # noqa: F401 — re-export for test patches
from plugins.web_ui_module.core.rag_handler import generate_rag_metadata  # noqa: F401 — re-export

# Import RAG header parser (re-export for tests)
try:
    from memory.rag.header_parser import parse_rag_header  # noqa: F401
except ImportError:
    parse_rag_header = None  # noqa: F841

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
    Crea l'APIRouter amb tots els endpoints del modul web_ui.

    Rep module_instance (WebUIModule) per accedir a:
      - module_instance.session_manager
      - module_instance.file_handler
      - module_instance.ui_dir  (directori static/ui)
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
    register_static_routes(router, module_ref=_module_ref)
    register_session_routes(router, session_mgr=session_mgr, require_ui_auth=_require_ui_auth)
    register_file_routes(router, session_mgr=session_mgr, file_handler=file_handler, require_ui_auth=_require_ui_auth)
    register_chat_routes(router, session_mgr=session_mgr, require_ui_auth=_require_ui_auth)
    register_memory_routes(router, require_ui_auth=_require_ui_auth)

    return router
