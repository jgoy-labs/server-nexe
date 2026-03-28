"""
────────────────────────────────────
Server Nexe
Version: 0.8
Author: Jordi Goy
Location: plugins/web_ui_module/module.py
Description: Modul Web UI — NexeModule + NexeModuleWithRouter Protocol.
             Interficie web per demostrar sistema modular de Nexe.

www.jgoy.net · https://server-nexe.org
────────────────────────────────────
"""

import logging
import os
from pathlib import Path
from typing import Dict, Any

from fastapi import APIRouter
from core.loader.protocol import ModuleMetadata, HealthResult, HealthStatus

from .core.session_manager import SessionManager
from .core.file_handler import FileHandler

logger = logging.getLogger(__name__)


class WebUIModule:
    """
    Plugin UI web per Nexe.
    Implementa NexeModule + NexeModuleWithRouter.

    Funcionalitats:
    - Interficie web estil Ollama
    - Sessions de xat amb historial i compactacio
    - Upload de fitxers amb ingesta RAG automatica
    - Streaming de respostes multi-engine (Ollama, MLX, Llama.cpp)
    - Intent detection (save/recall/chat)
    - Context compacting per sessions llargues
    """

    def __init__(self):
        self._initialized = False
        self._router = None
        # SINGLETON: una sola instancia de SessionManager (fix F5)
        self.session_manager = SessionManager()
        # Paths — disponibles immediatament per create_router
        self._plugin_dir = Path(__file__).parent
        self.ui_dir = self._plugin_dir / "ui"
        self.upload_dir = self.ui_dir / "uploads"
        self.file_handler = FileHandler(self.upload_dir)
        self.api_base_url = os.getenv("NEXE_API_BASE_URL", "http://127.0.0.1:9119")

    # --- NexeModule Protocol ---

    @property
    def metadata(self) -> ModuleMetadata:
        return ModuleMetadata(
            name="web_ui_module",
            version="0.8.5",
            description="Interficie web estil Ollama per demostrar sistema modular",
            author="Jordi Goy",
            module_type="web_interface",
            quadrant="demo"
        )

    async def initialize(self, context: Dict[str, Any]) -> bool:
        """Inicialitzacio del plugin"""
        if self._initialized:
            return True

        try:
            # Re-create SessionManager with crypto if available
            try:
                from core.lifespan import get_server_state
                crypto = get_server_state().crypto_provider
                if crypto:
                    self.session_manager = SessionManager(crypto_provider=crypto)
            except Exception:
                pass  # Keep original SessionManager without crypto

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
        """Health check del modul"""
        if not self._initialized:
            return HealthResult(
                status=HealthStatus.UNKNOWN,
                message="Module not initialized"
            )

        return HealthResult(
            status=HealthStatus.HEALTHY,
            message="Web UI active",
            details={
                "sessions": len(self.session_manager.list_sessions()),
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
        """Crea router delegant a api/routes.py"""
        from .api.routes import create_router
        self._router = create_router(self)

    # --- Metodes publics ---

    def get_info(self) -> Dict[str, Any]:
        return {
            "name": self.metadata.name,
            "version": self.metadata.version,
            "initialized": self._initialized,
            "sessions": len(self.session_manager.list_sessions()),
            "type": self.metadata.module_type,
        }

    def _resolve_api_base_url(self, context: Dict[str, Any]) -> str:
        env_url = os.getenv("NEXE_API_BASE_URL")
        if env_url:
            return env_url.rstrip("/")

        config = (context or {}).get("config", {}) or {}
        server_config = config.get("core", {}).get("server", {})
        host = server_config.get("host", "127.0.0.1")
        port = server_config.get("port", 9119)
        if host in ("0.0.0.0", "::"):
            host = "127.0.0.1"
        return f"http://{host}:{port}"
