"""
────────────────────────────────────
Server Nexe
Author: Jordi Goy
Location: plugins/ollama_module/module.py
Description: Modul Ollama — NexeModule + NexeModuleWithRouter Protocol.
             Thin wrapper: delega a core/client.py, core/models.py, core/chat.py.

www.jgoy.net · https://server-nexe.org
────────────────────────────────────
"""

import logging
import os
from typing import Any, AsyncIterator, Dict, List, Optional

try:
    import httpx
except ImportError:
    httpx = None

from fastapi import APIRouter

from core.loader.protocol import HealthResult, HealthStatus, ModuleMetadata
from core.resilience import ollama_breaker  # noqa: F401 — accessed dynamically by core/models.py

from .core.client import (
    DEFAULT_BASE_URL,
    OLLAMA_CONNECTION_TIMEOUT,  # noqa: F401 — re-export used by tests
    OllamaClient,
    resolve_base_url,
)
from .core.chat import OllamaChat
from .core.errors import (
    ModelNotFoundError,  # noqa: F401 — re-export used by tests
    OllamaSemanticError,  # noqa: F401 — re-export used by tests
    is_semantic_http_error as _raw_is_semantic_http_error,
)
from .core.models import OllamaModels

logger = logging.getLogger(__name__)


def _is_semantic_http_error(exc: BaseException) -> bool:
    """Wrapper que passa httpx (patchable pels tests) al helper de core.errors."""
    return _raw_is_semantic_http_error(exc, httpx)


class OllamaModule:
    """
    Modul d'integracio amb Ollama (opcio local per LLM).
    Implementa NexeModule + NexeModuleWithRouter Protocol.

    La logica pesada viu a core/client.py, core/models.py, core/chat.py.
    Aquesta classe nomes implementa el Protocol i delega.
    """

    DEFAULT_BASE_URL = DEFAULT_BASE_URL

    def __init__(self):
        """Inicialitza sense params — config des d'env."""
        self.base_url = resolve_base_url()
        self.i18n = None
        self.timeout = float(os.getenv("NEXE_OLLAMA_CHAT_TIMEOUT", "600.0"))
        self.pull_timeout = float(os.getenv("NEXE_OLLAMA_PULL_TIMEOUT", "600.0"))
        self._initialized = False
        self._router = None

        # Components extrets
        self.client = OllamaClient(self.base_url)
        self.models_mgr = OllamaModels(self.client)
        self.models_mgr._owner = self
        self.chat_mgr = OllamaChat(self.client)
        self.chat_mgr._owner = self

    # --- NexeModule Protocol ---

    @property
    def metadata(self) -> ModuleMetadata:
        return ModuleMetadata(
            name="ollama_module",
            version="0.9.9",
            description="Integracio amb Ollama per executar models LLM locals",
            author="Jordi Goy",
            module_type="local_llm_option",
            quadrant="core",
            dependencies=[],
            tags=["ollama", "llm", "chat", "local"],
        )

    async def initialize(self, context: Dict[str, Any]) -> bool:
        """Inicialitzacio via Nexe Launcher"""
        if self._initialized:
            return True
        self._init_router()
        try:
            services = context.get("services", {})
            if services and "i18n" in services:
                self.i18n = services["i18n"]
            await self.client.ensure_ollama_running()
            self._initialized = True
            logger.info("OllamaModule initialized - base_url=%s", self.base_url)
            return True
        except Exception as e:
            logger.error("Failed to initialize OllamaModule: %s", e)
            return False

    async def shutdown(self) -> None:
        """Cleanup — descarrega models d'Ollama i allibera VRAM."""
        if self._initialized:
            await self.client.unload_all_models()
        self._initialized = False

    async def health_check(self) -> HealthResult:
        """Health check async del modul Ollama (F7 fix)."""
        if httpx is None:
            return HealthResult(
                status=HealthStatus.UNKNOWN,
                message="httpx not installed",
            )
        try:
            connected = await self.check_connection()
            if connected:
                return HealthResult(
                    status=HealthStatus.HEALTHY,
                    message="Ollama reachable",
                    details={"base_url": self.base_url},
                )
            return HealthResult(
                status=HealthStatus.DEGRADED,
                message="Ollama not reachable",
                details={"base_url": self.base_url},
            )
        except Exception as e:
            return HealthResult(status=HealthStatus.DEGRADED, message=str(e))

    # --- NexeModuleWithRouter ---

    def get_router(self) -> APIRouter:
        return self._router

    def get_router_prefix(self) -> str:
        return "/ollama"

    def _init_router(self):
        """Crea router delegant a api/routes.py"""
        from .api.routes import create_router
        self._router = create_router(self)

    # --- Metodes publics (delegats als components core/) ---

    def get_info(self) -> Dict[str, Any]:
        return {
            "name": self.metadata.name,
            "version": self.metadata.version,
            "description": self.metadata.description,
            "initialized": self._initialized,
            "base_url": self.base_url,
            "type": self.metadata.module_type,
        }

    def _t(self, key: str, fallback: str, **kwargs) -> str:
        """Helper per traduir amb fallback."""
        if not self.i18n:
            return fallback.format(**kwargs) if kwargs else fallback
        try:
            value = self.i18n.t(key, **kwargs)
            if value == key:
                return fallback.format(**kwargs) if kwargs else fallback
            return value
        except Exception:
            return fallback.format(**kwargs) if kwargs else fallback

    async def check_connection(self) -> bool:
        return await self.client.check_connection()

    async def is_model_loaded(self, model_name: str) -> bool:
        return await self.client.is_model_loaded(model_name)

    async def list_models(self) -> List[Dict[str, Any]]:
        return await self.models_mgr.list_models()

    def pull_model(self, model_name: str) -> AsyncIterator[Dict[str, Any]]:
        return self.models_mgr.pull_model(model_name)

    async def get_model_info(self, model_name: str) -> Dict[str, Any]:
        return await self.models_mgr.get_model_info(model_name)

    async def delete_model(self, model_name: str) -> bool:
        return await self.models_mgr.delete_model(model_name)

    def chat(
        self, model: str, messages: List[Dict[str, str]], stream: bool = True,
        images: Optional[List[str]] = None, thinking_enabled: bool = False,
    ) -> AsyncIterator[Dict[str, Any]]:
        return self.chat_mgr.chat(model, messages, stream=stream, images=images,
                                  thinking_enabled=thinking_enabled)
