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
from core.loader.protocol import ModuleMetadata, HealthResult, HealthStatus

from .core.session_manager import SessionManager
from .core.file_handler import FileHandler

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
        # SessionManager is created in initialize() once crypto_provider is
        # available. Creating it here without crypto followed by a replacement
        # later generated two divergent instances (bug: the router could
        # capture the old reference without crypto, leaving .enc sessions
        # invisible in the UI and saving new ones unencrypted).
        self.session_manager: Optional[SessionManager] = None
        # Paths — available immediately for create_router
        self._plugin_dir = Path(__file__).parent
        self.ui_dir = self._plugin_dir / "ui"
        self.upload_dir = self.ui_dir / "uploads"
        self.file_handler = FileHandler(self.upload_dir)
        from core.config import get_server_url
        self.api_base_url = os.getenv("NEXE_API_BASE_URL", get_server_url())

    # --- NexeModule Protocol ---

    @property
    def metadata(self) -> ModuleMetadata:
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

            try:
                # Create the one and only SessionManager, with crypto if available.
                crypto = None
                try:
                    from core.lifespan import get_server_state
                    crypto = get_server_state().crypto_provider
                except Exception:
                    crypto = None
                self.session_manager = SessionManager(crypto_provider=crypto)

                # Resolve API base URL
                self.api_base_url = self._resolve_api_base_url(context)

                # Ensure directories exist
                self.ui_dir.mkdir(parents=True, exist_ok=True)
                self.upload_dir.mkdir(parents=True, exist_ok=True)

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
                "sessions": len(self.session_manager.list_sessions()),  # type: ignore[union-attr]  # invariant: _initialized=True ⟹ session_manager set (initialize L84 abans de L96)
                "ui_dir": str(self.ui_dir)
            }
        )

    # --- NexeModuleWithRouter ---

    def get_router(self) -> APIRouter:
        return self._router

    def get_router_prefix(self) -> str:
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
