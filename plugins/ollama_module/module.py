"""
────────────────────────────────────
Server Nexe
Author: Jordi Goy
Location: plugins/ollama_module/module.py
Description: Modul Ollama — NexeModule + NexeModuleWithRouter Protocol.
             Integracio amb Ollama per executar models LLM locals.

www.jgoy.net · https://server-nexe.org
────────────────────────────────────
"""

import json
import logging
import os
from typing import List, Dict, Any, Optional, AsyncIterator
from pathlib import Path

try:
    import httpx
except ImportError:
    httpx = None

from core.resilience import ollama_breaker, CircuitOpenError
from core.loader.protocol import ModuleMetadata, HealthResult, HealthStatus

from fastapi import APIRouter

logger = logging.getLogger(__name__)

# Configurable timeout via environment variable
OLLAMA_CONNECTION_TIMEOUT = float(os.getenv('NEXE_OLLAMA_CONNECTION_TIMEOUT', '10.0'))


class OllamaModule:
    """
    Modul d'integracio amb Ollama (opcio local per LLM).
    Implementa NexeModule + NexeModuleWithRouter Protocol.

    Funcionalitats:
    - Llistar models locals disponibles
    - Descarregar nous models
    - Chat amb streaming
    - Info detallada de models
    """

    DEFAULT_BASE_URL = "http://localhost:11434"

    def __init__(self):
        """Inicialitza sense params — config des d'env."""
        base_url = (
            os.getenv("NEXE_OLLAMA_HOST")
            or os.getenv("OLLAMA_HOST")
            or self.DEFAULT_BASE_URL
        )
        self.base_url = base_url.rstrip("/")
        self.i18n = None
        self.timeout = float(os.getenv("NEXE_OLLAMA_CHAT_TIMEOUT", "600.0"))
        self.pull_timeout = float(os.getenv("NEXE_OLLAMA_PULL_TIMEOUT", "600.0"))
        self._initialized = False
        self._router = None

    # --- NexeModule Protocol ---

    @property
    def metadata(self) -> ModuleMetadata:
        return ModuleMetadata(
            name="ollama_module",
            version="0.8.5",
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
            # Carregar i18n si disponible al context
            services = context.get("services", {})
            if services and "i18n" in services:
                self.i18n = services["i18n"]

            # Auto-start Ollama if installed but not running
            await self._ensure_ollama_running()

            self._initialized = True
            logger.info("OllamaModule initialized - base_url=%s", self.base_url)
            return True
        except Exception as e:
            logger.error("Failed to initialize OllamaModule: %s", e)
            return False

    async def _ensure_ollama_running(self):
        """Start Ollama if it is installed but not running. macOS + Linux."""
        import shutil
        import subprocess
        import platform

        if httpx is None:
            return

        # Comprovar si ja corre
        try:
            async with httpx.AsyncClient(timeout=3.0) as client:
                resp = await client.get(f"{self.base_url}/api/tags")
                if resp.status_code == 200:
                    logger.info("Ollama already running at %s", self.base_url)
                    return
        except Exception:
            pass

        # No corre — intentar arrencar
        is_macos = platform.system() == "Darwin"

        if is_macos and os.path.exists("/Applications/Ollama.app"):
            try:
                subprocess.Popen(["open", "-g", "-a", "Ollama"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                logger.info("Ollama.app started automatically (macOS)")
            except Exception as e:
                logger.warning("Could not start Ollama.app: %s", e)
        elif shutil.which("ollama"):
            try:
                subprocess.Popen(
                    ["ollama", "serve"],
                    stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                    start_new_session=True  # No morir amb el parent process
                )
                logger.info("ollama serve started automatically")
            except Exception as e:
                logger.warning("Could not start ollama serve: %s", e)
        else:
            logger.info("Ollama not installed — skipping auto-start")
            return

        # Esperar que estigui llest (max 15s)
        import asyncio
        for i in range(15):
            await asyncio.sleep(1)
            try:
                async with httpx.AsyncClient(timeout=2.0) as client:
                    resp = await client.get(f"{self.base_url}/api/tags")
                    if resp.status_code == 200:
                        logger.info("Ollama ready after %ds", i + 1)
                        return
            except Exception:
                pass
        logger.warning("Ollama started but not responding after 15s")

    async def shutdown(self) -> None:
        """Cleanup — descarrega models d'Ollama i allibera VRAM."""
        if self._initialized and httpx is not None:
            try:
                async with httpx.AsyncClient(timeout=OLLAMA_CONNECTION_TIMEOUT) as client:
                    # Obtenir models carregats a VRAM
                    resp = await client.get(f"{self.base_url}/api/ps")
                    if resp.status_code == 200:
                        loaded = resp.json().get("models", [])
                        for loaded_model in loaded:
                            name = loaded_model.get("name", "")
                            if name:
                                await client.post(
                                    f"{self.base_url}/api/generate",
                                    json={"model": name, "keep_alive": 0}
                                )
                                logger.info("Model %s unloaded from VRAM (shutdown)", name)
            except Exception as e:
                logger.debug("Could not unload Ollama models on shutdown: %s", e)
        self._initialized = False

    async def health_check(self) -> HealthResult:
        """Health check async del modul Ollama (F7 fix)."""
        if httpx is None:
            return HealthResult(
                status=HealthStatus.UNKNOWN,
                message="httpx not installed"
            )

        try:
            connected = await self.check_connection()
            if connected:
                return HealthResult(
                    status=HealthStatus.HEALTHY,
                    message="Ollama reachable",
                    details={"base_url": self.base_url}
                )
            return HealthResult(
                status=HealthStatus.UNHEALTHY,
                message="Ollama not reachable",
                details={"base_url": self.base_url}
            )
        except Exception as e:
            return HealthResult(
                status=HealthStatus.DEGRADED,
                message=str(e)
            )

    # --- NexeModuleWithRouter ---

    def get_router(self) -> APIRouter:
        return self._router

    def get_router_prefix(self) -> str:
        return "/ollama"

    def _init_router(self):
        """Crea router delegant a api/routes.py"""
        from .api.routes import create_router
        self._router = create_router(self)

    # --- Metodes publics ---

    def get_info(self) -> Dict[str, Any]:
        return {
            "name": self.metadata.name,
            "version": self.metadata.version,
            "description": self.metadata.description,
            "initialized": self._initialized,
            "base_url": self.base_url,
            "type": self.metadata.module_type,
        }

    # --- Logica negoci (mantinguda intacta) ---

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

    async def is_model_loaded(self, model_name: str) -> bool:
        """Comprova si un model esta carregat a VRAM via /api/ps."""
        try:
            async with httpx.AsyncClient(timeout=OLLAMA_CONNECTION_TIMEOUT) as client:
                response = await client.get(f"{self.base_url}/api/ps")
                if response.status_code == 200:
                    data = response.json()
                    loaded = data.get("models", [])
                    # Match exacte: "qwen3.5:9b" != "qwen3.5:2b"
                    # Ollama retorna noms amb tag (e.g. "qwen3.5:9b")
                    # Si l'usuari no posa tag, Ollama usa ":latest"
                    target = model_name if ":" in model_name else f"{model_name}:latest"
                    for m in loaded:
                        name = m.get("name", "")
                        if name == target:
                            return True
                return False
        except Exception:
            return False

    async def check_connection(self) -> bool:
        """Verifica si Ollama esta accessible."""
        try:
            async with httpx.AsyncClient(timeout=OLLAMA_CONNECTION_TIMEOUT) as client:
                response = await client.get(f"{self.base_url}/api/tags")
                return response.status_code == 200
        except CircuitOpenError:
            logger.warning("Circuit breaker OPEN for Ollama - skipping connection check")
            return False

    @ollama_breaker.protect
    async def list_models(self) -> List[Dict[str, Any]]:
        """List all available local models. Protected by Circuit Breaker."""
        async with httpx.AsyncClient(timeout=self.timeout) as client:
            response = await client.get(f"{self.base_url}/api/tags")
            response.raise_for_status()
            data = response.json()
            models = data.get("models", [])
            msg = self._t("logs.models_found", "Found {count} Ollama models", count=len(models))
            logger.info(msg)
            return models

    async def pull_model(self, model_name: str) -> AsyncIterator[Dict[str, Any]]:
        """Download an Ollama model (streaming progress)."""
        if not await ollama_breaker.check_circuit():
            raise CircuitOpenError(
                f"Circuit [ollama] is OPEN. Will retry in {ollama_breaker.config.timeout_seconds}s"
            )

        try:
            async with httpx.AsyncClient(timeout=self.pull_timeout) as client:
                async with client.stream(
                    "POST", f"{self.base_url}/api/pull", json={"name": model_name}
                ) as response:
                    response.raise_for_status()
                    await ollama_breaker.record_success()
                    async for line in response.aiter_lines():
                        if line.strip():
                            try:
                                data = json.loads(line)
                                yield data
                            except json.JSONDecodeError:
                                logger.warning("JSON invalid a pull: %s", line)
        except (httpx.HTTPError, ConnectionError, TimeoutError) as e:
            await ollama_breaker.record_failure(e)
            logger.error("Error descarregant model %s: %s", model_name, repr(e))
            raise

    @ollama_breaker.protect
    async def get_model_info(self, model_name: str) -> Dict[str, Any]:
        """Obte informacio detallada d'un model. Protected by Circuit Breaker."""
        async with httpx.AsyncClient(timeout=self.timeout) as client:
            response = await client.post(
                f"{self.base_url}/api/show", json={"name": model_name}
            )
            response.raise_for_status()
            return response.json()

    async def chat(
        self, model: str, messages: List[Dict[str, str]], stream: bool = True
    ) -> AsyncIterator[Dict[str, Any]]:
        """Chat amb model Ollama (streaming o directe)."""
        if not await ollama_breaker.check_circuit():
            raise CircuitOpenError(
                f"Circuit [ollama] is OPEN. Will retry in {ollama_breaker.config.timeout_seconds}s"
            )

        try:
            stop_sequences = [
                "<|end|>", "<|endoftext|>", "</s>",
                "<|eot_id|>", "<end_of_turn>", "<|im_end|>",
            ]
            payload = {
                "model": model, "messages": messages,
                "stream": stream, "stop": stop_sequences,
                "think": True
            }

            async with httpx.AsyncClient(timeout=self.timeout) as client:
                if stream:
                    async with client.stream(
                        "POST", f"{self.base_url}/api/chat", json=payload
                    ) as response:
                        response.raise_for_status()
                        await ollama_breaker.record_success()
                        async for line in response.aiter_lines():
                            if line.strip():
                                try:
                                    data = json.loads(line)
                                    yield data
                                except json.JSONDecodeError:
                                    logger.warning("JSON invalid a chat: %s", line)
                else:
                    response = await client.post(
                        f"{self.base_url}/api/chat", json=payload
                    )
                    response.raise_for_status()
                    await ollama_breaker.record_success()
                    yield response.json()

        except (httpx.HTTPError, ConnectionError, TimeoutError) as e:
            await ollama_breaker.record_failure(e)
            logger.error("Chat fallida amb model %s: %s", model, repr(e))
            raise

    @ollama_breaker.protect
    async def delete_model(self, model_name: str) -> bool:
        """Elimina un model local. Protected by Circuit Breaker."""
        async with httpx.AsyncClient(timeout=self.timeout) as client:
            response = await client.delete(
                f"{self.base_url}/api/delete", json={"name": model_name}
            )
            response.raise_for_status()
            logger.info("Model %s eliminat correctament", model_name)
            return True
