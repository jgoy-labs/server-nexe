"""
────────────────────────────────────
Server Nexe
Version: 0.8
Author: Jordi Goy 
Location: plugins/llama_cpp_module/module.py
Description: Mòdul Nexe per a Llama.cpp. Adaptació del LlamaCppChatNode original.

www.jgoy.net
────────────────────────────────────
"""

import logging
from typing import Optional, Dict, Any, List
from pathlib import Path

from fastapi import APIRouter, HTTPException
from core.loader.protocol import ModuleMetadata, HealthResult, HealthStatus
from .chat import LlamaCppChatNode
from .config import LlamaCppConfig
from personality.i18n.resolve import t_modular

logger = logging.getLogger(__name__)

def _t_log(key: str, fallback: str, **kwargs) -> str:
    return t_modular(f"llama_cpp_module.logs.{key}", fallback, **kwargs)

class LlamaCppModule:
    """
    Motor Nexe per a Llama.cpp.
    Implementa el NexeModule Protocol per a la càrrega dinàmica al kernel.
    """

    def __init__(self):
        self._node = None
        self._initialized = False
        self._router = None

    @property
    def metadata(self) -> ModuleMetadata:
        return ModuleMetadata(
            name="llama_cpp_module",
            version="1.0.0",
            description=t_modular(
                "llama_cpp_module.metadata.description",
                "Universal Llama.cpp inference engine (GGUF)"
            ),
            author="Jordi Goy",
            module_type="local_llm_option",
            quadrant="core"
        )

    async def initialize(self, context: Dict[str, Any]) -> bool:
        """Inicialització via Nexe Launcher"""
        if self._initialized:
            return True

        # Inicialitzar router sempre per permetre diagnòstics
        self._init_router()

        try:
            # Carregar config des d'env o context
            llama_config = LlamaCppConfig.from_env()
            
            # Intentar validar si el model existeix abans d'arrancar
            if not llama_config.validate():
                logger.warning(
                    _t_log(
                        "config_validation_failed",
                        "LlamaCppModule: Configuration validation failed. Module started in degraded mode."
                    )
                )
                self._initialized = True
                return True # Permetem arrancar per diagnòstic

            self._node = LlamaCppChatNode(config=llama_config)
            self._initialized = True
            
            logger.info(
                _t_log("initialized", "LlamaCppModule initialized successfully")
            )
            return True
        except Exception as e:
            logger.error(
                _t_log(
                    "init_failed",
                    "Failed to initialize LlamaCppModule: {error}",
                    error=str(e),
                )
            )
            # En cas d'error catastròfic, mantenim initialized=False 
            # però el router ja s'hauria d'haver creat si no ha fallat abans
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
                        "llama_cpp_module.errors.not_initialized",
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
        return "/llama-cpp"

    async def chat(self, messages: List[Dict[str, str]], system: str = "", session_id: str = "default", stream_callback=None):
        """Mètode principal de xat"""
        if not self._initialized or not self._node:
            raise RuntimeError(
                t_modular(
                    "llama_cpp_module.errors.not_initialized",
                    "LlamaCppModule not initialized"
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
                    "llama_cpp_module.errors.not_initialized",
                    "Module not initialized"
                )
            )
        
        try:
            stats = self._node.get_pool_stats()
            return HealthResult(
                status=HealthStatus.HEALTHY,
                message=t_modular(
                    "llama_cpp_module.health.active",
                    "Llama.cpp engine active"
                ),
                details=stats
            )
        except Exception as e:
            return HealthResult(status=HealthStatus.UNHEALTHY, message=str(e))

    async def shutdown(self) -> None:
        """Cleanup logic"""
        if self._node:
            self._node.reset_model()
        self._initialized = False

    def get_info(self) -> Dict[str, Any]:
        return {
            "name": self.metadata.name,
            "version": self.metadata.version,
            "initialized": self._initialized,
            "pool_stats": self._node.get_pool_stats() if self._node else {}
        }
