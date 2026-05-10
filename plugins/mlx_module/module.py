"""
────────────────────────────────────
Server Nexe
Author: Jordi Goy 
Location: plugins/mlx_module/module.py
Description: Nexe module for MLX (Apple Silicon). Adaptation of the original MLXChatNode.

www.jgoy.net · https://server-nexe.org
────────────────────────────────────
"""

import asyncio
import logging
from typing import Dict, Any, List

from fastapi import APIRouter
from core.loader.protocol import ModuleMetadata, HealthResult, HealthStatus
from .core.chat import MLXChatNode
from .core.config import MLXConfig

logger = logging.getLogger(__name__)

class MLXModule:
    """
    Nexe engine for MLX.
    Implements the NexeModule Protocol for Apple Silicon.
    """

    def __init__(self):
        self._node = None
        self._initialized = False
        self._init_lock = asyncio.Lock()
        self._router = None

    @property
    def metadata(self) -> ModuleMetadata:
        """Return static module metadata for the MLX engine."""
        return ModuleMetadata(
            name="mlx_module",
            version="1.0.0-beta",
            description="Ultra-optimized inference engine for Apple Silicon (MLX)",
            author="Jordi Goy",
            module_type="local_llm_option",
            quadrant="core"
        )

    async def initialize(self, context: Dict[str, Any]) -> bool:
        """Initialize via Nexe Launcher."""
        if self._initialized:
            return True
        async with self._init_lock:
            if self._initialized:
                return True

            # Always initialize router
            self._init_router()

            if not MLXConfig.is_metal_available():
                logger.error("MLXModule: Metal is not available. Cannot initialize MLX.")
                logger.info("To use MLX: Ensure you're running on Apple Silicon with Metal support")
                return False

            try:
                mlx_config = MLXConfig.from_env()

                if not mlx_config.validate():
                    logger.error("MLXModule: Configuration invalid. Check NEXE_MLX_MODEL.")
                    logger.info("Expected: NEXE_MLX_MODEL should point to a valid MLX model directory")
                    return False

                self._node = MLXChatNode(config=mlx_config)
                self._initialized = True

                logger.info("MLXModule initialized successfully")
                return True
            except Exception as e:
                logger.error(f"Failed to initialize MLXModule: {e}")
                return False

    def _init_router(self):
        """Create the MLX API router from api/routes.py."""
        from .api.routes import create_router
        self._router = create_router(self)

    def get_router(self) -> APIRouter:
        """Return the FastAPI router for MLX endpoints."""
        return self._router

    def get_router_prefix(self) -> str:
        """Return the URL prefix for MLX routes."""
        return "/mlx"

    async def is_model_loaded(self, model_name: str = "") -> bool:
        """Checks whether the MLX model is loaded in memory."""
        if not self._node:
            return False
        try:
            stats = self._node.get_pool_stats()
            return stats.get("model_loaded", False)
        except Exception:
            return False

    async def chat(
        self, messages: List[Dict[str, str]], system: str = "",
        session_id: str = "default", stream_callback=None, **kwargs,
    ):
        """Main chat method using MLX."""
        if not self._initialized or not self._node:
            raise RuntimeError("MLXModule not initialized")

        inputs = {
            "system": system,
            "messages": messages,
            "session_id": session_id,
            "stream_callback": stream_callback,
            **kwargs,
        }

        return await self._node.execute(inputs)

    async def health_check(self) -> HealthResult:
        """Check MLX module health by querying the inference pool stats."""
        if not self._initialized:
            return HealthResult(status=HealthStatus.UNKNOWN, message="Module not initialized")
        
        try:
            stats = self._node.get_pool_stats()
            return HealthResult(
                status=HealthStatus.HEALTHY,
                message="MLX motor active",
                details=stats
            )
        except Exception as e:
            return HealthResult(status=HealthStatus.DEGRADED, message=str(e))

    async def shutdown(self) -> None:
        """Cleanup logic"""
        if self._node:
            self._node.reset_model()
        self._initialized = False

    def get_info(self) -> Dict[str, Any]:
        """Return module metadata and current cache statistics."""
        return {
            "name": self.metadata.name,
            "version": self.metadata.version,
            "initialized": self._initialized,
            "cache_stats": self._node.get_pool_stats() if self._node else {}
        }
