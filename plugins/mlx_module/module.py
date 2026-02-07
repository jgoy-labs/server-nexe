"""
────────────────────────────────────
Server Nexe
Version: 0.8
Author: Jordi Goy 
Location: plugins/mlx_module/module.py
Description: Nexe module for MLX (Apple Silicon). Adapted from the original MLXChatNode.

www.jgoy.net
────────────────────────────────────
"""

import logging
from typing import Optional, Dict, Any, List
from pathlib import Path

from fastapi import APIRouter, HTTPException
from core.loader.protocol import ModuleMetadata, HealthResult, HealthStatus
from .chat import MLXChatNode
from .config import MLXConfig
from personality.i18n.resolve import t_modular

logger = logging.getLogger(__name__)

def _t_log(key: str, fallback: str, **kwargs) -> str:
    return t_modular(f"mlx_module.logs.{key}", fallback, **kwargs)

class MLXModule:
    """
    Nexe engine for MLX.
    Implements the NexeModule Protocol for Apple Silicon.
    """

    def __init__(self):
        self._node = None
        self._initialized = False
        self._router = None

    @property
    def metadata(self) -> ModuleMetadata:
        return ModuleMetadata(
            name="mlx_module",
            version="1.0.0",
            description=t_modular(
                "mlx_module.metadata.description",
                "Ultra-optimized inference engine for Apple Silicon (MLX)"
            ),
            author="Jordi Goy",
            module_type="local_llm_option",
            quadrant="core"
        )

    async def initialize(self, context: Dict[str, Any]) -> bool:
        """Initialize via the Nexe Launcher."""
        if self._initialized:
            return True

        # Inicialitzar router sempre
        self._init_router()

        if not MLXConfig.is_metal_available():
            logger.error(
                _t_log(
                    "metal_unavailable",
                    "MLXModule: Metal is not available. Cannot initialize MLX."
                )
            )
            logger.info(
                _t_log(
                    "metal_unavailable_hint",
                    "To use MLX: Ensure you're running on Apple Silicon with Metal support"
                )
            )
            return False

        try:
            mlx_config = MLXConfig.from_env()

            if not mlx_config.validate():
                logger.error(
                    _t_log(
                        "config_invalid",
                        "MLXModule: Configuration invalid. Check NEXE_MLX_MODEL."
                    )
                )
                logger.info(
                    _t_log(
                        "config_invalid_hint",
                        "Expected: NEXE_MLX_MODEL should point to a valid MLX model directory"
                    )
                )
                return False

            self._node = MLXChatNode(config=mlx_config)
            self._initialized = True

            logger.info(
                _t_log("initialized", "MLXModule initialized successfully")
            )
            return True
        except Exception as e:
            logger.error(
                _t_log(
                    "init_failed",
                    "Failed to initialize MLXModule: {error}",
                    error=str(e),
                )
            )
            return False

    def _init_router(self):
        self._router = APIRouter()
        
        @self._router.get("/info")
        async def get_info():
            return self.get_info()

        @self._router.post("/chat")
        async def chat_endpoint(request: Dict[str, Any]):
            if not self._initialized:
                raise HTTPException(
                    status_code=503,
                    detail=t_modular(
                        "mlx_module.errors.not_initialized",
                        "Module not initialized"
                    )
                )
            
            messages = request.get("messages", [])
            system = request.get("system", "")
            session_id = request.get("session_id", "default")
            
            try:
                result = await self.chat(messages, system, session_id)
                return result
            except Exception as e:
                raise HTTPException(status_code=500, detail=str(e))

    def get_router(self) -> APIRouter:
        return self._router

    def get_router_prefix(self) -> str:
        return "/mlx"

    async def chat(self, messages: List[Dict[str, str]], system: str = "", session_id: str = "default", stream_callback=None):
        """Chat method for MLX."""
        if not self._initialized or not self._node:
            raise RuntimeError(
                t_modular(
                    "mlx_module.errors.not_initialized",
                    "MLXModule not initialized"
                )
            )

        inputs = {
            "system": system,
            "messages": messages,
            "session_id": session_id,
            "stream_callback": stream_callback
        }

        return await self._node.execute(inputs)

    async def health_check(self) -> HealthResult:
        if not self._initialized:
            return HealthResult(
                status=HealthStatus.UNKNOWN,
                message=t_modular(
                    "mlx_module.errors.not_initialized",
                    "Module not initialized"
                )
            )
        
        try:
            stats = self._node.get_pool_stats()
            return HealthResult(
                status=HealthStatus.HEALTHY,
                message=t_modular(
                    "mlx_module.health.active",
                    "MLX engine active"
                ),
                details=stats
            )
        except Exception as e:
            return HealthResult(status=HealthStatus.UNHEALTHY, message=str(e))

    async def shutdown(self) -> None:
        """Cleanup logic."""
        if self._node:
            self._node.reset_model()
        self._initialized = False

    def get_info(self) -> Dict[str, Any]:
        return {
            "name": self.metadata.name,
            "version": self.metadata.version,
            "initialized": self._initialized,
            "cache_stats": self._node.get_pool_stats() if self._node else {}
        }
