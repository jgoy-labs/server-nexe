"""
────────────────────────────────────
Server Nexe
Author: Jordi Goy
Location: plugins/ollama_module/module.py
Description: Ollama Module — NexeModule + NexeModuleWithRouter Protocol.
             Thin wrapper: delegates to core/client.py, core/models.py, core/chat.py.

www.jgoy.net · https://server-nexe.org
────────────────────────────────────
"""

import asyncio
import logging
import os
from typing import Any, AsyncIterator, Dict, List, Optional

try:
    import httpx
except ImportError:
    httpx = None  # type: ignore[assignment]  # Module|None, httpx absent in environments without the dependency

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
    """Wrapper that passes httpx (patchable by tests) to the core.errors helper."""
    return _raw_is_semantic_http_error(exc, httpx)


class OllamaModule:
    """
    Ollama integration module (local LLM option).
    Implements NexeModule + NexeModuleWithRouter Protocol.

    Heavy logic lives in core/client.py, core/models.py, core/chat.py.
    This class only implements the Protocol and delegates.
    """

    DEFAULT_BASE_URL = DEFAULT_BASE_URL

    def __init__(self) -> None:
        """Initialises without params — config from env."""
        self.base_url = resolve_base_url()
        self.i18n = None
        self.timeout = float(os.getenv("NEXE_OLLAMA_CHAT_TIMEOUT", "600.0"))
        self.pull_timeout = float(os.getenv("NEXE_OLLAMA_PULL_TIMEOUT", "600.0"))
        self._initialized = False
        self._init_lock = asyncio.Lock()
        self._router = None
        # Lifecycle state for /status and routes_chat.
        # "uninitialized" → before initialize() runs
        # "ready"         → Ollama daemon reachable, chat-capable
        # "unavailable"   → Ollama not installed or not reachable. Plugin
        #                   stays at the registry so restart_sidecar
        #                   can retry after the user installs Ollama.
        # "error"         → unexpected exception during init.
        self._state: str = "uninitialized"

        # Extracted components
        self.client = OllamaClient(self.base_url)
        self.models_mgr = OllamaModels(self.client)
        self.models_mgr._owner = self  # type: ignore[attr-defined]  # pyright: ignore[reportAttributeAccessIssue]
        self.chat_mgr = OllamaChat(self.client)
        self.chat_mgr._owner = self  # type: ignore[attr-defined]  # pyright: ignore[reportAttributeAccessIssue]

    # --- NexeModule Protocol ---

    @property
    def metadata(self) -> ModuleMetadata:
        """Return static module metadata for the Ollama integration."""
        return ModuleMetadata(
            name="ollama_module",
            version="1.0.0-beta",
            description="Integration with Ollama to run local LLM models",
            author="Jordi Goy",
            module_type="local_llm_option",
            quadrant="core",
            dependencies=[],
            tags=["ollama", "llm", "chat", "local"],
        )

    async def initialize(self, context: Dict[str, Any]) -> bool:
        """Initialisation via Nexe Launcher"""
        if self._initialized:
            return True
        async with self._init_lock:
            if self._initialized:
                return True
            self._init_router()
            try:
                services = context.get("services", {})
                if services and "i18n" in services:
                    self.i18n = services["i18n"]
                await self.client.ensure_ollama_running()
                # Verify Ollama daemon actually responds; if not,
                # mark unavailable (kept at registry so restart_sidecar can
                # retry after the user installs Ollama). Without this check the
                # previous code logged "OllamaModule initialized" even when
                # Ollama was absent — causing chat-time ConnectError post-wizard.
                try:
                    connected = await self.client.check_connection()
                except Exception:
                    connected = False
                if not connected:
                    logger.warning(
                        "OllamaModule: Ollama not reachable at %s. Plugin "
                        "stays at registry with state=unavailable. Install "
                        "Ollama (https://ollama.com/download) and restart "
                        "the app to enable the Ollama backend.",
                        self.base_url,
                    )
                    self._state = "unavailable"
                    self._initialized = False
                    return True  # keep at registry — restart_sidecar may retry
                self._initialized = True
                self._state = "ready"
                logger.info("OllamaModule initialized - base_url=%s", self.base_url)
                return True
            except Exception as e:
                logger.error("Failed to initialize OllamaModule: %s", e)
                self._state = "error"
                return False

    async def shutdown(self) -> None:
        """Cleanup — unloads Ollama models and frees VRAM."""
        if self._initialized:
            await self.client.unload_all_models()
        self.client.reap_process()
        self._initialized = False

    async def health_check(self) -> HealthResult:
        """Async health check for the Ollama module (F7 fix)."""
        if httpx is None:
            return HealthResult(
                status=HealthStatus.UNKNOWN,
                message="httpx not installed",
            )
        # Report not_configured/unavailable explicitly so
        # /status is actionable. The previous DEGRADED was ambiguous (could
        # be temporary network glitch); UNKNOWN+state=unavailable tells the
        # UI to surface the "install Ollama" hint instead.
        if self._state == "unavailable":
            return HealthResult(
                status=HealthStatus.UNKNOWN,
                message="not_configured: Ollama not installed or not reachable",
                details={"base_url": self.base_url, "state": self._state},
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
        """Return the FastAPI router for Ollama endpoints."""
        return self._router

    def get_router_prefix(self) -> str:
        """Return the URL prefix for Ollama routes."""
        return "/ollama"

    def _init_router(self):
        """Creates router delegating to api/routes.py"""
        from .api.routes import create_router
        self._router = create_router(self)

    # --- Public methods (delegated to core/ components) ---

    def get_info(self) -> Dict[str, Any]:
        """Return module metadata including Ollama base URL and init state."""
        return {
            "name": self.metadata.name,
            "version": self.metadata.version,
            "description": self.metadata.description,
            "initialized": self._initialized,
            "base_url": self.base_url,
            "type": self.metadata.module_type,
        }

    def _t(self, key: str, fallback: str, **kwargs) -> str:
        """Helper to translate with fallback."""
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
        """Test connectivity to the Ollama daemon."""
        return await self.client.check_connection()

    async def is_model_loaded(self, model_name: str) -> bool:
        """Check whether a model is currently loaded in Ollama memory."""
        return await self.client.is_model_loaded(model_name)

    async def list_models(self) -> List[Dict[str, Any]]:
        """List all models available in the local Ollama instance."""
        return await self.models_mgr.list_models()

    def pull_model(self, model_name: str) -> AsyncIterator[Dict[str, Any]]:
        """Pull a model from the Ollama registry, yielding progress events."""
        return self.models_mgr.pull_model(model_name)

    async def get_model_info(self, model_name: str) -> Dict[str, Any]:
        """Retrieve detailed metadata for a specific Ollama model."""
        return await self.models_mgr.get_model_info(model_name)

    async def delete_model(self, model_name: str) -> bool:
        """Delete a model from the local Ollama instance."""
        return await self.models_mgr.delete_model(model_name)

    def chat(
        self, model: str, messages: List[Dict[str, str]], stream: bool = True,
        images: Optional[List[str]] = None, thinking_enabled: bool = False,
        top_p: Optional[float] = None,
    ) -> AsyncIterator[Dict[str, Any]]:
        """Send a chat request to Ollama, yielding streamed response chunks."""
        return self.chat_mgr.chat(model, messages, stream=stream, images=images,
                                  thinking_enabled=thinking_enabled, top_p=top_p)
