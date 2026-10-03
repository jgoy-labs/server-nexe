"""
────────────────────────────────────
Server Nexe
Author: Jordi Goy
Location: plugins/web_ui_module/module.py
Description: Web UI Module — NexeModule + NexeModuleWithRouter Protocol.
             Web interface to demonstrate Nexe's modular system.

www.jgoy.net · https://server-nexe.org
────────────────────────────────────
"""

import asyncio
import logging
import os
from pathlib import Path
from typing import Dict, Any, Optional

from fastapi import APIRouter
from core.modules.protocol import ModuleMetadata, HealthResult, HealthStatus

from core.sessions import SessionManager
from core.paths.helpers import get_data_dir

logger = logging.getLogger(__name__)


class WebUIModule:
    """
    Web UI plugin for Nexe.
    Implements NexeModule + NexeModuleWithRouter.

    Features:
    - Ollama-style web interface
    - Chat sessions with history and compaction
    - File upload with automatic RAG ingestion
    - Multi-engine response streaming (Ollama, MLX, Llama.cpp)
    - Intent detection (save/recall/chat)
    - Context compacting for long sessions
    """

    def __init__(self) -> None:
        self._initialized = False
        self._init_lock = asyncio.Lock()
        self._router = None
        # The instance lives on server_state (lifespan builds it after
        # encryption, before plugins). Creating one here without crypto
        # followed by a replacement later generated two divergent instances
        # (bug: the router could capture the old reference without crypto,
        # leaving .enc sessions invisible in the UI and saving new ones
        # unencrypted). initialize() binds to the core instance.
        self.session_manager: Optional[SessionManager] = None
        # Paths — available immediately for create_router
        self._plugin_dir = Path(__file__).parent
        self.ui_dir = self._plugin_dir / "ui"
        #: What a user uploads is user data, so it lives with the rest of the
        #: user's data and not inside the plugin's own code tree, where it used
        #: to sit (`ui/uploads`). The packaged app extracts that tree fresh on
        #: every version, and uploads survived it only by an accident of how
        #: `tar` unpacks — nothing guaranteed it. `storage/data/uploads` is the
        #: tree `_resolve_storage_root` already points at `NEXE_DATA_DIR` in
        #: sidecar mode, which exists precisely to be segregated from updates.
        #: Closes the debt `core/files/attach.py` declares about where a second
        #: door's uploads should land. `get_data_dir` is the helper every other
        #: consumer of the data tree already goes through, and it chmods 0700:
        #: uploaded documents are private, and until now they inherited umask.
        self.upload_dir = get_data_dir("uploads")
        #: LEGACY_UPLOAD_DIR is not written any more; it is kept so the
        #: unauthenticated static route can keep refusing it. See the WS5-01
        #: guard in `api/routes_static.py`: a document left behind by an
        #: install from before the move is still a document.
        self.legacy_upload_dir = self.ui_dir / "uploads"
        # C4.3-b: the process-wide FileHandler, not a plugin-private one — same
        # instance /v1/attachments reads off app.state.file_handler. Built here
        # (not deferred to initialize(), unlike session_manager) because it has
        # no crypto/encryption ordering dependency: attach_file_handler() is
        # idempotent, so whichever door (core lifespan or this constructor)
        # runs first creates it and the other just reuses it. create_router()
        # reads module_instance.file_handler eagerly (no late-binding proxy,
        # unlike session_manager — see api/routes.py), so it must already be
        # set here, before initialize() ever runs.
        from core.files import attach_file_handler
        from core.server_state import get_server_state
        self.file_handler = attach_file_handler(get_server_state())
        from core.config import get_server_url
        self.api_base_url = os.getenv("NEXE_API_BASE_URL", get_server_url())

    # --- NexeModule Protocol ---

    @property
    def metadata(self) -> ModuleMetadata:
        """Return static module metadata for the web UI plugin."""
        return ModuleMetadata(
            name="web_ui_module",
            version="1.0.0-beta",
            description="Interficie web estil Ollama per demostrar sistema modular",
            author="Jordi Goy",
            module_type="web_interface",
            quadrant="demo"
        )

    async def initialize(self, context: Dict[str, Any]) -> bool:
        """Plugin initialization"""
        if self._initialized:
            return True
        async with self._init_lock:
            if self._initialized:
                return True

            # Declarative short-circuit — if the manifest has
            # `disabled_in_sidecar=true` and `SidecarConfig.is_sidecar=True`,
            # we do NOT load the module (the UI is served by the Tauri host).
            if self._is_disabled_in_sidecar():
                logger.info(
                    "WebUIModule: disabled_in_sidecar=true and is_sidecar=True; "
                    "skipping initialization (UI served by Tauri host)"
                )
                return False

            try:
                # Consume the process-wide SessionManager. Lifespan attaches
                # it after encryption; if a test reaches initialize() without
                # going through lifespan, attach_session_manager builds the
                # same singleton (never a plugin-private instance).
                from core.server_state import get_server_state
                from core.sessions import attach_session_manager
                self.session_manager = attach_session_manager(get_server_state())

                # Resolve API base URL
                self.api_base_url = self._resolve_api_base_url(context)

                # Ensure directories exist. The upload root is created by
                # get_data_dir() (with 0700) when it is resolved; the legacy
                # one is NOT created — it is only remembered so the static
                # route can keep refusing whatever an older install left there.
                self.ui_dir.mkdir(parents=True, exist_ok=True)

                # Initialize router
                self._init_router()

                self._initialized = True
                logger.info("WebUIModule initialized successfully")
                return True

            except Exception as e:
                logger.error(f"Failed to initialize WebUIModule: {e}")
                return False

    async def shutdown(self) -> None:
        """Cleanup — idempotent"""
        logger.info("WebUIModule shutting down")
        self._initialized = False

    async def health_check(self) -> HealthResult:
        """Module health check"""
        if not self._initialized:
            return HealthResult(
                status=HealthStatus.UNKNOWN,
                message="Module not initialized"
            )

        return HealthResult(
            status=HealthStatus.HEALTHY,
            message="Web UI active",
            details={
                "sessions": len(self.session_manager.list_sessions()),  # type: ignore[union-attr]  # invariant: _initialized=True ⟹ session_manager set
                "ui_dir": str(self.ui_dir)
            }
        )

    # --- NexeModuleWithRouter ---

    def get_router(self) -> APIRouter:
        """Return the FastAPI router for web UI endpoints."""
        return self._router

    def get_router_prefix(self) -> str:
        """Return the URL prefix for web UI routes."""
        return "/ui"

    # --- Router setup ---

    def _init_router(self):
        """Creates router delegating to api/routes.py.

        R6-15 v1.0.4: graceful degradation when the security plugin is absent.
        routes_auth.py exposes ``_SECURITY_AVAILABLE`` so the dependency
        ``require_ui_auth`` returns 503 for protected endpoints (FAIL CLOSED).
        Public endpoints (HTML at ``/``, ``/static/{path}``, ``/health``)
        continue to serve so the user can still see *why* the UI is degraded.
        """
        from .api.routes import create_router
        self._router = create_router(self)
        from .api.routes_auth import _SECURITY_AVAILABLE
        if not _SECURITY_AVAILABLE:
            logger.warning(
                "web_ui_module: security plugin missing, running in degraded "
                "mode (no auth on protected endpoints — they return 503)"
            )

    # --- Public methods ---

    def get_info(self) -> Dict[str, Any]:
        """Return module metadata and active session count."""
        return {
            "name": self.metadata.name,
            "version": self.metadata.version,
            "initialized": self._initialized,
            "sessions": len(self.session_manager.list_sessions()) if self.session_manager else 0,
            "type": self.metadata.module_type,
        }

    def _resolve_api_base_url(self, context: Dict[str, Any]) -> str:
        env_url = os.getenv("NEXE_API_BASE_URL")
        if env_url:
            return env_url.rstrip("/")

        from core.config import DEFAULT_HOST, DEFAULT_PORT
        config = (context or {}).get("config", {}) or {}
        server_config = config.get("core", {}).get("server", {})
        host = server_config.get("host", DEFAULT_HOST)
        port = server_config.get("port", DEFAULT_PORT)
        if host in ("0.0.0.0", "::"):  # nosec B104: comparing to wildcard strings, not binding to them (rewriting to DEFAULT_HOST for client-side URL construction)
            host = DEFAULT_HOST
        return f"http://{host}:{port}"

    # --- Sidecar-aware initialization ---

    def _is_disabled_in_sidecar(self) -> bool:
        """Return True only if manifest `disabled_in_sidecar=true` AND sidecar mode is on.

        Light-touch defensive (lesson `feedback_revert_mental_obligatori`): any
        exception is logged at debug and we return False — keep the historical
        behaviour (load the module) if something fails.
        """
        try:
            try:
                import tomllib
            except ModuleNotFoundError:  # pragma: no cover — Python < 3.11
                import tomli as tomllib  # type: ignore[no-redef]
            manifest_path = self._plugin_dir / "manifest.toml"
            with open(manifest_path, "rb") as fh:
                data = tomllib.load(fh)
            disabled = bool(data.get("module", {}).get("disabled_in_sidecar", False))
            if not disabled:
                return False
            from core.sidecar_config import get_sidecar_config
            return bool(get_sidecar_config().is_sidecar)
        except Exception as exc:
            logger.debug(
                "WebUIModule._is_disabled_in_sidecar: defensive fallback (%s); "
                "treating as NOT disabled",
                exc,
            )
            return False
